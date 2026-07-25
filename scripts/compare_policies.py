"""Measure what the agent is actually worth.

Runs the same simulated day three ways -- no agent, rule engine, language model
-- and reports energy and comfort side by side. Without this the claim "our AI
saves energy" is an assertion; with it, it is a number with a comfort cost
attached.

Decisions are made synchronously inside the simulation callback, so every policy
gets exactly the same number of decisions at exactly the same points in the day
however long it takes to think. Pacing the simulation on wall-clock time instead
would hand the fast policy more decisions than the slow one and measure laptop
speed as much as judgment.

    python scripts/compare_policies.py
    python scripts/compare_policies.py --date 07-15 --decide-every 4
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.llm_policy import LlmPolicy  # noqa: E402
from backend.agent.ollama_client import OllamaClient, OllamaError, OllamaSettings  # noqa: E402
from backend.config.logging import configure_logging  # noqa: E402
from backend.config.settings import (  # noqa: E402
    DEFAULT_MODEL_NAME,
    MODELS_DIR,
    CalendarDay,
    SimulationSettings,
)
from backend.control.store import ControlStore  # noqa: E402
from backend.decision.policy import (  # noqa: E402
    Decision,
    DecisionPolicy,
    PolicyTuning,
    RuleBasedPolicy,
)
from backend.processing.context import build_context  # noqa: E402
from backend.simulation.engine import SimulationEngine  # noqa: E402
from backend.simulation.idf import controllable_zone_names, lights_by_zone  # noqa: E402
from backend.simulation.sensors import SensorCatalog  # noqa: E402
from backend.simulation.state import SimulationStateStore  # noqa: E402

JOULES_PER_KWH = 3.6e6
COMFORT_LIMIT = PolicyTuning().comfortable_pmv


@dataclass
class Result:
    label: str
    cooling_kwh: float = 0.0
    lighting_kwh: float = 0.0
    fans_kwh: float = 0.0
    total_kwh: float = 0.0
    occupied_samples: int = 0
    uncomfortable_samples: int = 0
    pmv_sum: float = 0.0
    setpoint_sum: float = 0.0
    setpoint_samples: int = 0
    decisions: int = 0
    fallbacks: int = 0
    clamped: int = 0
    error: str | None = None

    @property
    def mean_occupied_pmv(self) -> float | None:
        return self.pmv_sum / self.occupied_samples if self.occupied_samples else None

    @property
    def uncomfortable_pct(self) -> float | None:
        if not self.occupied_samples:
            return None
        return self.uncomfortable_samples / self.occupied_samples * 100

    @property
    def mean_setpoint_c(self) -> float | None:
        return self.setpoint_sum / self.setpoint_samples if self.setpoint_samples else None


class SynchronousDriver:
    """Decides every N timesteps, inline with the simulation, and records outcomes."""

    def __init__(
        self,
        policy: DecisionPolicy | None,
        fallback: DecisionPolicy | None,
        control: ControlStore | None,
        day: CalendarDay,
        cadence: int,
        result: Result,
    ) -> None:
        self._policy = policy
        self._fallback = fallback
        self._control = control
        self._day = tuple(day)
        self._cadence = cadence
        self._result = result
        self._since_decision = 0

    def __call__(self, snapshot) -> None:
        if snapshot.clock.calendar_day != self._day:
            return

        context = build_context(snapshot)
        self._record_conditions(context)

        if self._policy is None or self._control is None:
            return

        self._since_decision += 1
        if self._since_decision < self._cadence:
            return
        self._since_decision = 0

        decision = self._decide(context)
        if decision is None:
            return

        clamp_result = self._control.submit(decision.command)
        self._result.decisions += 1
        if clamp_result.was_adjusted:
            self._result.clamped += 1

    def _decide(self, context) -> Decision | None:
        try:
            return self._policy.decide(context)
        except Exception:  # noqa: BLE001 - a policy failure is a measured outcome
            self._result.fallbacks += 1
            if self._fallback is None:
                return None
            return self._fallback.decide(context)

    def _record_conditions(self, context) -> None:
        result = self._result
        result.cooling_kwh += (context.energy.cooling_electricity_j or 0.0) / JOULES_PER_KWH
        result.lighting_kwh += (
            context.energy.interior_lights_electricity_j or 0.0
        ) / JOULES_PER_KWH
        result.fans_kwh += (context.energy.fans_electricity_j or 0.0) / JOULES_PER_KWH
        result.total_kwh += (context.energy.total_electricity_j or 0.0) / JOULES_PER_KWH

        for zone in context.occupied_zones:
            if zone.pmv is None:
                continue
            result.occupied_samples += 1
            result.pmv_sum += zone.pmv
            if abs(zone.pmv) > COMFORT_LIMIT:
                result.uncomfortable_samples += 1

        if context.is_occupied and context.mean_cooling_setpoint_c is not None:
            result.setpoint_sum += context.mean_cooling_setpoint_c
            result.setpoint_samples += 1


def run(
    label: str,
    model_path: Path,
    day: CalendarDay,
    cadence: int,
    policy: DecisionPolicy | None,
    fallback: DecisionPolicy | None,
) -> Result:
    result = Result(label=label)
    state = SimulationStateStore(history_limit=200)
    control = ControlStore() if policy is not None else None

    engine = SimulationEngine(
        settings=SimulationSettings(
            model_path=model_path,
            seconds_per_timestep=0.0,
            report_from=day,
        ),
        catalog=SensorCatalog(zone_names=tuple(controllable_zone_names(model_path))),
        store=state,
        control=control,
        lights_by_zone=lights_by_zone(model_path),
        on_timestep=SynchronousDriver(policy, fallback, control, day, cadence, result),
    )

    print(f"  running {label}...", flush=True)
    engine.start()
    engine.wait_until_finished(timeout=1800)
    result.error = engine.status().error
    return result


def print_table(results: list[Result]) -> None:
    rows = (
        ("cooling energy", "cooling_kwh", "kWh", "{:.2f}"),
        ("lighting energy", "lighting_kwh", "kWh", "{:.2f}"),
        ("fan energy", "fans_kwh", "kWh", "{:.2f}"),
        ("total electricity", "total_kwh", "kWh", "{:.2f}"),
        ("setpoint, occupied", "mean_setpoint_c", "C", "{:.2f}"),
        ("mean occupied PMV", "mean_occupied_pmv", "", "{:+.3f}"),
        ("time uncomfortable", "uncomfortable_pct", "%", "{:.1f}"),
        ("decisions", "decisions", "", "{:.0f}"),
        ("fallbacks", "fallbacks", "", "{:.0f}"),
        ("safety adjustments", "clamped", "", "{:.0f}"),
    )

    width = 15
    header = f"{'':<22}" + "".join(f"{r.label:>{width}}" for r in results)
    print(f"\n{header}")
    print("-" * len(header))

    for label, attribute, unit, fmt in rows:
        cells = ""
        for result in results:
            value = getattr(result, attribute)
            cells += f"{(fmt.format(value) if value is not None else 'n/a'):>{width}}"
        name = f"{label} ({unit})" if unit else label
        print(f"{name:<22}{cells}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--date", default="07-02")
    parser.add_argument("--decide-every", type=int, default=4)
    parser.add_argument("--llm-model", default="llama3")
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()

    configure_logging(logging.ERROR)

    model_path = MODELS_DIR / args.model
    if not model_path.is_file():
        print(f"FAIL: {model_path} not found. Run: python scripts/prepare_model.py")
        return 1

    month, day = (int(part) for part in args.date.split("-"))
    target = CalendarDay(month=month, day=day)
    rules = RuleBasedPolicy()

    llm: LlmPolicy | None = None
    if not args.skip_llm:
        client = OllamaClient(OllamaSettings(model=args.llm_model))
        try:
            client.check_ready()
        except OllamaError as exc:
            print(f"FAIL: {exc}")
            print("      Use --skip-llm to compare the baseline and rule engine only.")
            return 1
        llm = LlmPolicy(client=client)

    print(f"Comparing policies on {args.date}, deciding every {args.decide_every} timesteps\n")

    results = [
        run("no agent", model_path, target, args.decide_every, None, None),
        run("rule engine", model_path, target, args.decide_every, rules, None),
    ]
    if llm is not None:
        results.append(run(args.llm_model, model_path, target, args.decide_every, llm, rules))

    for result in results:
        if result.error:
            print(f"FAIL: {result.label} run errored: {result.error}")
            return 1

    print_table(results)

    baseline = results[0]
    print()
    for result in results[1:]:
        saved = baseline.cooling_kwh - result.cooling_kwh
        percent = saved / baseline.cooling_kwh * 100 if baseline.cooling_kwh else 0.0
        comfort = result.uncomfortable_pct
        print(
            f"{result.label:<15} cooling {saved:+6.2f} kWh ({percent:+5.1f}%)"
            f"   uncomfortable {comfort:.1f}% vs {baseline.uncomfortable_pct:.1f}%"
        )

    if llm is not None and llm.mean_latency_seconds is not None:
        print(f"\nMean LLM latency: {llm.mean_latency_seconds:.2f}s per decision")

    if baseline.cooling_kwh <= 0:
        print("\nFAIL: baseline used no cooling energy; pick a warmer date")
        return 1

    print("\nOK: policies compared on identical conditions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
