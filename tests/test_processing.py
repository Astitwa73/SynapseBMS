import pytest

from backend.processing.air_quality import (
    MAX_REPORTED_CO2_PPM,
    OUTDOOR_CO2_PPM,
    AirQualityBand,
    air_quality_band,
    estimated_co2_ppm,
)
from backend.processing.comfort import (
    PMV_REPORTING_LIMIT,
    ComfortAssumptions,
    ComfortBand,
    comfort_band,
    predicted_mean_vote,
    predicted_percentage_dissatisfied,
)
from backend.processing.context import build_context
from backend.simulation.state import (
    EnergyReading,
    SensorSnapshot,
    SimulationClock,
    SiteReading,
    ZoneReading,
)

SUMMER = ComfortAssumptions()


# --- PMV: validated by properties, not by numbers I might misremember -------


def test_pmv_rises_monotonically_with_temperature():
    votes = [predicted_mean_vote(t, 50.0, SUMMER) for t in range(16, 34)]
    assert votes == sorted(votes)
    assert votes[0] < 0 < votes[-1]


def test_pmv_has_a_neutral_point_at_a_plausible_office_temperature():
    """Locate PMV == 0 numerically and check it lands where ASHRAE 55 expects."""
    neutral = min(
        (t / 10 for t in range(180, 320)),
        key=lambda t: abs(predicted_mean_vote(t, 50.0, SUMMER)),
    )
    assert 23.0 <= neutral <= 27.0, f"neutral temperature {neutral}C is implausible"


def test_pmv_rises_with_humidity_at_fixed_temperature():
    dry = predicted_mean_vote(27.0, 20.0, SUMMER)
    humid = predicted_mean_vote(27.0, 80.0, SUMMER)
    assert humid > dry, "humidity must make a warm room feel warmer"


def test_heavier_clothing_feels_warmer():
    light = predicted_mean_vote(24.0, 50.0, ComfortAssumptions(clothing_insulation_clo=0.5))
    heavy = predicted_mean_vote(24.0, 50.0, ComfortAssumptions(clothing_insulation_clo=1.2))
    assert heavy > light


def test_air_movement_cools():
    still = predicted_mean_vote(28.0, 50.0, ComfortAssumptions(air_velocity_m_s=0.1))
    breezy = predicted_mean_vote(28.0, 50.0, ComfortAssumptions(air_velocity_m_s=0.8))
    assert breezy < still


def test_pmv_is_clipped_to_the_models_validated_range():
    assert predicted_mean_vote(60.0, 90.0, SUMMER) == PMV_REPORTING_LIMIT
    assert predicted_mean_vote(-30.0, 10.0, SUMMER) == -PMV_REPORTING_LIMIT


def test_pmv_converges_across_the_whole_plausible_range():
    """The clothing-temperature solve is iterative; it must not diverge."""
    for temperature in range(10, 45):
        for humidity in (10, 50, 90):
            value = predicted_mean_vote(float(temperature), float(humidity), SUMMER)
            assert -PMV_REPORTING_LIMIT <= value <= PMV_REPORTING_LIMIT


# --- PPD -------------------------------------------------------------------


def test_ppd_bottoms_out_at_five_percent():
    """Even at perfect neutrality some people are dissatisfied, by construction."""
    assert predicted_percentage_dissatisfied(0.0) == pytest.approx(5.0)


def test_ppd_is_symmetric_and_increases_away_from_neutral():
    assert predicted_percentage_dissatisfied(-1.0) == pytest.approx(
        predicted_percentage_dissatisfied(1.0)
    )
    assert predicted_percentage_dissatisfied(2.0) > predicted_percentage_dissatisfied(1.0)


@pytest.mark.parametrize(
    "pmv,expected",
    [
        (-2.0, ComfortBand.COLD),
        (-1.0, ComfortBand.COOL),
        (0.0, ComfortBand.COMFORTABLE),
        (0.5, ComfortBand.COMFORTABLE),
        (1.0, ComfortBand.WARM),
        (2.0, ComfortBand.HOT),
    ],
)
def test_comfort_bands(pmv, expected):
    assert comfort_band(pmv) == expected


# --- CO2 -------------------------------------------------------------------


def test_empty_zone_sits_at_outdoor_concentration():
    assert estimated_co2_ppm(0, 0.5) == OUTDOOR_CO2_PPM


def test_co2_rises_with_occupancy_and_falls_with_ventilation():
    few = estimated_co2_ppm(5, 0.5)
    many = estimated_co2_ppm(20, 0.5)
    ventilated = estimated_co2_ppm(20, 2.0)

    assert many > few > OUTDOOR_CO2_PPM
    assert ventilated < many


def test_zero_ventilation_with_occupants_is_capped_not_infinite():
    assert estimated_co2_ppm(10, 0.0) == MAX_REPORTED_CO2_PPM


def test_missing_inputs_yield_no_estimate():
    assert estimated_co2_ppm(None, 0.5) is None
    assert estimated_co2_ppm(10, None) is None


def test_co2_matches_the_mass_balance_by_hand():
    """10 people at 5e-6 m3/s each, diluted by 0.5 kg/s of air at 1.2 kg/m3."""
    expected = OUTDOOR_CO2_PPM + (10 * 5.0e-6) / (0.5 / 1.2) * 1e6
    assert estimated_co2_ppm(10, 0.5) == pytest.approx(expected)


@pytest.mark.parametrize(
    "ppm,expected",
    [(500, AirQualityBand.GOOD), (900, AirQualityBand.MODERATE), (1500, AirQualityBand.POOR)],
)
def test_air_quality_bands(ppm, expected):
    assert air_quality_band(ppm) == expected


# --- context ---------------------------------------------------------------


def make_snapshot(zones):
    return SensorSnapshot(
        clock=SimulationClock(month=7, day=2, hour=14, minute=0),
        zones=zones,
        site=SiteReading(outdoor_air_temperature_c=31.0),
        energy=EnergyReading(
            building_electricity_j=9_900_000.0,
            hvac_electricity_j=568_660.0,
            plant_electricity_j=3_058_228.0,
        ),
        sequence=7,
    )


def test_context_derives_comfort_and_air_quality_per_zone():
    snapshot = make_snapshot((
        ZoneReading(
            name="SPACE1-1", air_temperature_c=27.5, relative_humidity_pct=55.0,
            occupant_count=10, ventilation_mass_flow_kg_s=0.4, cooling_setpoint_c=24.0,
        ),
    ))
    context = build_context(snapshot)
    zone = context.zones[0]

    assert zone.pmv is not None and zone.pmv > 0
    assert zone.comfort in (ComfortBand.WARM, ComfortBand.HOT)
    assert zone.co2_ppm > OUTDOOR_CO2_PPM
    assert zone.is_occupied


def test_mean_pmv_ignores_empty_zones():
    """An empty room's comfort is nobody's comfort."""
    snapshot = make_snapshot((
        ZoneReading(name="OCCUPIED", air_temperature_c=28.0, relative_humidity_pct=50.0,
                    occupant_count=10),
        ZoneReading(name="EMPTY", air_temperature_c=19.0, relative_humidity_pct=50.0,
                    occupant_count=0),
    ))
    context = build_context(snapshot)

    occupied_only = context.zones[0].pmv
    assert context.mean_pmv == pytest.approx(occupied_only)
    assert context.worst_zone.name == "OCCUPIED"


def test_mean_pmv_falls_back_to_all_zones_when_building_is_empty():
    snapshot = make_snapshot((
        ZoneReading(name="A", air_temperature_c=30.0, relative_humidity_pct=50.0,
                    occupant_count=0),
    ))
    context = build_context(snapshot)
    assert context.mean_pmv is not None
    assert not context.is_occupied


def test_total_power_is_derived_from_timestep_length():
    snapshot = make_snapshot((ZoneReading(name="A"),))
    context = build_context(snapshot, seconds_per_timestep=900.0)

    expected_kw = (9_900_000.0 + 568_660.0 + 3_058_228.0) / 900.0 / 1000.0
    assert context.total_power_kw == pytest.approx(expected_kw)


def test_context_tolerates_missing_sensors():
    context = build_context(make_snapshot((ZoneReading(name="DARK"),)))
    zone = context.zones[0]

    assert zone.pmv is None and zone.comfort is None and zone.co2_ppm is None
    assert context.mean_pmv is None
    assert context.worst_zone is None
