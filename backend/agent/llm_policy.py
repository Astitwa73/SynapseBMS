"""A DecisionPolicy backed by a local language model.

Implements the same interface as the rule engine and produces commands through
the same arithmetic, so the two differ only in judgment.

The model's output surface is deliberately tiny: one action label from a closed
set, plus a sentence of reasoning. It never emits a setpoint. That removes an
entire class of failure -- unit confusion, off-by-degrees arithmetic,
hallucinated precision -- and leaves the model doing what it is actually good
at, which is choosing between labelled options and explaining the choice.

Anything unrecognised raises, and the DecisionLoop falls back to the rule
policy. A wrong answer from the model is a normal path, not an exception.
"""

from __future__ import annotations

import logging
from collections import deque

from backend.agent.ollama_client import OllamaClient, OllamaError
from backend.agent.prompt import SYSTEM_PROMPT, build_user_prompt
from backend.control.commands import ControlAction, SafetyLimits
from backend.decision.actions import command_for
from backend.decision.policy import Decision, PolicyTuning, observe
from backend.processing.context import BuildingContext

logger = logging.getLogger(__name__)

MAX_REASONING_CHARS = 400

# Bounded: a long run must not accumulate one float per decision forever.
LATENCY_WINDOW = 200

# The model may only choose from these. Anything else is discarded rather than
# guessed at: an unrecognised label is a signal the model misunderstood, and
# acting on a best-guess interpretation is how a bad decision reaches a building.
ALLOWED_ACTIONS = {action.value: action for action in ControlAction}


class LlmPolicy:
    """Asks a language model which action to take."""

    def __init__(
        self,
        client: OllamaClient | None = None,
        tuning: PolicyTuning | None = None,
        limits: SafetyLimits | None = None,
    ) -> None:
        self._client = client or OllamaClient()
        self._tuning = tuning or PolicyTuning()
        self._limits = limits or SafetyLimits()
        self._latencies: deque[float] = deque(maxlen=LATENCY_WINDOW)

    @property
    def name(self) -> str:
        return self._client.model

    @property
    def mean_latency_seconds(self) -> float | None:
        return sum(self._latencies) / len(self._latencies) if self._latencies else None

    @property
    def last_latency_seconds(self) -> float | None:
        return self._latencies[-1] if self._latencies else None

    def decide(self, context: BuildingContext) -> Decision:
        response = self._client.chat_json(SYSTEM_PROMPT, build_user_prompt(context))
        self._latencies.append(response.latency_seconds)

        action = _parse_action(response.payload)
        reasoning = _parse_reasoning(response.payload, action)

        return Decision(
            command=command_for(
                action=action,
                context=context,
                step_c=self._tuning.comfort_step_c,
                limits=self._limits,
                source=self.name,
                setback_lighting_fraction=self._tuning.setback_lighting_fraction,
                occupied_lighting_fraction=self._tuning.occupied_lighting_fraction,
            ),
            reasoning=reasoning,
            observations=observe(context) + (f"llm {response.latency_seconds:.1f}s",),
        )


def _parse_action(payload: dict) -> ControlAction:
    raw = payload.get("action")
    if not isinstance(raw, str):
        raise OllamaError(f"Response had no action field: {payload!r}")

    action = ALLOWED_ACTIONS.get(raw.strip().lower())
    if action is None:
        raise OllamaError(
            f"Model chose '{raw}', which is not one of {sorted(ALLOWED_ACTIONS)}"
        )
    return action


def _parse_reasoning(payload: dict, action: ControlAction) -> str:
    raw = payload.get("reasoning")
    if not isinstance(raw, str) or not raw.strip():
        # The action is valid and usable; only the explanation is missing, so
        # losing the decision over it would trade a good command for nothing.
        logger.warning("Model returned no reasoning for action %s", action.value)
        return f"Model selected {action.value} without giving a reason."

    return raw.strip()[:MAX_REASONING_CHARS]
