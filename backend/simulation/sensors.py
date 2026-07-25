"""Reads sensor values out of a running EnergyPlus simulation.

Two EnergyPlus rules shape this module:

1. An output variable that was not requested before the run starts does not
   exist during the run, and its handle is permanently -1.
2. Handles cannot be resolved until the simulation is fully initialised. Asking
   too early also yields -1, and that -1 never becomes valid.

So the lifecycle is: request everything up front, resolve handles exactly once on
the first timestep where real data exists, then read by cached handle forever.

The sensor set is declared as data rather than code. Adding a measurement means
adding one line to a table, and the read path never grows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.simulation.state import (
    EnergyReading,
    SensorSnapshot,
    SimulationClock,
    SiteReading,
    ZoneReading,
)

logger = logging.getLogger(__name__)

INVALID_HANDLE = -1

# The reserved EnergyPlus key for site-level (weather) variables.
SITE_KEY = "Environment"

# (ZoneReading field, EnergyPlus output variable name), keyed per zone.
ZONE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("air_temperature_c", "Zone Mean Air Temperature"),
    ("relative_humidity_pct", "Zone Air Relative Humidity"),
    ("occupant_count", "Zone People Occupant Count"),
    ("cooling_setpoint_c", "Zone Thermostat Cooling Setpoint Temperature"),
    ("heating_setpoint_c", "Zone Thermostat Heating Setpoint Temperature"),
    ("lighting_power_w", "Zone Lights Electricity Rate"),
    ("ventilation_mass_flow_kg_s", "Zone Mechanical Ventilation Mass Flow Rate"),
)

# (SiteReading field, EnergyPlus output variable name), keyed by SITE_KEY.
SITE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("outdoor_air_temperature_c", "Site Outdoor Air Drybulb Temperature"),
    ("outdoor_relative_humidity_pct", "Site Outdoor Air Relative Humidity"),
    ("direct_solar_w_per_m2", "Site Direct Solar Radiation Rate per Area"),
)

# (EnergyReading field, EnergyPlus meter name). Meters need no request step.
#
# The first three are system-category meters and are disjoint, so they sum to
# whole-building electricity. The rest are end-use meters covering the same
# energy along a different axis -- useful for attribution, never for totalling.
METERS: tuple[tuple[str, str], ...] = (
    ("building_electricity_j", "Electricity:Building"),
    ("hvac_electricity_j", "Electricity:HVAC"),
    ("plant_electricity_j", "Electricity:Plant"),
    ("cooling_electricity_j", "Cooling:Electricity"),
    ("heating_electricity_j", "Heating:Electricity"),
    ("fans_electricity_j", "Fans:Electricity"),
    ("pumps_electricity_j", "Pumps:Electricity"),
    ("interior_lights_electricity_j", "InteriorLights:Electricity"),
    ("interior_equipment_electricity_j", "InteriorEquipment:Electricity"),
)


@dataclass(frozen=True, slots=True)
class SensorCatalog:
    """Which zones we read, and therefore which handles we need."""

    zone_names: tuple[str, ...]

    def variable_requests(self) -> tuple[tuple[str, str], ...]:
        """Every (variable_name, key) pair to request before the run starts."""
        zone_pairs = tuple(
            (variable, zone) for zone in self.zone_names for _, variable in ZONE_VARIABLES
        )
        site_pairs = tuple((variable, SITE_KEY) for _, variable in SITE_VARIABLES)
        return zone_pairs + site_pairs


class SensorReader:
    """Turns a live EnergyPlus state into an immutable SensorSnapshot."""

    def __init__(self, exchange, catalog: SensorCatalog) -> None:
        self._exchange = exchange
        self._catalog = catalog
        self._variable_handles: dict[tuple[str, str], int] = {}
        self._meter_handles: dict[str, int] = {}
        self._resolved = False

    @property
    def is_resolved(self) -> bool:
        return self._resolved

    @property
    def health(self) -> tuple[int, int, int, int]:
        """(variables resolved, requested, meters resolved, requested).

        Surfaced so the dashboard can show that every sensor the model was asked
        for is actually reporting, rather than asserting it in a slide.
        """
        variables = sum(1 for h in self._variable_handles.values() if h != INVALID_HANDLE)
        meters = sum(1 for h in self._meter_handles.values() if h != INVALID_HANDLE)
        return (variables, len(self._variable_handles), meters, len(self._meter_handles))

    def request_variables(self, state) -> None:
        """Tell EnergyPlus to produce our variables. Must precede run_energyplus."""
        for variable, key in self._catalog.variable_requests():
            self._exchange.request_variable(state, variable, key)
        logger.info(
            "Requested %d output variables for %d zones",
            len(self._catalog.variable_requests()),
            len(self._catalog.zone_names),
        )

    def resolve_handles(self, state) -> None:
        """Look up and cache every handle. Call once, on a fully-ready timestep."""
        for variable, key in self._catalog.variable_requests():
            self._variable_handles[(variable, key)] = self._exchange.get_variable_handle(
                state, variable, key
            )
        for _, meter in METERS:
            self._meter_handles[meter] = self._exchange.get_meter_handle(state, meter)

        self._resolved = True
        self._warn_about_missing_handles()

    def read(self, state) -> SensorSnapshot:
        """Capture the current timestep. Handles must already be resolved."""
        if not self._resolved:
            raise RuntimeError("resolve_handles must be called before read")

        return SensorSnapshot(
            clock=self._read_clock(state),
            zones=tuple(self._read_zone(state, name) for name in self._catalog.zone_names),
            site=self._read_site(state),
            energy=self._read_energy(state),
        )

    def _read_clock(self, state) -> SimulationClock:
        """Build the timestamp from the zone timestep index, not from minutes().

        exchange.minutes() reports the boundary of the HVAC *system* timestep,
        which EnergyPlus varies adaptively. During an annual run it yields values
        like 16, 23 and even 68 -- correct for the system loop, wrong as a label
        for a zone-timestep sample. The zone timestep index is exact by
        construction: step 1 of 4 is always :00, step 2 is always :15.
        """
        exchange = self._exchange
        steps_per_hour = exchange.num_time_steps_in_hour(state)
        step_number = exchange.zone_time_step_number(state)

        return SimulationClock(
            month=exchange.month(state),
            day=exchange.day_of_month(state),
            hour=exchange.hour(state),
            minute=(step_number - 1) * (60 // steps_per_hour),
            is_warmup=bool(exchange.warmup_flag(state)),
        )

    def _read_zone(self, state, zone_name: str) -> ZoneReading:
        values = {
            field: self._variable_value(state, variable, zone_name)
            for field, variable in ZONE_VARIABLES
        }
        return ZoneReading(name=zone_name, **values)

    def _read_site(self, state) -> SiteReading:
        return SiteReading(
            **{
                field: self._variable_value(state, variable, SITE_KEY)
                for field, variable in SITE_VARIABLES
            }
        )

    def _read_energy(self, state) -> EnergyReading:
        return EnergyReading(
            **{field: self._meter_value(state, meter) for field, meter in METERS}
        )

    def _variable_value(self, state, variable: str, key: str) -> float | None:
        handle = self._variable_handles.get((variable, key), INVALID_HANDLE)
        if handle == INVALID_HANDLE:
            return None
        return self._exchange.get_variable_value(state, handle)

    def _meter_value(self, state, meter: str) -> float | None:
        handle = self._meter_handles.get(meter, INVALID_HANDLE)
        if handle == INVALID_HANDLE:
            return None
        return self._exchange.get_meter_value(state, handle)

    def _warn_about_missing_handles(self) -> None:
        """A missing handle degrades one reading; it must never fail the run.

        Logged loudly because a silently absent sensor looks identical to a
        genuinely idle one on a dashboard.
        """
        missing_variables = [
            f"{variable} @ {key}"
            for (variable, key), handle in self._variable_handles.items()
            if handle == INVALID_HANDLE
        ]
        missing_meters = [
            meter for meter, handle in self._meter_handles.items() if handle == INVALID_HANDLE
        ]

        resolved = len(self._variable_handles) - len(missing_variables)
        logger.info(
            "Resolved %d/%d variables and %d/%d meters",
            resolved,
            len(self._variable_handles),
            len(self._meter_handles) - len(missing_meters),
            len(self._meter_handles),
        )
        for name in missing_variables + missing_meters:
            logger.warning("Sensor unavailable, will report None: %s", name)
