"""How the building decides what to do next.

A policy maps a BuildingContext to a Decision. That is the entire contract, and
it is a Protocol rather than a base class because the LLM policy and the rule
policy share no implementation -- only a shape. Structural typing lets the LLM
be dropped in without inheriting anything, and lets the rule policy stand in as
a fallback when the LLM times out or misbehaves.

The rule policy below is deliberately a priority ladder rather than an
optimiser. It is explainable line by line, deterministic under test, and gives
the LLM a baseline it has to beat -- which is a far better claim than an LLM
that merely produces output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backend.control.commands import ControlAction, ControlCommand, SafetyLimits
from backend.processing.comfort import ComfortBand
from backend.processing.context import BuildingContext, ZoneContext


@dataclass(frozen=True, slots=True)
class Decision:
    """A command plus the account of why it was chosen.

    The reasoning is a deliverable, not a debug aid: it is what the dashboard
    shows and what a judge asks about. It is carried alongside the command so a
    decision can never be displayed without its justification.
    """

    command: ControlCommand
    reasoning: str
    observations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def action(self) -> ControlAction:
        return self.command.action


@runtime_checkable
class DecisionPolicy(Protocol):
    """Anything that can look at the building and decide what to do."""

    name: str

    def decide(self, context: BuildingContext) -> Decision: ...


@dataclass(frozen=True, slots=True)
class PolicyTuning:
    """Thresholds the rule ladder trips on, separated from the logic it drives."""

    comfortable_pmv: float = 0.5
    setback_setpoint_c: float = 28.0
    setback_lighting_fraction: float = 0.3
    comfort_step_c: float = 1.0
    savings_step_c: float = 0.5

    # Below this margin from neutral there is no headroom worth harvesting, and
    # nudging the setpoint would only add churn.
    savings_pmv_headroom: float = 0.25

    # Restated on every occupied decision. Control state is sticky, so a setback
    # dim would otherwise persist through the working day.
    occupied_lighting_fraction: float = 1.0


class RuleBasedPolicy:
    """A priority ladder: the first rule that applies decides.

    Ordering encodes intent. Setback comes first because an empty building is
    the largest and safest saving available. Comfort violations outrank
    opportunistic savings because a complaint costs more than a kilowatt-hour.
    """

    name = "rule-based"

    def __init__(
        self,
        tuning: PolicyTuning | None = None,
        limits: SafetyLimits | None = None,
    ) -> None:
        self._tuning = tuning or PolicyTuning()
        self._limits = limits or SafetyLimits()

    def decide(self, context: BuildingContext) -> Decision:
        observations = observe(context)

        for rule in (self._setback, self._relieve_warmth, self._relieve_cold, self._harvest):
            decision = rule(context, observations)
            if decision is not None:
                return decision

        return self._hold(
            "Building is occupied and within the comfort band with no headroom "
            "to give back. Holding current setpoints.",
            observations,
        )

    def _hold(self, reasoning: str, observations: tuple[str, ...]) -> Decision:
        return Decision(
            command=ControlCommand(
                action=ControlAction.HOLD,
                lighting_fraction=self._tuning.occupied_lighting_fraction,
                source=self.name,
            ),
            reasoning=reasoning,
            observations=observations,
        )

    def _setback(self, context: BuildingContext, observations) -> Decision | None:
        if context.is_occupied:
            return None

        return Decision(
            command=ControlCommand(
                action=ControlAction.RAISE_SETPOINT,
                cooling_setpoint_c=self._tuning.setback_setpoint_c,
                lighting_fraction=self._tuning.setback_lighting_fraction,
                source=self.name,
            ),
            reasoning=(
                f"No occupants detected at {context.clock.label}. Relaxing the cooling "
                f"setpoint to {self._tuning.setback_setpoint_c:.1f}C and dimming lights "
                f"to {self._tuning.setback_lighting_fraction:.0%}; there is no comfort "
                "cost to conditioning an empty building."
            ),
            observations=observations,
        )

    def _relieve_warmth(self, context: BuildingContext, observations) -> Decision | None:
        worst = context.worst_zone
        if worst is None or worst.pmv is None or worst.pmv <= self._tuning.comfortable_pmv:
            return None

        target = self._target_from(context, -self._tuning.comfort_step_c)
        if _is_saturated(target, context.mean_cooling_setpoint_c):
            return self._hold(
                f"{worst.name} is at PMV {worst.pmv:+.2f} ({_band_text(worst)}), but the "
                f"cooling setpoint is already at its {self._limits.min_cooling_setpoint_c:.1f}C "
                "minimum. No further cooling is available within the safety envelope.",
                observations,
            )

        return Decision(
            command=ControlCommand(
                action=ControlAction.LOWER_SETPOINT,
                cooling_setpoint_c=target,
                lighting_fraction=self._tuning.occupied_lighting_fraction,
                source=self.name,
            ),
            reasoning=(
                f"{worst.name} is at PMV {worst.pmv:+.2f} ({_band_text(worst)}), outside "
                f"the +/-{self._tuning.comfortable_pmv:.1f} comfort band, with "
                f"{worst.ppd_pct:.0f}% of occupants likely dissatisfied. Lowering the "
                f"cooling setpoint to {target:.1f}C."
            ),
            observations=observations,
        )

    def _relieve_cold(self, context: BuildingContext, observations) -> Decision | None:
        worst = context.worst_zone
        if worst is None or worst.pmv is None or worst.pmv >= -self._tuning.comfortable_pmv:
            return None

        target = self._target_from(context, self._tuning.comfort_step_c)
        if _is_saturated(target, context.mean_cooling_setpoint_c):
            # Relaxing a cooling setpoint stops the building being cooled; it
            # cannot add heat. Once the setpoint is at its ceiling there is no
            # cooling-side action left, and claiming otherwise would be theatre.
            return self._hold(
                f"{worst.name} is at PMV {worst.pmv:+.2f} ({_band_text(worst)}), but the "
                f"cooling setpoint is already at its {self._limits.max_cooling_setpoint_c:.1f}C "
                "maximum. Warming the zone would require heating control, which this "
                "agent does not manage; the zone will recover as occupancy and solar "
                "gains build.",
                observations,
            )

        return Decision(
            command=ControlCommand(
                action=ControlAction.RAISE_SETPOINT,
                cooling_setpoint_c=target,
                lighting_fraction=self._tuning.occupied_lighting_fraction,
                source=self.name,
            ),
            reasoning=(
                f"{worst.name} is at PMV {worst.pmv:+.2f} ({_band_text(worst)}); the zone "
                f"is being overcooled. Raising the cooling setpoint to {target:.1f}C to "
                "recover comfort and reduce cooling load at the same time."
            ),
            observations=observations,
        )

    def _harvest(self, context: BuildingContext, observations) -> Decision | None:
        """Give back comfort headroom as energy, while staying inside the band."""
        mean_pmv = context.mean_pmv
        if mean_pmv is None:
            return None

        headroom = self._tuning.comfortable_pmv - mean_pmv
        if headroom < self._tuning.savings_pmv_headroom:
            return None

        target = self._target_from(context, self._tuning.savings_step_c)
        if _is_saturated(target, context.mean_cooling_setpoint_c):
            return None

        return Decision(
            command=ControlCommand(
                action=ControlAction.RAISE_SETPOINT,
                cooling_setpoint_c=target,
                lighting_fraction=self._tuning.occupied_lighting_fraction,
                source=self.name,
            ),
            reasoning=(
                f"Mean PMV is {mean_pmv:+.2f}, {headroom:.2f} inside the comfort limit. "
                f"Raising the cooling setpoint to {target:.1f}C converts that margin into "
                "reduced cooling energy while occupants stay comfortable."
            ),
            observations=observations,
        )

    def _target_from(self, context: BuildingContext, delta_c: float) -> float | None:
        """Move from where the building actually is, not from an assumed baseline."""
        current = context.mean_cooling_setpoint_c
        if current is None:
            return None
        return min(
            max(current + delta_c, self._limits.min_cooling_setpoint_c),
            self._limits.max_cooling_setpoint_c,
        )


def _is_saturated(target: float | None, current: float | None) -> bool:
    """True when the proposed setpoint would not actually move anything."""
    if target is None:
        return True
    if current is None:
        return False
    return abs(target - current) < 1e-6


def _band_text(zone: ZoneContext) -> str:
    return zone.comfort.value if zone.comfort else "unknown"


def observe(context: BuildingContext) -> tuple[str, ...]:
    """The facts behind the decision, for the dashboard and the audit trail."""
    observations = [
        f"time {context.clock.label}",
        f"occupancy {context.total_occupancy:.0f}",
    ]
    if context.mean_pmv is not None:
        observations.append(f"mean PMV {context.mean_pmv:+.2f}")
    if context.mean_cooling_setpoint_c is not None:
        observations.append(f"cooling setpoint {context.mean_cooling_setpoint_c:.1f}C")
    if context.total_power_kw is not None:
        observations.append(f"load {context.total_power_kw:.1f} kW")
    if context.site.outdoor_air_temperature_c is not None:
        observations.append(f"outdoor {context.site.outdoor_air_temperature_c:.1f}C")
    if context.peak_co2_ppm is not None:
        observations.append(f"peak CO2 {context.peak_co2_ppm:.0f} ppm")
    return tuple(observations)


def comfort_is_acceptable(context: BuildingContext, tuning: PolicyTuning | None = None) -> bool:
    """Shared predicate so policies and reports agree on what 'comfortable' means."""
    settings = tuning or PolicyTuning()
    return all(
        zone.comfort == ComfortBand.COMFORTABLE
        for zone in context.occupied_zones
        if zone.comfort is not None
    ) and (context.mean_pmv is None or abs(context.mean_pmv) <= settings.comfortable_pmv)
