"""Runtime configuration for the simulation layer.

Deliberately a plain frozen dataclass rather than pydantic-settings or a YAML
file: there is exactly one consumer today and nothing here needs validation
beyond type hints. A building-description YAML arrives when we have per-building
values worth externalising (zone display names, comfort bands, tariffs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models"
DOCS_DIR = PROJECT_ROOT / "docs"

# 5ZoneAirCooled is the most heavily exercised example in the EnergyPlus test
# suite and has what a BMS demo needs: multiple zones, thermostats, lighting and
# occupancy schedules. Small enough to run at demo speed.
DEFAULT_MODEL_NAME = "5ZoneAirCooled.idf"


def run_output_dir(name: str) -> Path:
    """Return (creating if needed) a directory for EnergyPlus run artifacts.

    Deliberately project-local and never cleaned up: EnergyPlus writes its error
    log here, and eplusout.err is the first thing anyone needs when a run
    misbehaves. Discarding it to keep the filesystem tidy trades away the only
    diagnostic that matters.
    """
    path = PROJECT_ROOT / "run_output" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True, slots=True)
class SimulationSettings:
    """How to run the building simulation."""

    model_path: Path = MODELS_DIR / DEFAULT_MODEL_NAME
    weather_path: Path | None = None  # None selects a shipped .epw at startup

    # Design-day mode runs the two sizing days instead of a full year: a couple
    # hundred timesteps under extreme conditions, which is both fast enough to
    # watch live and a defensible demo scenario (peak load performance).
    design_day_only: bool = True

    # Wall-clock seconds to spend per simulation timestep. Pacing happens inside
    # the sensor callback, so this throttles EnergyPlus itself rather than
    # dropping data on the floor.
    seconds_per_timestep: float = 0.5

    history_limit: int = 2880

    output_dir: Path = PROJECT_ROOT / "run_output"


@dataclass(frozen=True, slots=True)
class BuildingSettings:
    """Static description of the building being simulated."""

    zone_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def zone_count(self) -> int:
        return len(self.zone_names)
