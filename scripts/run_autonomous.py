"""Run the building under autonomous agent control.

Simulation, processing, decision and control all running together with no LLM:
this is the fully working baseline the language model will later be measured
against.

    python scripts/run_autonomous.py
    python scripts/run_autonomous.py --speed 0.1 --seconds 60 --from-date 07-02

Ctrl+C stops cleanly.
"""

from __future__ import annotations

import argparse
import logging
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
from backend.control.store import ControlStore  # noqa: E402
from backend.decision.loop import DecisionLoop  # noqa: E402
from backend.decision.policy import RuleBasedPolicy  # noqa: E402
from backend.simulation.engine import SimulationEngine  # noqa: E402
from backend.simulation.idf import controllable_zone_names, lights_by_zone  # noqa: E402
from backend.simulation.sensors import SensorCatalog  # noqa: E402
from backend.simulation.state import SimulationStateStore  # noqa: E402


def print_decision(record) -> None:
    context = record.context
    decision = record.decision

    print(f"\n  {context.clock.label}  [{decision.action.value}]")
    print(f"    {' | '.join(decision.observations)}")
    print(f"    {decision.reasoning}")
    for adjustment in record.clamp.adjustments:
        print(f"    SAFETY: {adjustment}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--speed", type=float, default=0.1)
    parser.add_argument("--seconds", type=float, default=90.0)
    parser.add_argument("--from-date", default="07-02")
    parser.add_argument(
        "--decide-every", type=int, default=4, help="timesteps per decision (4 = hourly)"
    )
    args = parser.parse_args()

    configure_logging(logging.WARNING)

    model_path = MODELS_DIR / args.model
    if not model_path.is_file():
        print(f"FAIL: {model_path} not found. Run: python scripts/prepare_model.py")
        return 1

    zones = controllable_zone_names(model_path)
    month, day = (int(part) for part in args.from_date.split("-"))

    state = SimulationStateStore()
    control = ControlStore()
    policy = RuleBasedPolicy()

    engine = SimulationEngine(
        settings=SimulationSettings(
            model_path=model_path,
            seconds_per_timestep=args.speed,
            report_from=CalendarDay(month=month, day=day),
        ),
        catalog=SensorCatalog(zone_names=tuple(zones)),
        store=state,
        control=control,
        lights_by_zone=lights_by_zone(model_path),
    )
    loop = DecisionLoop(policy, state, control, timesteps_per_decision=args.decide_every)

    print(f"Model  : {model_path.name}")
    print(f"Zones  : {', '.join(zones)}")
    print(f"Policy : {policy.name}, deciding every {args.decide_every} timesteps")
    print(f"Start  : {args.from_date}\n")

    try:
        engine.start()
    except EnergyPlusNotFoundError as exc:
        print(f"FAIL: {exc}")
        return 1
    loop.start()

    started = time.perf_counter()
    seen = 0
    try:
        while engine.is_running and time.perf_counter() - started < args.seconds:
            records = loop.history()
            for record in records[seen:]:
                print_decision(record)
            seen = len(records)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        loop.stop()
        engine.stop()

    records = loop.history()
    submitted, adjusted = control.counters
    actions: dict[str, int] = {}
    for record in records:
        actions[record.decision.action.value] = actions.get(record.decision.action.value, 0) + 1

    print(f"\n{'-' * 58}")
    print(f"Timesteps simulated : {state.published_count}")
    print(f"Decisions taken     : {len(records)}")
    print(f"Commands clamped    : {adjusted}/{submitted}")
    print(f"Policy failures     : {loop.failure_count}")
    print(f"Actions             : {actions or 'none'}")

    if engine.status().error:
        print(f"FAIL: {engine.status().error}")
        return 1
    if not records:
        print("FAIL: the agent never decided anything")
        return 1

    print("\nOK: the building ran under autonomous agent control.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
