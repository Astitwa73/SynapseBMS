import pytest

from backend.control.commands import ControlAction
from backend.decision.explain import (
    COOLING_PCT_PER_DEGREE,
    NO_IMPACT,
    current_objective,
    expected_impact,
)
from backend.processing.carbon import GRID_CARBON_KG_PER_KWH, carbon_kg
from backend.processing.context import build_context
from backend.simulation.state import (
    EnergyReading,
    SensorSnapshot,
    SimulationClock,
    SiteReading,
    ZoneReading,
)


def context(temperature=26.0, occupants=10.0, setpoint=26.0):
    return build_context(
        SensorSnapshot(
            clock=SimulationClock(month=7, day=2, hour=14, minute=0),
            zones=(
                ZoneReading(
                    name="SPACE1-1",
                    air_temperature_c=temperature,
                    relative_humidity_pct=45.0,
                    occupant_count=occupants,
                    cooling_setpoint_c=setpoint,
                    ventilation_mass_flow_kg_s=0.4,
                ),
            ),
            site=SiteReading(outdoor_air_temperature_c=29.0),
            energy=EnergyReading(
                building_electricity_j=9.9e6,
                plant_electricity_j=3.0e6,
                cooling_electricity_j=2.8e6,
                interior_lights_electricity_j=6.7e6,
            ),
        )
    )


# --- carbon ----------------------------------------------------------------


def test_carbon_scales_linearly_with_energy():
    assert carbon_kg(10.0) == pytest.approx(10.0 * GRID_CARBON_KG_PER_KWH)
    assert carbon_kg(None) is None


# --- expected impact -------------------------------------------------------


def test_raising_the_setpoint_predicts_less_cooling_and_a_warmer_building():
    impact = expected_impact(ControlAction.RAISE_SETPOINT, context())

    assert impact.cooling_change_pct == pytest.approx(-COOLING_PCT_PER_DEGREE)
    assert impact.power_change_kw < 0, "less cooling means less power"
    assert impact.comfort_change_pmv > 0, "warmer means PMV rises"
    assert impact.carbon_change_kg_per_hour < 0


def test_lowering_the_setpoint_is_the_exact_inverse():
    up = expected_impact(ControlAction.RAISE_SETPOINT, context())
    down = expected_impact(ControlAction.LOWER_SETPOINT, context())

    assert down.cooling_change_pct == pytest.approx(-up.cooling_change_pct)
    assert down.comfort_change_pmv == pytest.approx(-up.comfort_change_pmv)


def test_impact_is_scaled_by_the_buildings_actual_load():
    """A prediction of kW saved must come from the load now, not a constant."""
    busy = expected_impact(ControlAction.RAISE_SETPOINT, context())
    idle_context = context()
    idle = expected_impact(ControlAction.RAISE_SETPOINT, idle_context)

    assert busy.power_change_kw == pytest.approx(
        idle_context.power.cooling_kw * busy.cooling_change_pct / 100.0
    )
    assert idle.power_change_kw == busy.power_change_kw


def test_dimming_predicts_a_lighting_reduction_and_no_comfort_cost():
    impact = expected_impact(ControlAction.REDUCE_LIGHTING, context(occupants=0))

    assert impact.power_change_kw < 0
    assert impact.comfort_change_pmv == 0.0
    assert "Lighting" in impact.summary


def test_holding_predicts_nothing_rather_than_zero():
    assert expected_impact(ControlAction.HOLD, context()) is NO_IMPACT
    assert NO_IMPACT.is_neutral


def test_every_impact_carries_the_basis_it_was_derived_from():
    """A prediction quoted without its provenance is the one that gets attacked."""
    for action in ControlAction:
        impact = expected_impact(action, context())
        assert impact.basis.strip()
        assert impact.summary.strip()


def test_setpoint_basis_cites_the_measurement_not_an_assumption():
    impact = expected_impact(ControlAction.RAISE_SETPOINT, context())
    assert "compare_policies" in impact.basis
    assert "Fanger" in impact.basis


def test_impact_survives_missing_power_readings():
    empty = build_context(
        SensorSnapshot(
            clock=SimulationClock(month=7, day=2, hour=3, minute=0),
            zones=(ZoneReading(name="DARK"),),
            site=SiteReading(),
            energy=EnergyReading(),
        )
    )
    impact = expected_impact(ControlAction.RAISE_SETPOINT, empty)

    assert impact.power_change_kw is None
    assert impact.cooling_change_pct is not None, "the percentage is load-independent"


# --- objective -------------------------------------------------------------


def test_an_empty_building_is_always_about_energy():
    for action in ControlAction:
        assert "unoccupied" in current_objective(action, context(occupants=0))


def test_the_same_action_serves_different_goals_by_situation():
    """Raising a setpoint when cold recovers comfort; when comfortable it saves energy."""
    overcooled = current_objective(ControlAction.RAISE_SETPOINT, context(temperature=19.0))
    comfortable = current_objective(ControlAction.RAISE_SETPOINT, context(temperature=25.5))

    assert "over-cooled" in overcooled
    assert "energy" in comfortable
    assert overcooled != comfortable


def test_objectives_are_written_for_a_reader_not_a_log():
    for action in ControlAction:
        for occupants in (0, 20):
            objective = current_objective(action, context(occupants=occupants))
            assert objective[0].isupper()
            assert 20 < len(objective) < 90
