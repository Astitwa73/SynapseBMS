"""Check the language model before trusting it in a demo.

Runs a handful of building states past the model and reports what it chose, why,
and how long it took. Latency is the number that matters: a supervisory decision
is due every simulated hour, and a model slower than that cadence will spend the
demo falling back to the rule engine.

    python scripts/verify_agent.py
    python scripts/verify_agent.py --llm-model llama3.2:3b --repeats 3
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.llm_policy import LlmPolicy  # noqa: E402
from backend.agent.ollama_client import OllamaClient, OllamaError, OllamaSettings  # noqa: E402
from backend.control.commands import ControlAction  # noqa: E402
from backend.processing.context import build_context  # noqa: E402
from backend.simulation.state import (  # noqa: E402
    EnergyReading,
    SensorSnapshot,
    SimulationClock,
    SiteReading,
    ZoneReading,
)


@dataclass(frozen=True)
class Scenario:
    label: str
    temperature_c: float
    occupants: float
    setpoint_c: float
    hour: int
    sensible: tuple[ControlAction, ...]


# `sensible` is what a competent building engineer would accept, not a single
# right answer: several actions are defensible in most states.
SCENARIOS = (
    Scenario("empty building, overnight", 22.0, 0, 24.0, 2,
             (ControlAction.RAISE_SETPOINT, ControlAction.REDUCE_LIGHTING)),
    Scenario("occupied and too warm", 29.5, 52, 26.0, 14,
             (ControlAction.LOWER_SETPOINT,)),
    Scenario("occupied and overcooled", 21.0, 52, 23.0, 10,
             (ControlAction.RAISE_SETPOINT,)),
    Scenario("occupied and comfortable", 25.4, 40, 25.0, 11,
             (ControlAction.HOLD, ControlAction.RAISE_SETPOINT)),
    Scenario("empty during the day", 26.0, 0, 24.0, 19,
             (ControlAction.RAISE_SETPOINT, ControlAction.REDUCE_LIGHTING)),
)


def context_for(scenario: Scenario):
    return build_context(
        SensorSnapshot(
            clock=SimulationClock(month=7, day=2, hour=scenario.hour, minute=0),
            zones=tuple(
                ZoneReading(
                    name=f"SPACE{index}-1",
                    air_temperature_c=scenario.temperature_c,
                    relative_humidity_pct=50.0,
                    occupant_count=scenario.occupants / 5,
                    cooling_setpoint_c=scenario.setpoint_c,
                    ventilation_mass_flow_kg_s=0.4,
                    lighting_power_w=1350.0,
                )
                for index in range(1, 6)
            ),
            site=SiteReading(outdoor_air_temperature_c=28.0),
            energy=EnergyReading(building_electricity_j=9.9e6, plant_electricity_j=3.0e6),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-model", default="llama3")
    parser.add_argument("--repeats", type=int, default=1, help="runs per scenario")
    parser.add_argument("--cadence-seconds", type=float, default=None,
                        help="wall-clock budget per decision; defaults to no budget")
    args = parser.parse_args()

    client = OllamaClient(OllamaSettings(model=args.llm_model))
    try:
        client.check_ready()
    except OllamaError as exc:
        print(f"FAIL: {exc}")
        return 1

    policy = LlmPolicy(client=client)
    print(f"Model: {args.llm_model}\n")

    failures = 0
    surprising = 0

    for scenario in SCENARIOS:
        context = context_for(scenario)
        for attempt in range(args.repeats):
            try:
                decision = policy.decide(context)
            except OllamaError as exc:
                failures += 1
                print(f"  FAIL  {scenario.label}: {exc}")
                continue

            expected = decision.action in scenario.sensible
            if not expected:
                surprising += 1

            marker = "ok  " if expected else "hmm "
            suffix = f" (attempt {attempt + 1})" if args.repeats > 1 else ""
            print(f"  {marker}{scenario.label}{suffix}")
            print(f"        action    : {decision.action.value}")
            print(f"        reasoning : {decision.reasoning}")
            print(f"        latency   : {policy.last_latency_seconds:.2f}s")
            if not expected:
                print(f"        expected  : {', '.join(a.value for a in scenario.sensible)}")

    total = len(SCENARIOS) * args.repeats
    mean_latency = policy.mean_latency_seconds

    print(f"\n{'-' * 58}")
    print(f"Scenarios       : {total}")
    print(f"Model failures  : {failures}")
    print(f"Unexpected picks: {surprising}")
    if mean_latency is not None:
        print(f"Mean latency    : {mean_latency:.2f}s")

    if failures:
        print("\nFAIL: the model produced unusable responses.")
        return 1

    if args.cadence_seconds and mean_latency and mean_latency > args.cadence_seconds:
        print(
            f"\nFAIL: {mean_latency:.1f}s per decision exceeds the "
            f"{args.cadence_seconds:.1f}s budget. Try a smaller model."
        )
        return 1

    print("\nOK: the model returns usable decisions.")
    if surprising:
        print("Note: some picks were outside the expected set. Defensible, but review them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
