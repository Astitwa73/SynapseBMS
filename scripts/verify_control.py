"""Prove the control loop closes, and measure what it is worth.

Runs the same summer day twice -- once untouched, once with a fixed setpoint
command in force -- and reports the difference in cooling energy. This is the
Module 2 acceptance test and the source of the savings figure used in the demo.

    python scripts/verify_control.py
    python scripts/verify_control.py --setpoint 26.0 --date 07-02
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.logging import configure_logging  # noqa: E402
from backend.config.settings import (  # noqa: E402
    DEFAULT_MODEL_NAME,
    MODELS_DIR,
    CalendarDay,
    SimulationSettings,
)
from backend.control.commands import ControlAction, ControlCommand  # noqa: E402
from backend.control.store import ControlStore  # noqa: E402
from backend.simulation.engine import SimulationEngine  # noqa: E402
from backend.simulation.idf import controllable_zone_names, lights_by_zone  # noqa: E402
from backend.simulation.sensors import SensorCatalog  # noqa: E402
from backend.simulation.state import SimulationStateStore  # noqa: E402

JOULES_PER_KWH = 3.6e6


def run_day(model_path: Path, day: CalendarDay, command: ControlCommand | None) -> dict:
    """Simulate one day, optionally with a command in force, and total the meters."""
    # The run continues to December after the target day, so history must hold a
    # full year or the day under test is evicted before it can be read.
    store = SimulationStateStore(history_limit=40_000)
    control = None

    if command is not None:
        control = ControlStore()
        # Submitted repeatedly so rate limiting converges before the day starts;
        # a single submission would only move the setpoint by one step.
        for _ in range(40):
            control.submit(command)

    engine = SimulationEngine(
        settings=SimulationSettings(
            model_path=model_path,
            seconds_per_timestep=0.0,
            report_from=day,
        ),
        catalog=SensorCatalog(zone_names=tuple(controllable_zone_names(model_path))),
        store=store,
        control=control,
        lights_by_zone=lights_by_zone(model_path),
    )
    engine.start()
    engine.wait_until_finished(timeout=600)

    day_snapshots = [s for s in store.history() if s.clock.calendar_day == tuple(day)]
    if not day_snapshots:
        raise RuntimeError(f"No snapshots captured for {day.month:02d}-{day.day:02d}")

    def total(attribute: str) -> float:
        return sum(getattr(s.energy, attribute) or 0.0 for s in day_snapshots) / JOULES_PER_KWH

    # Occupied hours only: the overnight setback is much higher than the daytime
    # setpoint, and averaging it in hides the change the agent actually made.
    setpoints = [
        z.cooling_setpoint_c
        for s in day_snapshots
        if s.total_occupancy
        for z in s.zones
        if z.cooling_setpoint_c
    ]
    return {
        "timesteps": len(day_snapshots),
        "cooling_kwh": total("cooling_electricity_j"),
        "heating_kwh": total("heating_electricity_j"),
        "fans_kwh": total("fans_electricity_j"),
        "lighting_kwh": total("interior_lights_electricity_j"),
        "total_kwh": sum(s.energy.total_electricity_j or 0.0 for s in day_snapshots)
        / JOULES_PER_KWH,
        "mean_setpoint_c": sum(setpoints) / len(setpoints) if setpoints else None,
        "peak_temperature_c": max(
            (s.mean_air_temperature_c for s in day_snapshots if s.mean_air_temperature_c),
            default=None,
        ),
        "error": engine.status().error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--setpoint", type=float, default=26.0)
    parser.add_argument("--date", default="07-02", help="MM-DD to compare")
    args = parser.parse_args()

    configure_logging(logging.WARNING)

    model_path = MODELS_DIR / args.model
    if not model_path.is_file():
        print(f"FAIL: {model_path} not found. Run: python scripts/prepare_model.py")
        return 1

    month, day = (int(part) for part in args.date.split("-"))
    target = CalendarDay(month=month, day=day)

    print(f"Comparing {args.date} with and without agent control...\n")
    baseline = run_day(model_path, target, command=None)
    controlled = run_day(
        model_path,
        target,
        command=ControlCommand(
            action=ControlAction.RAISE_SETPOINT,
            cooling_setpoint_c=args.setpoint,
            source="verify_control",
        ),
    )

    for label, result in (("baseline", baseline), ("controlled", controlled)):
        if result["error"]:
            print(f"FAIL: {label} run errored: {result['error']}")
            return 1

    header = f"{'':<22}{'baseline':>12}{'controlled':>12}{'change':>12}"
    print(header)
    print("-" * len(header))
    for label, key, unit in (
        ("setpoint, occupied", "mean_setpoint_c", "C"),
        ("peak indoor temp", "peak_temperature_c", "C"),
        ("cooling energy", "cooling_kwh", "kWh"),
        ("heating energy", "heating_kwh", "kWh"),
        ("fan energy", "fans_kwh", "kWh"),
        ("lighting energy", "lighting_kwh", "kWh"),
        ("total electricity", "total_kwh", "kWh"),
    ):
        before, after = baseline[key], controlled[key]
        if before is None or after is None:
            continue
        print(f"{label + ' (' + unit + ')':<22}{before:>12.2f}{after:>12.2f}{after - before:>+12.2f}")

    saved = baseline["cooling_kwh"] - controlled["cooling_kwh"]
    if baseline["cooling_kwh"] <= 0:
        print("\nFAIL: baseline used no cooling energy; pick a warmer date")
        return 1

    percent = saved / baseline["cooling_kwh"] * 100
    print(f"\nCooling energy saved: {saved:.2f} kWh ({percent:.1f}%)")

    if abs(saved) < 1e-6:
        print("FAIL: control had no measurable effect")
        return 1

    print("OK: control commands reach EnergyPlus and change building behaviour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
