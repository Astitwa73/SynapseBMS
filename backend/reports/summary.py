"""Period reports: what the building did, and what the agent did about it.

Everything here is computed from recorded history rather than estimated, with
one exception that is labelled as an estimate and carries its own basis. We
cannot know what the building would have consumed without the agent while the
agent is running, so the report does not pretend to: it states the measured
benchmark separately from the live figures.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from backend.decision.loop import DecisionRecord
from backend.processing.comfort import ComfortBand
from backend.processing.air_quality import AirQualityBand
from backend.processing.context import BuildingContext

JOULES_PER_KWH = 3.6e6

# The occupied cooling setpoint the model schedules with no agent running,
# measured from a baseline run of 5ZoneAirCooled.
BASELINE_SETPOINT_C = 23.90

# Cooling energy sensitivity to setpoint, from scripts/compare_policies.py:
# 36.2% less cooling for a 2.1C higher occupied setpoint on 2 July.
COOLING_SENSITIVITY_PCT_PER_C = 36.2 / 2.1

# Beyond the range we actually measured, a linear extrapolation stops meaning
# anything, so the estimate is capped rather than allowed to grow indefinitely.
MAX_CREDIBLE_SAVING_PCT = 45.0


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    from_label: str
    to_label: str
    samples: int
    simulated_hours: float


@dataclass(frozen=True, slots=True)
class EnergyReport:
    total_kwh: float
    cooling_kwh: float
    heating_kwh: float
    fans_kwh: float
    pumps_kwh: float
    lighting_kwh: float
    equipment_kwh: float
    peak_demand_kw: float | None
    mean_demand_kw: float | None


@dataclass(frozen=True, slots=True)
class ComfortReport:
    mean_occupied_pmv: float | None
    comfortable_pct: float | None
    occupied_samples: int
    worst_zone: str | None
    worst_zone_pmv: float | None
    peak_co2_ppm: float | None
    poor_air_quality_pct: float | None


@dataclass(frozen=True, slots=True)
class AgentReport:
    policy: str
    decisions: int
    actions: dict[str, int] = field(default_factory=dict)
    safety_adjustments: int = 0
    fallbacks: int = 0


@dataclass(frozen=True, slots=True)
class SavingsEstimate:
    """Explicitly an estimate. `basis` travels with it so it cannot be quoted bare."""

    baseline_setpoint_c: float
    mean_setpoint_c: float | None
    setpoint_offset_c: float | None
    estimated_cooling_saving_pct: float | None
    basis: str


@dataclass(frozen=True, slots=True)
class BuildingReport:
    period: ReportPeriod
    energy: EnergyReport
    comfort: ComfortReport
    agent: AgentReport
    savings: SavingsEstimate
    headline: str


def build_report(
    contexts: tuple[BuildingContext, ...],
    decisions: tuple[DecisionRecord, ...],
    policy_name: str,
    fallbacks: int = 0,
    seconds_per_timestep: float = 900.0,
) -> BuildingReport:
    """Summarise a run from its recorded history."""
    if not contexts:
        raise ValueError("Cannot report on an empty period")

    period = _build_period(contexts, seconds_per_timestep)
    energy = _build_energy(contexts)
    comfort = _build_comfort(contexts)
    agent = _build_agent(decisions, policy_name, fallbacks)
    savings = _build_savings(comfort, contexts)

    return BuildingReport(
        period=period,
        energy=energy,
        comfort=comfort,
        agent=agent,
        savings=savings,
        headline=_build_headline(period, energy, comfort, agent),
    )


def _build_period(contexts, seconds_per_timestep) -> ReportPeriod:
    return ReportPeriod(
        from_label=contexts[0].clock.label,
        to_label=contexts[-1].clock.label,
        samples=len(contexts),
        simulated_hours=len(contexts) * seconds_per_timestep / 3600.0,
    )


def _build_energy(contexts) -> EnergyReport:
    def total(attribute: str) -> float:
        return sum(getattr(c.energy, attribute) or 0.0 for c in contexts) / JOULES_PER_KWH

    demands = [c.total_power_kw for c in contexts if c.total_power_kw is not None]
    return EnergyReport(
        # total_electricity_j is a derived property, but getattr reaches it the
        # same way, so the end-use helper works unchanged.
        total_kwh=total("total_electricity_j"),
        cooling_kwh=total("cooling_electricity_j"),
        heating_kwh=total("heating_electricity_j"),
        fans_kwh=total("fans_electricity_j"),
        pumps_kwh=total("pumps_electricity_j"),
        lighting_kwh=total("interior_lights_electricity_j"),
        equipment_kwh=total("interior_equipment_electricity_j"),
        peak_demand_kw=max(demands) if demands else None,
        mean_demand_kw=sum(demands) / len(demands) if demands else None,
    )


def _build_comfort(contexts) -> ComfortReport:
    occupied = [
        zone for context in contexts for zone in context.occupied_zones if zone.pmv is not None
    ]
    air_samples = [
        zone.air_quality for context in contexts for zone in context.zones if zone.air_quality
    ]
    co2 = [c.peak_co2_ppm for c in contexts if c.peak_co2_ppm is not None]

    worst = max(occupied, key=lambda zone: abs(zone.pmv), default=None)
    comfortable = sum(1 for zone in occupied if zone.comfort is ComfortBand.COMFORTABLE)
    poor = sum(1 for band in air_samples if band is AirQualityBand.POOR)

    return ComfortReport(
        mean_occupied_pmv=sum(z.pmv for z in occupied) / len(occupied) if occupied else None,
        comfortable_pct=comfortable / len(occupied) * 100 if occupied else None,
        occupied_samples=len(occupied),
        worst_zone=worst.name if worst else None,
        worst_zone_pmv=worst.pmv if worst else None,
        peak_co2_ppm=max(co2) if co2 else None,
        poor_air_quality_pct=poor / len(air_samples) * 100 if air_samples else None,
    )


def _build_agent(decisions, policy_name, fallbacks) -> AgentReport:
    return AgentReport(
        policy=policy_name,
        decisions=len(decisions),
        actions=dict(Counter(r.decision.action.value for r in decisions)),
        safety_adjustments=sum(1 for r in decisions if r.was_adjusted),
        fallbacks=fallbacks,
    )


def _build_savings(comfort: ComfortReport, contexts) -> SavingsEstimate:
    setpoints = [
        c.mean_cooling_setpoint_c
        for c in contexts
        if c.is_occupied and c.mean_cooling_setpoint_c is not None
    ]
    mean_setpoint = sum(setpoints) / len(setpoints) if setpoints else None

    offset = estimate = None
    if mean_setpoint is not None:
        offset = mean_setpoint - BASELINE_SETPOINT_C
        estimate = min(max(offset * COOLING_SENSITIVITY_PCT_PER_C, 0.0), MAX_CREDIBLE_SAVING_PCT)

    return SavingsEstimate(
        baseline_setpoint_c=BASELINE_SETPOINT_C,
        mean_setpoint_c=mean_setpoint,
        setpoint_offset_c=offset,
        estimated_cooling_saving_pct=estimate,
        basis=(
            f"Estimated from setpoint offset against the unmanaged baseline of "
            f"{BASELINE_SETPOINT_C:.1f}C, at a measured sensitivity of "
            f"{COOLING_SENSITIVITY_PCT_PER_C:.1f}% cooling energy per degree "
            f"(scripts/compare_policies.py, 2 July). Capped at "
            f"{MAX_CREDIBLE_SAVING_PCT:.0f}% because linear extrapolation beyond "
            "the measured range is not supportable."
        ),
    )


def _build_headline(period, energy, comfort, agent) -> str:
    comfort_text = (
        f"{comfort.comfortable_pct:.0f}% of occupied readings within the comfort band"
        if comfort.comfortable_pct is not None
        else "no occupied readings"
    )
    return (
        f"Over {period.simulated_hours:.1f} simulated hours the building used "
        f"{energy.total_kwh:.1f} kWh, of which {energy.cooling_kwh:.1f} kWh was cooling, "
        f"with {comfort_text}. The {agent.policy} agent took {agent.decisions} decisions."
    )


def render_markdown(report: BuildingReport) -> str:
    """Human-readable form, for the MCP tool and the dashboard's export."""
    comfort = report.comfort
    savings = report.savings

    lines = [
        "# Building Performance Report",
        "",
        f"**Period:** {report.period.from_label} to {report.period.to_label} "
        f"({report.period.simulated_hours:.1f} simulated hours, "
        f"{report.period.samples} samples)",
        "",
        report.headline,
        "",
        "## Energy",
        "",
        "| End use | kWh |",
        "| --- | ---: |",
        f"| Cooling | {report.energy.cooling_kwh:.2f} |",
        f"| Heating | {report.energy.heating_kwh:.2f} |",
        f"| Fans | {report.energy.fans_kwh:.2f} |",
        f"| Pumps | {report.energy.pumps_kwh:.2f} |",
        f"| Lighting | {report.energy.lighting_kwh:.2f} |",
        f"| Equipment | {report.energy.equipment_kwh:.2f} |",
        f"| **Total** | **{report.energy.total_kwh:.2f}** |",
        "",
        f"Peak demand {_number(report.energy.peak_demand_kw)} kW, "
        f"mean {_number(report.energy.mean_demand_kw)} kW.",
        "",
        "## Comfort and air quality",
        "",
        f"- Mean occupied PMV: {_number(comfort.mean_occupied_pmv, '+.2f')}",
        f"- Within comfort band: {_number(comfort.comfortable_pct, '.1f')}% "
        f"of {comfort.occupied_samples} occupied zone readings",
        f"- Least comfortable zone: {comfort.worst_zone or 'n/a'} "
        f"at PMV {_number(comfort.worst_zone_pmv, '+.2f')}",
        f"- Peak CO2: {_number(comfort.peak_co2_ppm, '.0f')} ppm",
        f"- Air quality poor: {_number(comfort.poor_air_quality_pct, '.1f')}% of readings",
        "",
        "## Agent activity",
        "",
        f"- Policy: {report.agent.policy}",
        f"- Decisions: {report.agent.decisions}",
        f"- Actions: {report.agent.actions or 'none'}",
        f"- Commands adjusted by the safety layer: {report.agent.safety_adjustments}",
        f"- Policy fallbacks: {report.agent.fallbacks}",
        "",
        "## Estimated savings",
        "",
        f"- Baseline setpoint: {savings.baseline_setpoint_c:.1f} C",
        f"- Mean occupied setpoint: {_number(savings.mean_setpoint_c)} C "
        f"({_number(savings.setpoint_offset_c, '+.1f')} C)",
        f"- Estimated cooling reduction: "
        f"{_number(savings.estimated_cooling_saving_pct, '.1f')}%",
        "",
        f"> {savings.basis}",
    ]
    return "\n".join(lines)


def _number(value: float | None, spec: str = ".2f") -> str:
    return format(value, spec) if value is not None else "n/a"
