"""Runtime configuration for the simulation layer.

Deliberately a plain frozen dataclass rather than pydantic-settings or a YAML
file: there is exactly one consumer today and nothing here needs validation
beyond type hints. A building-description YAML arrives when we have per-building
values worth externalising (zone display names, comfort bands, tariffs).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


class CalendarDay(NamedTuple):
    """A month/day in the simulated year, independent of calendar year."""

    month: int
    day: int

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

    # Design days are sizing scenarios, not operating scenarios: their schedules
    # zero out occupancy so equipment is sized for the worst case. That leaves an
    # empty building with flat energy use -- nothing for a BMS agent to reason
    # about. The annual run period carries real occupancy and weather instead.
    design_day_only: bool = False

    # An annual run reaches December in about 11 seconds unthrottled, so we skip
    # ahead to an interesting date at full speed and only then drop to demo pace.
    # None reports from the first timestep.
    report_from: CalendarDay | None = CalendarDay(month=7, day=1)

    # Wall-clock seconds to spend per simulation timestep. Pacing happens inside
    # the sensor callback, so this throttles EnergyPlus itself rather than
    # dropping data on the floor.
    seconds_per_timestep: float = 0.5

    history_limit: int = 2880

    output_dir: Path = PROJECT_ROOT / "run_output" / "simulation"
