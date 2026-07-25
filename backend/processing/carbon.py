"""Carbon accounting from electricity use.

Deliberately a single fixed emission factor rather than a time-varying grid
signal. A real carbon-intensity curve would need a live grid data source, and
synthesising one would put a fabricated series on a dashboard next to measured
ones. The factor is displayed wherever a carbon figure appears so that the
number is never quoted without its assumption.

The consequence, stated plainly: with a constant factor, carbon is a linear
transform of energy and carries no information energy does not. It is reported
as a cumulative total, which is a useful executive figure, and deliberately not
as a separate trend line, which would be the power chart wearing a different
axis label.
"""

from __future__ import annotations

# US eGRID national average, all fuels. A site-specific factor belongs in
# configuration once a building has a known grid region.
GRID_CARBON_KG_PER_KWH = 0.40

GRID_CARBON_BASIS = (
    f"{GRID_CARBON_KG_PER_KWH:.2f} kg CO2e per kWh, US eGRID national average. "
    "A fixed factor: carbon here scales directly with electricity use."
)


def carbon_kg(energy_kwh: float | None) -> float | None:
    """Emissions for an amount of electricity, in kg CO2e."""
    if energy_kwh is None:
        return None
    return energy_kwh * GRID_CARBON_KG_PER_KWH
