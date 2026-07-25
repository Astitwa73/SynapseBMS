"""Estimated zone CO2 from occupancy and ventilation.

This model does not simulate contaminants, so CO2 is derived rather than read.
That is also the normal situation in a real building: CO2 sensors are the
exception, and ventilation control is routinely driven by an occupancy-based
estimate of exactly this form.

Steady-state mass balance: occupants generate CO2, outdoor air dilutes it.

    C_zone = C_outdoor + (N * G) / Q

The steady-state assumption is the limitation worth naming -- it gives the
equilibrium concentration for the current occupancy and airflow, so it will not
show the gradual ramp as a room fills. For supervisory decisions made on an
hourly cadence that is the right level of detail.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Outdoor background concentration, ppm. Rises about 2.5 ppm a year.
OUTDOOR_CO2_PPM = 425.0

# CO2 generated per sedentary adult, m3/s. ASHRAE 62.1 gives roughly
# 0.005 L/s per person at 1.2 met.
CO2_PER_PERSON_M3_S = 5.0e-6

AIR_DENSITY_KG_M3 = 1.2

# Unventilated occupied spaces would trend towards concentrations the
# steady-state form reports as unbounded. Cap at a value that is unambiguously
# "ventilation has failed" rather than reporting a physically silly number.
MAX_REPORTED_CO2_PPM = 5000.0


class AirQualityBand(str, Enum):
    GOOD = "good"
    MODERATE = "moderate"
    POOR = "poor"


@dataclass(frozen=True, slots=True)
class AirQualityAssumptions:
    outdoor_co2_ppm: float = OUTDOOR_CO2_PPM
    co2_per_person_m3_s: float = CO2_PER_PERSON_M3_S
    air_density_kg_m3: float = AIR_DENSITY_KG_M3


def estimated_co2_ppm(
    occupant_count: float | None,
    ventilation_mass_flow_kg_s: float | None,
    assumptions: AirQualityAssumptions | None = None,
) -> float | None:
    """Estimate zone CO2. Returns None when the inputs cannot support an estimate."""
    settings = assumptions or AirQualityAssumptions()

    if occupant_count is None or ventilation_mass_flow_kg_s is None:
        return None

    if occupant_count <= 0:
        return settings.outdoor_co2_ppm

    airflow_m3_s = ventilation_mass_flow_kg_s / settings.air_density_kg_m3
    if airflow_m3_s <= 0:
        return MAX_REPORTED_CO2_PPM

    generation_m3_s = occupant_count * settings.co2_per_person_m3_s
    rise_ppm = (generation_m3_s / airflow_m3_s) * 1e6

    return min(settings.outdoor_co2_ppm + rise_ppm, MAX_REPORTED_CO2_PPM)


def air_quality_band(co2_ppm: float | None) -> AirQualityBand | None:
    """Classify against the thresholds commonly used for demand-controlled ventilation."""
    if co2_ppm is None:
        return None
    if co2_ppm < 800:
        return AirQualityBand.GOOD
    if co2_ppm < 1100:
        return AirQualityBand.MODERATE
    return AirQualityBand.POOR
