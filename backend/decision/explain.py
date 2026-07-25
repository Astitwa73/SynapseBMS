"""What a decision is trying to achieve, and what it is expected to do.

Both are derived deterministically from the action and the building state, not
produced by the language model. The model is good at judging which situation the
building is in; it is not a source of quantitative predictions, and asking it for
one would produce a confident number with nothing behind it.

Every figure here traces to a measurement in scripts/compare_policies.py or to
the comfort model, and each carries the basis it came from.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.control.commands import ControlAction
from backend.processing.carbon import GRID_CARBON_KG_PER_KWH, carbon_kg
from backend.processing.context import BuildingContext

# Cooling energy change per degree of setpoint, measured on 2 July:
# 36.2% less cooling for a 2.1C higher occupied setpoint.
COOLING_PCT_PER_DEGREE = 36.2 / 2.1

# PMV change per degree of air temperature at 0.5 clo / 1.1 met, read off the
# Fanger curve between 25C (-0.13) and 26C (+0.20).
PMV_PER_DEGREE = 0.33

# The setback fraction lighting drops to when the building is empty.
LIGHTING_SETBACK_FRACTION = 0.3

SETPOINT_STEP_C = 1.0


@dataclass(frozen=True, slots=True)
class ExpectedImpact:
    """Predicted consequences of a decision. Estimates, and labelled as such."""

    cooling_change_pct: float | None
    power_change_kw: float | None
    comfort_change_pmv: float | None
    carbon_change_kg_per_hour: float | None
    summary: str
    basis: str

    @property
    def is_neutral(self) -> bool:
        return not any(
            (self.cooling_change_pct, self.power_change_kw, self.comfort_change_pmv)
        )


NO_IMPACT = ExpectedImpact(
    cooling_change_pct=None,
    power_change_kw=None,
    comfort_change_pmv=None,
    carbon_change_kg_per_hour=None,
    summary="No change; the building continues on its current setpoints.",
    basis="Holding makes no change, so there is nothing to estimate.",
)

SETPOINT_BASIS = (
    f"Cooling energy sensitivity of {COOLING_PCT_PER_DEGREE:.1f}% per degree, measured "
    "in scripts/compare_policies.py on 2 July. Comfort from the Fanger curve at "
    f"{PMV_PER_DEGREE:.2f} PMV per degree. Carbon at "
    f"{GRID_CARBON_KG_PER_KWH:.2f} kg CO2e/kWh."
)


def expected_impact(action: ControlAction, context: BuildingContext) -> ExpectedImpact:
    """Estimate what an action will do, from the building's current load."""
    if action is ControlAction.RAISE_SETPOINT:
        return _setpoint_impact(context, degrees=SETPOINT_STEP_C)
    if action is ControlAction.LOWER_SETPOINT:
        return _setpoint_impact(context, degrees=-SETPOINT_STEP_C)
    if action is ControlAction.REDUCE_LIGHTING:
        return _lighting_impact(context)
    return NO_IMPACT


def _setpoint_impact(context: BuildingContext, degrees: float) -> ExpectedImpact:
    cooling_pct = -COOLING_PCT_PER_DEGREE * degrees
    cooling_kw = context.power.cooling_kw
    power_change = cooling_kw * cooling_pct / 100.0 if cooling_kw is not None else None
    comfort_change = PMV_PER_DEGREE * degrees

    direction = "warmer" if degrees > 0 else "cooler"
    return ExpectedImpact(
        cooling_change_pct=cooling_pct,
        power_change_kw=power_change,
        comfort_change_pmv=comfort_change,
        carbon_change_kg_per_hour=carbon_kg(power_change) if power_change is not None else None,
        summary=(
            f"About {abs(cooling_pct):.0f}% "
            f"{'less' if cooling_pct < 0 else 'more'} cooling energy, with zones "
            f"settling roughly {abs(degrees):.0f}C {direction} "
            f"({comfort_change:+.2f} PMV)."
        ),
        basis=SETPOINT_BASIS,
    )


def _lighting_impact(context: BuildingContext) -> ExpectedImpact:
    lighting_kw = context.power.lighting_kw
    power_change = (
        -lighting_kw * (1.0 - LIGHTING_SETBACK_FRACTION) if lighting_kw is not None else None
    )

    return ExpectedImpact(
        cooling_change_pct=None,
        power_change_kw=power_change,
        # Dimming an unoccupied space has no occupant to affect.
        comfort_change_pmv=0.0,
        carbon_change_kg_per_hour=carbon_kg(power_change) if power_change is not None else None,
        summary=(
            f"Lighting drops to {LIGHTING_SETBACK_FRACTION:.0%} of current output"
            + (f", about {abs(power_change):.1f} kW." if power_change is not None else ".")
        ),
        basis=(
            f"Lighting setback to {LIGHTING_SETBACK_FRACTION:.0%} applied to the "
            f"measured lighting load. Carbon at {GRID_CARBON_KG_PER_KWH:.2f} kg CO2e/kWh."
        ),
    )


def current_objective(action: ControlAction, context: BuildingContext) -> str:
    """A short statement of what the agent is optimising for right now.

    Read from the situation rather than the action alone: raising a setpoint in
    an empty building and raising it in an occupied comfortable one are the same
    action pursuing different goals, and the goal is what a viewer needs.
    """
    if not context.is_occupied:
        return "Minimise energy use while the building is unoccupied"

    if action is ControlAction.LOWER_SETPOINT:
        return "Restore occupant comfort in the warmest zone"
    if action is ControlAction.REDUCE_LIGHTING:
        return "Reduce lighting load without affecting occupants"

    if action is ControlAction.RAISE_SETPOINT:
        mean_pmv = context.mean_pmv
        if mean_pmv is not None and mean_pmv < -0.5:
            return "Recover comfort in an over-cooled building"
        return "Convert comfort margin into reduced cooling energy"

    return "Hold comfort and energy in balance"
