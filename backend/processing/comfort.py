"""Thermal comfort as Predicted Mean Vote, per ISO 7730 / ASHRAE 55.

PMV places thermal sensation on a -3 (cold) to +3 (hot) scale, where 0 is
neutral and +/-0.5 is the usual comfortable band. It exists because temperature
alone does not describe comfort: 24C at 30% humidity in still air and 24C at 70%
humidity feel materially different, and an agent optimising on temperature alone
cannot see that.

The model takes six inputs. This building measures two of them. The remaining
four are assumptions, and they live in ComfortAssumptions rather than as
literals inside the calculation so that they can be challenged -- an assumption
you cannot find is an assumption nobody will check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

# Above this magnitude the Fanger model is outside its validated range; reporting
# a precise-looking number there would overstate what it can tell us.
PMV_REPORTING_LIMIT = 3.0

_MAX_ITERATIONS = 150
_CONVERGENCE_TOLERANCE = 0.00015


class ComfortBand(str, Enum):
    """Human-readable PMV bands, for the dashboard and the agent's prompt."""

    COLD = "cold"
    COOL = "cool"
    COMFORTABLE = "comfortable"
    WARM = "warm"
    HOT = "hot"


@dataclass(frozen=True, slots=True)
class ComfortAssumptions:
    """The four PMV inputs this building does not measure.

    mean_radiant_offset_c is the weakest of them: PMV wants the mean radiant
    temperature of the surrounding surfaces, and we assume it equals air
    temperature. That holds reasonably for interior zones away from glazing and
    would be replaced by a measured value in a real deployment.
    """

    metabolic_rate_met: float = 1.1  # seated office work
    clothing_insulation_clo: float = 0.5  # summer dress
    air_velocity_m_s: float = 0.1  # still air
    mean_radiant_offset_c: float = 0.0


def predicted_mean_vote(
    air_temperature_c: float,
    relative_humidity_pct: float,
    assumptions: ComfortAssumptions | None = None,
) -> float:
    """Return PMV for a zone, clipped to the model's validated range.

    Implements the iterative Fanger formulation: solve for clothing surface
    temperature, then sum the six heat-loss terms that make up the body's
    thermal load.
    """
    settings = assumptions or ComfortAssumptions()

    air_temp = air_temperature_c
    radiant_temp = air_temp + settings.mean_radiant_offset_c
    velocity = settings.air_velocity_m_s

    vapour_pressure = relative_humidity_pct * 10 * math.exp(
        16.6536 - 4030.183 / (air_temp + 235)
    )
    clothing_resistance = 0.155 * settings.clothing_insulation_clo
    metabolic_w = settings.metabolic_rate_met * 58.15

    clothing_area_factor = (
        1 + 1.29 * clothing_resistance
        if clothing_resistance <= 0.078
        else 1.05 + 0.645 * clothing_resistance
    )

    forced_convection = 12.1 * math.sqrt(velocity)
    air_temp_k = air_temp + 273
    radiant_temp_k = radiant_temp + 273

    clothing_temp_guess = air_temp_k + (35.5 - air_temp) / (3.5 * clothing_resistance + 0.1)
    p1 = clothing_resistance * clothing_area_factor
    p2 = p1 * 3.96
    p3 = p1 * 100
    p4 = p1 * air_temp_k
    p5 = 308.7 - 0.028 * metabolic_w + p2 * (radiant_temp_k / 100) ** 4

    upper = clothing_temp_guess / 100
    lower = clothing_temp_guess / 50
    convection = forced_convection

    for _ in range(_MAX_ITERATIONS):
        if abs(upper - lower) <= _CONVERGENCE_TOLERANCE:
            break
        lower = (lower + upper) / 2
        natural_convection = 2.38 * abs(100.0 * lower - air_temp_k) ** 0.25
        convection = max(forced_convection, natural_convection)
        upper = (p5 + p4 * convection - p2 * lower**4) / (100 + p3 * convection)

    clothing_temp_c = 100 * upper - 273

    skin_diffusion = 3.05 * 0.001 * (5733 - 6.99 * metabolic_w - vapour_pressure)
    sweat_loss = 0.42 * (metabolic_w - 58.15) if metabolic_w > 58.15 else 0.0
    latent_respiration = 1.7 * 0.00001 * metabolic_w * (5867 - vapour_pressure)
    dry_respiration = 0.0014 * metabolic_w * (34 - air_temp)
    radiation_loss = 3.96 * clothing_area_factor * (
        upper**4 - (radiant_temp_k / 100) ** 4
    )
    convection_loss = clothing_area_factor * convection * (clothing_temp_c - air_temp)

    thermal_sensitivity = 0.303 * math.exp(-0.036 * metabolic_w) + 0.028
    vote = thermal_sensitivity * (
        metabolic_w
        - skin_diffusion
        - sweat_loss
        - latent_respiration
        - dry_respiration
        - radiation_loss
        - convection_loss
    )

    return max(-PMV_REPORTING_LIMIT, min(PMV_REPORTING_LIMIT, vote))


def predicted_percentage_dissatisfied(pmv: float) -> float:
    """Share of occupants expected to complain, as a percentage.

    Bottoms out at 5% by construction: even at perfect neutrality some fraction
    of people are dissatisfied, which is why "PPD of zero" is not a target.
    """
    return 100.0 - 95.0 * math.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)


def comfort_band(pmv: float) -> ComfortBand:
    if pmv < -1.5:
        return ComfortBand.COLD
    if pmv < -0.5:
        return ComfortBand.COOL
    if pmv <= 0.5:
        return ComfortBand.COMFORTABLE
    if pmv <= 1.5:
        return ComfortBand.WARM
    return ComfortBand.HOT
