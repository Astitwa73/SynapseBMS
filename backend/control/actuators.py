"""Writes control commands into a running EnergyPlus simulation.

Actuators are addressed by three parts -- (component_type, control_type, key) --
unlike the two-part addressing used for sensors, and they must be written before
the zone predictor computes loads. Writing at the end of a timestep silently
does nothing until the next one.

Once written, an actuator stays overridden for the rest of the run. Releasing it
requires an explicit reset, which is what returns the building to its own
schedule when the agent has nothing to say.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from backend.control.commands import ControlCommand

logger = logging.getLogger(__name__)

INVALID_HANDLE = -1

ZONE_TEMPERATURE_CONTROL = "Zone Temperature Control"
COOLING_SETPOINT = "Cooling Setpoint"
HEATING_SETPOINT = "Heating Setpoint"
LIGHTS_POWER = ("Lights", "Electricity Rate")


@dataclass(frozen=True, slots=True)
class ActuatorSpec:
    component_type: str
    control_type: str
    key: str


class ActuatorRegistry:
    """Resolves actuator handles once, then applies commands each timestep."""

    def __init__(
        self,
        exchange,
        zone_names: tuple[str, ...],
        lights_by_zone: Mapping[str, str] | None = None,
    ) -> None:
        self._exchange = exchange
        self._zone_names = zone_names
        self._lights_by_zone = dict(lights_by_zone or {})
        self._handles: dict[ActuatorSpec, int] = {}
        self._resolved = False
        self._lighting_baseline_w: dict[str, float] = {}
        self._lighting_overridden = False

    @property
    def is_resolved(self) -> bool:
        return self._resolved

    def specs(self) -> tuple[ActuatorSpec, ...]:
        setpoints = tuple(
            ActuatorSpec(ZONE_TEMPERATURE_CONTROL, control, zone)
            for zone in self._zone_names
            for control in (COOLING_SETPOINT, HEATING_SETPOINT)
        )
        lights = tuple(
            ActuatorSpec(*LIGHTS_POWER, key=self._lights_by_zone[zone])
            for zone in self._zone_names
            if zone in self._lights_by_zone
        )
        return setpoints + lights

    def resolve_handles(self, state) -> None:
        for spec in self.specs():
            self._handles[spec] = self._exchange.get_actuator_handle(
                state, spec.component_type, spec.control_type, spec.key
            )
        self._resolved = True

        missing = [spec for spec, handle in self._handles.items() if handle == INVALID_HANDLE]
        logger.info(
            "Resolved %d/%d actuators", len(self._handles) - len(missing), len(self._handles)
        )
        for spec in missing:
            logger.warning("Actuator unavailable: %s", spec)

    def observe_lighting(self, zone_powers: Mapping[str, float | None]) -> None:
        """Record undimmed lighting power, the baseline a dim fraction scales.

        The Lights actuator takes an absolute wattage, but the agent reasons in
        fractions, and the model's own lighting schedule varies through the day.
        Reading the power back while we are overriding it would feed our own
        output back in, so the baseline is only refreshed while control is idle.
        """
        if self._lighting_overridden:
            return
        for zone, power in zone_powers.items():
            if power is not None:
                self._lighting_baseline_w[zone] = power

    def apply(self, state, command: ControlCommand | None) -> None:
        """Push a command to the actuators, or release them when there is none."""
        if command is None or command.is_noop:
            self.release(state)
            return

        for zone in self._zone_names:
            self._set(state, ActuatorSpec(ZONE_TEMPERATURE_CONTROL, COOLING_SETPOINT, zone),
                      command.cooling_setpoint_c)
            self._set(state, ActuatorSpec(ZONE_TEMPERATURE_CONTROL, HEATING_SETPOINT, zone),
                      command.heating_setpoint_c)

        self._apply_lighting(state, command.lighting_fraction)

    def release(self, state) -> None:
        """Return every actuator to the model's own schedule."""
        if not self._lighting_overridden and not self._handles:
            return

        reset = getattr(self._exchange, "reset_actuator", None)
        if reset is not None:
            for spec, handle in self._handles.items():
                if handle != INVALID_HANDLE:
                    reset(state, handle)
        self._lighting_overridden = False

    def _apply_lighting(self, state, fraction: float | None) -> None:
        if fraction is None:
            return

        for zone in self._zone_names:
            lights_key = self._lights_by_zone.get(zone)
            baseline = self._lighting_baseline_w.get(zone)
            if lights_key is None or baseline is None:
                continue
            self._set(state, ActuatorSpec(*LIGHTS_POWER, key=lights_key), baseline * fraction)
        self._lighting_overridden = True

    def _set(self, state, spec: ActuatorSpec, value: float | None) -> None:
        if value is None:
            return
        handle = self._handles.get(spec, INVALID_HANDLE)
        if handle == INVALID_HANDLE:
            return
        self._exchange.set_actuator_value(state, handle, value)
