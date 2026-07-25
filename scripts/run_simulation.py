"""Run the simulation engine and watch live sensor data arrive.

This is the Module 1 acceptance test: it proves EnergyPlus runs on its own
thread, publishes coherent snapshots, and can be observed and stopped from the
main thread without touching EnergyPlus directly.

    python scripts/run_simulation.py
    python scripts/run_simulation.py --speed 0.1 --seconds 20

Ctrl+C stops the simulation cleanly.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config.logging import configure_logging  # noqa: E402
from backend.config.paths import EnergyPlusNotFoundError  # noqa: E402
from backend.config.settings import (  # noqa: E402
    DEFAULT_MODEL_NAME,
    MODELS_DIR,
    CalendarDay,
    SimulationSettings,
)
from backend.simulation.engine import SimulationEngine  # noqa: E402
from backend.simulation.idf import controllable_zone_names  # noqa: E402
from backend.simulation.sensors import SensorCatalog  # noqa: E402
from backend.simulation.state import SensorSnapshot, SimulationStateStore  # noqa: E402


def format_snapshot(snapshot: SensorSnapshot) -> str:
    mean_temp = snapshot.mean_air_temperature_c
    outdoor = snapshot.site.outdoor_air_temperature_c
    total_j = snapshot.energy.total_electricity_j
    occupancy = snapshot.total_occupancy

    return (
        f"#{snapshot.sequence:<4} {snapshot.clock.label}  "
        f"indoor {_number(mean_temp, '5.2f')}C  "
        f"outdoor {_number(outdoor, '5.2f')}C  "
        f"occupancy {_number(occupancy, '5.1f')}  "
        f"energy {_number(total_j and total_j / 3.6e6, '7.3f')} kWh"
    )


def _number(value: float | None, spec: str) -> str:
    return format(value, spec) if value is not None else "n/a".rjust(len(format(0.0, spec)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--speed",
        type=float,
        default=0.25,
        help="wall-clock seconds per simulation timestep (0 runs flat out)",
    )
    parser.add_argument(
        "--seconds", type=float, default=None, help="stop after this many seconds"
    )
    parser.add_argument(
        "--from-date",
        default="07-01",
        help="MM-DD to fast-forward to before reporting, or 'start'",
    )
    args = parser.parse_args()

    configure_logging()

    model_path = MODELS_DIR / args.model
    if not model_path.is_file():
        print(f"FAIL: {model_path} not found. Run: python scripts/prepare_model.py")
        return 1

    zones = controllable_zone_names(model_path)
    if not zones:
        print(f"FAIL: no thermostat-controlled zones in {model_path.name}")
        return 1

    print(f"Model : {model_path.name}")
    print(f"Zones : {', '.join(zones)}\n")

    report_from = None
    if args.from_date != "start":
        month, day = (int(part) for part in args.from_date.split("-"))
        report_from = CalendarDay(month=month, day=day)
        print(f"Fast-forwarding to {month:02d}-{day:02d} before reporting\n")

    store = SimulationStateStore()
    engine = SimulationEngine(
        settings=SimulationSettings(
            model_path=model_path,
            seconds_per_timestep=args.speed,
            report_from=report_from,
        ),
        catalog=SensorCatalog(zone_names=tuple(zones)),
        store=store,
    )

    try:
        engine.start()
    except EnergyPlusNotFoundError as exc:
        print(f"FAIL: {exc}")
        return 1

    started = time.perf_counter()
    last_seen = 0

    try:
        while engine.is_running:
            if args.seconds and time.perf_counter() - started > args.seconds:
                print("\nTime limit reached, stopping.")
                break

            # Draining by sequence rather than polling latest(): a consumer that
            # falls behind still sees every timestep instead of silently skipping.
            for snapshot in store.history_since(last_seen):
                last_seen = snapshot.sequence
                print(format_snapshot(snapshot))
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nInterrupted, stopping.")
    finally:
        engine.stop()

    status = engine.status()
    elapsed = time.perf_counter() - started
    print(f"\nPublished {status.timesteps_published} timesteps in {elapsed:.1f}s")
    print(f"History retained: {len(store.history())}")

    if status.error:
        print(f"FAIL: {status.error}")
        return 1

    if status.timesteps_published == 0:
        print("FAIL: no snapshots were published")
        return 1

    print("OK: simulation engine published live sensor data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
