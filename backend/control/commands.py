"""What the agent may ask for, and the limits within which it may ask.

The agent is a probabilistic component and is treated as untrusted input. Every
command passes through `clamp` before it can reach an actuator, and clamping
happens at the boundary rather than at the source: a limit enforced upstream can
be defeated by any bug between the limiter and the device.

One constraint here is not a matter of taste. If the heating setpoint ever rises
above the cooling setpoint, EnergyPlus does not warn -- it terminates the
simulation with a DualSetPointWithDeadBand severe error. A hallucinated setpoint
would end the demo, so the deadband invariant is enforced last and
unconditionally, after every other adjustment has been applied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum


class ControlAction(str, Enum):
    """The small, closed set of moves the agent chooses between."""

    HOLD = "hold"
    RAISE_SETPOINT = "raise_setpoint"
    LOWER_SETPOINT = "lower_setpoint"
    REDUCE_LIGHTING = "reduce_lighting"


@dataclass(frozen=True, slots=True)
class ControlCommand:
    """A control intent. Values are targets, not guarantees: see `clamp`."""

    action: ControlAction = ControlAction.HOLD
    cooling_setpoint_c: float | None = None
    heating_setpoint_c: float | None = None
    lighting_fraction: float | None = None
    source: str = "unknown"
    issued_at: datetime | None = None

    @property
    def touches_setpoints(self) -> bool:
        return self.cooling_setpoint_c is not None or self.heating_setpoint_c is not None

    @property
    def is_noop(self) -> bool:
        return not self.touches_setpoints and self.lighting_fraction is None


@dataclass(frozen=True, slots=True)
class SafetyLimits:
    """The band the building is allowed to operate in, whoever asks.

    The bounds are chosen so the deadband invariant is always satisfiable:
    max heating (20.0) is exactly min cooling (22.0) minus the deadband (2.0),
    so clamping can never produce a contradiction it has to resolve arbitrarily.
    """

    min_cooling_setpoint_c: float = 22.0
    max_cooling_setpoint_c: float = 28.0
    min_heating_setpoint_c: float = 16.0
    max_heating_setpoint_c: float = 20.0
    min_deadband_c: float = 2.0
    min_lighting_fraction: float = 0.3
    max_lighting_fraction: float = 1.0
    # Matched to the policies' 1C action step. Set lower, it clamped every single
    # setpoint change, which is noise rather than protection: an action already
    # targets current +/- one step. The limit still binds on an absolute jump,
    # such as a setback straight to 28C or a bad command asking for the extreme.
    max_setpoint_change_c: float = 1.0


@dataclass(frozen=True, slots=True)
class ClampResult:
    """The command that will actually be applied, and why it differs.

    `adjustments` is written for humans: it is what the dashboard shows when the
    agent asks for something the building will not do.
    """

    command: ControlCommand
    adjustments: tuple[str, ...] = ()

    @property
    def was_adjusted(self) -> bool:
        return bool(self.adjustments)


def clamp(
    command: ControlCommand,
    limits: SafetyLimits,
    previous: ControlCommand | None = None,
) -> ClampResult:
    """Force a command inside the safety envelope, reporting every change."""
    adjustments: list[str] = []

    cooling = _finite(command.cooling_setpoint_c, "cooling setpoint", adjustments)
    heating = _finite(command.heating_setpoint_c, "heating setpoint", adjustments)
    lighting = _finite(command.lighting_fraction, "lighting fraction", adjustments)

    if cooling is not None:
        cooling = _bound(
            cooling, limits.min_cooling_setpoint_c, limits.max_cooling_setpoint_c,
            "cooling setpoint", adjustments,
        )
        cooling = _rate_limit(
            cooling, previous.cooling_setpoint_c if previous else None,
            limits.max_setpoint_change_c, "cooling setpoint", adjustments,
        )

    if heating is not None:
        heating = _bound(
            heating, limits.min_heating_setpoint_c, limits.max_heating_setpoint_c,
            "heating setpoint", adjustments,
        )
        heating = _rate_limit(
            heating, previous.heating_setpoint_c if previous else None,
            limits.max_setpoint_change_c, "heating setpoint", adjustments,
        )

    if lighting is not None:
        lighting = _bound(
            lighting, limits.min_lighting_fraction, limits.max_lighting_fraction,
            "lighting fraction", adjustments,
        )

    # Taking over one setpoint means taking over both: leaving the model's
    # scheduled counterpart in place is what inverts the deadband and kills the
    # simulation. Enforced last so no later adjustment can reintroduce it.
    if cooling is not None and heating is None:
        heating = min(cooling - limits.min_deadband_c, limits.max_heating_setpoint_c)
    elif heating is not None and cooling is None:
        cooling = max(heating + limits.min_deadband_c, limits.min_cooling_setpoint_c)

    if cooling is not None and heating is not None:
        required = cooling - limits.min_deadband_c
        if heating > required:
            adjustments.append(
                f"heating setpoint {heating:.1f} -> {required:.1f} "
                f"(deadband must be at least {limits.min_deadband_c:.1f}C)"
            )
            heating = required

    return ClampResult(
        command=replace(
            command,
            cooling_setpoint_c=cooling,
            heating_setpoint_c=heating,
            lighting_fraction=lighting,
            issued_at=command.issued_at or datetime.now(timezone.utc),
        ),
        adjustments=tuple(adjustments),
    )


def _finite(value: float | None, label: str, adjustments: list[str]) -> float | None:
    """Reject NaN and infinity, which arithmetic clamping would happily pass through."""
    if value is None:
        return None
    if not math.isfinite(value):
        adjustments.append(f"{label} {value} rejected (not a finite number)")
        return None
    return float(value)


def _bound(
    value: float, minimum: float, maximum: float, label: str, adjustments: list[str]
) -> float:
    bounded = min(max(value, minimum), maximum)
    if bounded != value:
        limit = "minimum" if bounded == minimum else "maximum"
        adjustments.append(f"{label} {value:.1f} -> {bounded:.1f} (below {limit})"
                           if limit == "minimum"
                           else f"{label} {value:.1f} -> {bounded:.1f} (above {limit})")
    return bounded


def _rate_limit(
    value: float, previous: float | None, max_change: float, label: str,
    adjustments: list[str],
) -> float:
    """Damp step changes, which cause HVAC surges and let the agent oscillate."""
    if previous is None or max_change <= 0:
        return value

    limited = min(max(value, previous - max_change), previous + max_change)
    if limited != value:
        adjustments.append(
            f"{label} {value:.1f} -> {limited:.1f} "
            f"(max {max_change:.1f}C change per step)"
        )
    return limited
