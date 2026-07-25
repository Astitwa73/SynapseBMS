"""The decision-grade view of the building.

Raw sensors answer "what is the temperature"; a control decision needs "is
anyone uncomfortable, where, and what is it costing". This module is the seam
between those two questions, and it is deliberately the only thing a policy
sees: the rule engine and the LLM agent consume the same BuildingContext, so
they can be compared, swapped, or run side by side.

Everything here is derived from one SensorSnapshot and is immutable, which keeps
a policy from mutating shared state or reaching back into the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.processing.air_quality import (
    AirQualityAssumptions,
    AirQualityBand,
    air_quality_band,
    estimated_co2_ppm,
)
from backend.processing.comfort import (
    ComfortAssumptions,
    ComfortBand,
    comfort_band,
    predicted_mean_vote,
    predicted_percentage_dissatisfied,
)
from backend.simulation.state import EnergyReading, SensorSnapshot, SimulationClock, SiteReading

JOULES_PER_KWH = 3.6e6

# EnergyPlus meters report joules accumulated over the timestep, so average
# power depends on how long that timestep was.
SECONDS_PER_TIMESTEP_DEFAULT = 900.0


@dataclass(frozen=True, slots=True)
class ZoneContext:
    """One zone, with comfort and air quality resolved."""

    name: str
    air_temperature_c: float | None
    relative_humidity_pct: float | None
    occupant_count: float | None
    cooling_setpoint_c: float | None
    pmv: float | None
    ppd_pct: float | None
    comfort: ComfortBand | None
    co2_ppm: float | None
    air_quality: AirQualityBand | None

    @property
    def is_occupied(self) -> bool:
        return bool(self.occupant_count)

    @property
    def is_uncomfortable(self) -> bool:
        return self.comfort is not None and self.comfort != ComfortBand.COMFORTABLE


@dataclass(frozen=True, slots=True)
class BuildingContext:
    """What a policy is allowed to reason about."""

    clock: SimulationClock
    zones: tuple[ZoneContext, ...]
    site: SiteReading
    energy: EnergyReading
    sequence: int
    total_power_kw: float | None

    @property
    def total_occupancy(self) -> float:
        return sum(zone.occupant_count or 0.0 for zone in self.zones)

    @property
    def is_occupied(self) -> bool:
        return self.total_occupancy > 0

    @property
    def occupied_zones(self) -> tuple[ZoneContext, ...]:
        return tuple(zone for zone in self.zones if zone.is_occupied)

    @property
    def mean_pmv(self) -> float | None:
        """Averaged over occupied zones only -- an empty room's comfort is nobody's."""
        votes = [zone.pmv for zone in self.occupied_zones if zone.pmv is not None]
        if not votes:
            votes = [zone.pmv for zone in self.zones if zone.pmv is not None]
        return sum(votes) / len(votes) if votes else None

    @property
    def worst_zone(self) -> ZoneContext | None:
        """The occupied zone furthest from neutral: where a complaint comes from."""
        candidates = [
            zone for zone in (self.occupied_zones or self.zones) if zone.pmv is not None
        ]
        return max(candidates, key=lambda zone: abs(zone.pmv), default=None)

    @property
    def mean_cooling_setpoint_c(self) -> float | None:
        setpoints = [z.cooling_setpoint_c for z in self.zones if z.cooling_setpoint_c]
        return sum(setpoints) / len(setpoints) if setpoints else None

    @property
    def peak_co2_ppm(self) -> float | None:
        readings = [zone.co2_ppm for zone in self.zones if zone.co2_ppm is not None]
        return max(readings) if readings else None


def build_context(
    snapshot: SensorSnapshot,
    comfort_assumptions: ComfortAssumptions | None = None,
    air_quality_assumptions: AirQualityAssumptions | None = None,
    seconds_per_timestep: float = SECONDS_PER_TIMESTEP_DEFAULT,
) -> BuildingContext:
    """Derive comfort and air quality for every zone in a snapshot."""
    zones = tuple(
        _build_zone(zone, comfort_assumptions, air_quality_assumptions)
        for zone in snapshot.zones
    )

    total_j = snapshot.energy.total_electricity_j
    power_kw = (
        (total_j / seconds_per_timestep) / 1000.0
        if total_j is not None and seconds_per_timestep > 0
        else None
    )

    return BuildingContext(
        clock=snapshot.clock,
        zones=zones,
        site=snapshot.site,
        energy=snapshot.energy,
        sequence=snapshot.sequence,
        total_power_kw=power_kw,
    )


def _build_zone(zone, comfort_assumptions, air_quality_assumptions) -> ZoneContext:
    pmv = ppd = None
    band = None
    if zone.air_temperature_c is not None and zone.relative_humidity_pct is not None:
        pmv = predicted_mean_vote(
            zone.air_temperature_c, zone.relative_humidity_pct, comfort_assumptions
        )
        ppd = predicted_percentage_dissatisfied(pmv)
        band = comfort_band(pmv)

    co2 = estimated_co2_ppm(
        zone.occupant_count, zone.ventilation_mass_flow_kg_s, air_quality_assumptions
    )

    return ZoneContext(
        name=zone.name,
        air_temperature_c=zone.air_temperature_c,
        relative_humidity_pct=zone.relative_humidity_pct,
        occupant_count=zone.occupant_count,
        cooling_setpoint_c=zone.cooling_setpoint_c,
        pmv=pmv,
        ppd_pct=ppd,
        comfort=band,
        co2_ppm=co2,
        air_quality=air_quality_band(co2),
    )
