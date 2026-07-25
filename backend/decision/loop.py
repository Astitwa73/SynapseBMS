"""Runs a policy against the live building on a fixed simulated-time cadence.

Triggering on published timesteps rather than a wall-clock timer keeps the
agent's behaviour independent of demo playback speed: the same run produces the
same decisions whether it is played at 0.5s or 0.05s per timestep. It also makes
"the agent reviews the building hourly" a true statement about the building
rather than about the laptop.

The loop is the supervisory layer. If the policy is slow, raises, or returns
nonsense, the simulation is unaffected -- it keeps applying the last accepted
command, and a policy failure is logged rather than propagated.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from backend.control.commands import ClampResult
from backend.control.store import ControlStore
from backend.decision.explain import current_objective, expected_impact
from backend.decision.policy import Decision, DecisionPolicy
from backend.processing.air_quality import AirQualityAssumptions
from backend.processing.comfort import ComfortAssumptions
from backend.processing.context import BuildingContext, build_context
from backend.simulation.state import SimulationStateStore

logger = logging.getLogger(__name__)

THREAD_NAME = "decision-loop"
DEFAULT_TIMESTEPS_PER_DECISION = 4  # one simulated hour at 15-minute timesteps


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """A decision, what the safety layer did to it, and when."""

    decision: Decision
    clamp: ClampResult
    context: BuildingContext
    decided_at: datetime

    # What the deterministic baseline would have chosen for the same context.
    # Present only when a baseline policy exists, which is when the language
    # model is driving. Agreement is a measured signal, unlike a model's
    # self-reported confidence, which is unverifiable and poorly calibrated.
    baseline_action: str | None = None
    used_fallback: bool = False

    @property
    def was_adjusted(self) -> bool:
        return self.clamp.was_adjusted

    @property
    def baseline_agrees(self) -> bool | None:
        if self.baseline_action is None:
            return None
        return self.baseline_action == self.decision.action.value


class DecisionLoop:
    """Watches the state store and drives a policy on a fixed cadence."""

    def __init__(
        self,
        policy: DecisionPolicy,
        state: SimulationStateStore,
        control: ControlStore,
        timesteps_per_decision: int = DEFAULT_TIMESTEPS_PER_DECISION,
        history_limit: int = 500,
        comfort_assumptions: ComfortAssumptions | None = None,
        air_quality_assumptions: AirQualityAssumptions | None = None,
        fallback: DecisionPolicy | None = None,
    ) -> None:
        if timesteps_per_decision < 1:
            raise ValueError("timesteps_per_decision must be at least 1")

        self._policy = policy
        self._fallback = fallback
        self._state = state
        self._control = control
        self._cadence = timesteps_per_decision
        self._comfort = comfort_assumptions
        self._air_quality = air_quality_assumptions

        self._lock = threading.Lock()
        self._history: deque[DecisionRecord] = deque(maxlen=history_limit)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_sequence = 0
        self._failures = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Loop already started")
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def latest(self) -> DecisionRecord | None:
        with self._lock:
            return self._history[-1] if self._history else None

    def history(self, limit: int | None = None) -> tuple[DecisionRecord, ...]:
        with self._lock:
            records = tuple(self._history)
        return records[-limit:] if limit is not None else records

    @property
    def failure_count(self) -> int:
        return self._failures

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = self._state.latest()
            if snapshot is None or snapshot.sequence - self._last_sequence < self._cadence:
                # Short poll rather than a condition variable: the state store is
                # the single source of truth and this keeps it free of observers.
                self._stop.wait(0.05)
                continue

            self._last_sequence = snapshot.sequence
            try:
                self._decide_once(snapshot)
            except Exception:  # noqa: BLE001 - a policy failure must not kill the loop
                self._failures += 1
                logger.exception("Decision failed; the last accepted command stays in force")

    def _decide_once(self, snapshot) -> None:
        context = build_context(
            snapshot,
            comfort_assumptions=self._comfort,
            air_quality_assumptions=self._air_quality,
        )

        used_fallback = False
        try:
            decision = self._policy.decide(context)
        except Exception:
            if self._fallback is None:
                raise
            self._failures += 1
            logger.exception(
                "Policy %s failed; falling back to %s", self._policy.name, self._fallback.name
            )
            decision = self._fallback.decide(context)
            used_fallback = True

        decision = replace(
            decision,
            impact=expected_impact(decision.command.action, context),
            objective=current_objective(decision.command.action, context),
        )
        clamp_result = self._control.submit(decision.command)

        record = DecisionRecord(
            decision=decision,
            clamp=clamp_result,
            context=context,
            decided_at=datetime.now(timezone.utc),
            baseline_action=self._baseline_action(context, used_fallback),
            used_fallback=used_fallback,
        )
        with self._lock:
            self._history.append(record)

        logger.info("[%s] %s", decision.action.value, decision.reasoning)

    def _baseline_action(self, context: BuildingContext, used_fallback: bool) -> str | None:
        """What the deterministic policy would choose for the same building state.

        Cheap enough to run on every decision -- the rule ladder is arithmetic --
        and it turns "do we trust the model" into something observable. Skipped
        when the fallback already produced the decision, since a policy cannot
        meaningfully agree with itself.
        """
        if self._fallback is None or used_fallback:
            return None
        try:
            return self._fallback.decide(context).command.action.value
        except Exception:  # noqa: BLE001 - a broken baseline must not lose the decision
            logger.exception("Baseline comparison failed")
            return None
