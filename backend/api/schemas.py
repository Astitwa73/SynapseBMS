"""The wire format.

Written out explicitly rather than serialising the domain objects. Auto-mapping
would tie the public contract to internal structure, so every refactor would
become a silent breaking change for the dashboard. These few extra lines make
the contract something a reader can see and a client can rely on.

snake_case throughout, matching the Python that produces it. Consistency across
the stack is worth more than matching JavaScript convention on one side of it.
"""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel, Field

from backend.control.commands import ClampResult, SafetyLimits
from backend.decision.loop import DecisionRecord
from backend.decision.policy import PolicyTuning
from backend.processing.carbon import GRID_CARBON_BASIS, carbon_kg
from backend.processing.context import BuildingContext, ZoneContext
from backend.reports.summary import BuildingReport, render_markdown
from backend.simulation.geometry import BuildingGeometry
from backend.services.building_service import ServiceConfig, ServiceStatus


class ClockOut(BaseModel):
    month: int
    day: int
    hour: int
    minute: int
    label: str


class ZoneOut(BaseModel):
    name: str
    temperature_c: float | None
    humidity_pct: float | None
    occupants: float | None
    cooling_setpoint_c: float | None
    pmv: float | None
    ppd_pct: float | None
    comfort: str | None
    co2_ppm: float | None
    air_quality: str | None
    ventilation_kg_s: float | None

    @classmethod
    def from_domain(cls, zone: ZoneContext) -> "ZoneOut":
        return cls(
            name=zone.name,
            temperature_c=zone.air_temperature_c,
            humidity_pct=zone.relative_humidity_pct,
            occupants=zone.occupant_count,
            cooling_setpoint_c=zone.cooling_setpoint_c,
            pmv=zone.pmv,
            ppd_pct=zone.ppd_pct,
            comfort=zone.comfort.value if zone.comfort else None,
            co2_ppm=zone.co2_ppm,
            air_quality=zone.air_quality.value if zone.air_quality else None,
            ventilation_kg_s=zone.ventilation_mass_flow_kg_s,
        )


class PowerOut(BaseModel):
    cooling_kw: float | None
    heating_kw: float | None
    fans_kw: float | None
    pumps_kw: float | None
    lighting_kw: float | None
    equipment_kw: float | None
    total_kw: float | None
    carbon_kg_per_hour: float | None = None


class SiteOut(BaseModel):
    outdoor_temperature_c: float | None
    outdoor_humidity_pct: float | None
    solar_w_per_m2: float | None


class SummaryOut(BaseModel):
    """Pre-computed aggregates, so the dashboard renders rather than calculates."""

    total_occupancy: float
    is_occupied: bool
    mean_pmv: float | None
    worst_zone: str | None
    worst_zone_pmv: float | None
    mean_cooling_setpoint_c: float | None
    peak_co2_ppm: float | None
    total_power_kw: float | None


class MetricsOut(BaseModel):
    sequence: int
    clock: ClockOut
    zones: list[ZoneOut]
    site: SiteOut
    power: PowerOut
    summary: SummaryOut

    @classmethod
    def from_domain(cls, context: BuildingContext) -> "MetricsOut":
        worst = context.worst_zone
        return cls(
            sequence=context.sequence,
            clock=ClockOut(
                month=context.clock.month,
                day=context.clock.day,
                hour=context.clock.hour,
                minute=context.clock.minute,
                label=context.clock.label,
            ),
            zones=[ZoneOut.from_domain(zone) for zone in context.zones],
            site=SiteOut(
                outdoor_temperature_c=context.site.outdoor_air_temperature_c,
                outdoor_humidity_pct=context.site.outdoor_relative_humidity_pct,
                solar_w_per_m2=context.site.direct_solar_w_per_m2,
            ),
            power=PowerOut(
                **asdict(context.power),
                carbon_kg_per_hour=carbon_kg(context.power.total_kw),
            ),
            summary=SummaryOut(
                total_occupancy=context.total_occupancy,
                is_occupied=context.is_occupied,
                mean_pmv=context.mean_pmv,
                worst_zone=worst.name if worst else None,
                worst_zone_pmv=worst.pmv if worst else None,
                mean_cooling_setpoint_c=context.mean_cooling_setpoint_c,
                peak_co2_ppm=context.peak_co2_ppm,
                total_power_kw=context.total_power_kw,
            ),
        )


class DecisionOut(BaseModel):
    sequence: int
    clock_label: str
    action: str
    reasoning: str
    observations: list[str]
    source: str
    cooling_setpoint_c: float | None
    lighting_fraction: float | None
    safety_adjustments: list[str]
    decided_at: str
    objective: str | None
    impact: dict | None
    baseline_action: str | None
    baseline_agrees: bool | None
    used_fallback: bool
    requested_setpoint_c: float | None

    @classmethod
    def from_domain(cls, record: DecisionRecord) -> "DecisionOut":
        command = record.clamp.command
        return cls(
            sequence=record.context.sequence,
            clock_label=record.context.clock.label,
            action=record.decision.action.value,
            reasoning=record.decision.reasoning,
            observations=list(record.decision.observations),
            source=command.source,
            cooling_setpoint_c=command.cooling_setpoint_c,
            lighting_fraction=command.lighting_fraction,
            safety_adjustments=list(record.clamp.adjustments),
            decided_at=record.decided_at.isoformat(),
            objective=record.decision.objective,
            impact=asdict(record.decision.impact) if record.decision.impact else None,
            baseline_action=record.baseline_action,
            baseline_agrees=record.baseline_agrees,
            used_fallback=record.used_fallback,
            # What the policy asked for before clamping, so the safety pipeline
            # can show request and applied side by side.
            requested_setpoint_c=record.decision.command.cooling_setpoint_c,
        )


class StatusOut(BaseModel):
    simulation_running: bool
    agent_running: bool
    timesteps_published: int
    decisions_taken: int
    policy_failures: int
    commands_submitted: int
    commands_adjusted: int
    policy_name: str
    llm_latency_seconds: float | None
    error: str | None
    is_paused: bool
    variables_resolved: int
    variables_requested: int
    meters_resolved: int
    meters_requested: int
    total_energy_kwh: float
    total_carbon_kg: float

    @classmethod
    def from_domain(cls, status: ServiceStatus) -> "StatusOut":
        return cls(**asdict(status))


class ConfigOut(BaseModel):
    """Everything an operator may inspect, including the safety envelope."""

    model_name: str
    policy: str
    llm_model: str
    seconds_per_timestep: float
    timesteps_per_decision: int
    start_date: str
    zones: list[str]
    limits: dict
    tuning: dict

    @classmethod
    def from_domain(
        cls,
        config: ServiceConfig,
        limits: SafetyLimits,
        tuning: PolicyTuning,
        zones: tuple[str, ...],
    ) -> "ConfigOut":
        return cls(
            model_name=config.model_name,
            policy=config.policy,
            llm_model=config.llm_model,
            seconds_per_timestep=config.seconds_per_timestep,
            timesteps_per_decision=config.timesteps_per_decision,
            start_date=f"{config.start_date.month:02d}-{config.start_date.day:02d}",
            zones=list(zones),
            limits=asdict(limits),
            tuning=asdict(tuning),
        )


class SetpointIn(BaseModel):
    """A manual override. Bounds here are advisory -- ControlStore clamps regardless."""

    cooling_setpoint_c: float = Field(description="Requested cooling setpoint in Celsius")
    source: str = Field(default="operator", max_length=40)


class CommandOut(BaseModel):
    """What the safety layer actually accepted, and how it differed."""

    accepted: bool
    action: str
    cooling_setpoint_c: float | None
    heating_setpoint_c: float | None
    lighting_fraction: float | None
    safety_adjustments: list[str]

    @classmethod
    def from_domain(cls, result: ClampResult) -> "CommandOut":
        command = result.command
        return cls(
            accepted=True,
            action=command.action.value,
            cooling_setpoint_c=command.cooling_setpoint_c,
            heating_setpoint_c=command.heating_setpoint_c,
            lighting_fraction=command.lighting_fraction,
            safety_adjustments=list(result.adjustments),
        )


class ReportOut(BaseModel):
    """A period report, in both structured and readable form.

    The markdown is included so a client that wants to show or forward the report
    does not have to reimplement its formatting, and so every consumer quotes the
    same wording -- including the caveat attached to the savings estimate.
    """

    headline: str
    period: dict
    energy: dict
    comfort: dict
    agent: dict
    savings: dict
    markdown: str

    @classmethod
    def from_domain(cls, report: BuildingReport) -> "ReportOut":
        return cls(
            headline=report.headline,
            period=asdict(report.period),
            energy=asdict(report.energy),
            comfort=asdict(report.comfort),
            agent=asdict(report.agent),
            savings=asdict(report.savings),
            markdown=render_markdown(report),
        )


class ZoneGeometryOut(BaseModel):
    """A zone's real plan footprint, read from the EnergyPlus model."""

    name: str
    footprint: list[list[float]]
    area_m2: float
    centroid: list[float]
    is_core: bool
    orientation: str | None
    azimuth_deg: float | None


class GeometryOut(BaseModel):
    """Static building geometry. Fetched once; it does not change during a run."""

    zones: list[ZoneGeometryOut]
    bounds: list[float]
    width_m: float
    depth_m: float
    floor_area_m2: float
    carbon_basis: str

    @classmethod
    def from_domain(cls, geometry: BuildingGeometry) -> "GeometryOut":
        return cls(
            zones=[
                ZoneGeometryOut(
                    name=zone.name,
                    footprint=[[x, y] for x, y in zone.footprint],
                    area_m2=zone.area_m2,
                    centroid=list(zone.centroid),
                    is_core=zone.is_core,
                    orientation=zone.orientation,
                    azimuth_deg=zone.azimuth_deg,
                )
                for zone in geometry.zones
            ],
            bounds=list(geometry.bounds),
            width_m=geometry.width_m,
            depth_m=geometry.depth_m,
            floor_area_m2=geometry.floor_area_m2,
            carbon_basis=GRID_CARBON_BASIS,
        )
