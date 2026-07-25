"""The application core: everything the system can do, with no transport attached.

This module never imports FastAPI and does not know what a request is. That is
what lets the REST API and the MCP server be two adapters over one
implementation rather than two implementations of the same thing.

It owns the lifecycle of the simulation and the decision loop, so that starting
the building is one call from wherever it needs to happen.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from backend.agent.llm_policy import LlmPolicy
from backend.agent.ollama_client import OllamaClient, OllamaError, OllamaSettings
from backend.config.settings import (
    DEFAULT_MODEL_NAME,
    MODELS_DIR,
    CalendarDay,
    SimulationSettings,
)
from backend.control.commands import ClampResult, ControlAction, ControlCommand, SafetyLimits
from backend.control.store import ControlStore
from backend.decision.loop import DecisionLoop, DecisionRecord
from backend.decision.policy import DecisionPolicy, PolicyTuning, RuleBasedPolicy
from backend.processing.context import BuildingContext, build_context
from backend.simulation.engine import SimulationEngine
from backend.simulation.idf import controllable_zone_names, lights_by_zone
from backend.simulation.sensors import SensorCatalog
from backend.simulation.state import SensorSnapshot, SimulationStateStore

logger = logging.getLogger(__name__)

MANUAL_SOURCE = "operator"


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """How to run the building. One object so an adapter can report it verbatim."""

    model_name: str = DEFAULT_MODEL_NAME
    policy: str = "rule"
    llm_model: str = "llama3"
    seconds_per_timestep: float = 0.4
    timesteps_per_decision: int = 12
    start_date: CalendarDay = CalendarDay(month=7, day=2)
    history_limit: int = 5000

    @property
    def model_path(self) -> Path:
        return MODELS_DIR / self.model_name


@dataclass(frozen=True, slots=True)
class ServiceStatus:
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


class BuildingService:
    """Owns the running building and answers questions about it."""

    def __init__(self, config: ServiceConfig | None = None) -> None:
        self._config = config or ServiceConfig()
        self._limits = SafetyLimits()
        self._tuning = PolicyTuning()

        self._state = SimulationStateStore(history_limit=self._config.history_limit)
        self._control = ControlStore(limits=self._limits)
        self._rules = RuleBasedPolicy(tuning=self._tuning, limits=self._limits)

        self._policy: DecisionPolicy = self._rules
        self._llm: LlmPolicy | None = None
        self._engine: SimulationEngine | None = None
        self._loop: DecisionLoop | None = None
        self._lock = threading.Lock()
        self._zone_names: tuple[str, ...] = ()

        # A startup failure must be visible through the API. Otherwise the server
        # comes up, reports no error, and simply never produces data.
        self._startup_error: str | None = None

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the simulation and the agent. Idempotent from the caller's view."""
        with self._lock:
            if self._engine is not None:
                raise RuntimeError("Building is already running")

            model_path = self._config.model_path
            if not model_path.is_file():
                raise FileNotFoundError(
                    f"{model_path} not found. Run: python scripts/prepare_model.py"
                )

            self._zone_names = tuple(controllable_zone_names(model_path))
            self._policy, fallback = self._build_policy()

            self._engine = SimulationEngine(
                settings=SimulationSettings(
                    model_path=model_path,
                    seconds_per_timestep=self._config.seconds_per_timestep,
                    report_from=self._config.start_date,
                ),
                catalog=SensorCatalog(zone_names=self._zone_names),
                store=self._state,
                control=self._control,
                lights_by_zone=lights_by_zone(model_path),
            )
            self._loop = DecisionLoop(
                policy=self._policy,
                state=self._state,
                control=self._control,
                timesteps_per_decision=self._config.timesteps_per_decision,
                fallback=fallback,
            )

            self._startup_error = None
            self._engine.start()
            self._loop.start()
            logger.info("Building started with policy %s", self._policy.name)

    def record_startup_failure(self, message: str) -> None:
        self._startup_error = message

    def stop(self) -> None:
        with self._lock:
            if self._loop is not None:
                self._loop.stop()
            if self._engine is not None:
                self._engine.stop()
            self._loop = None
            self._engine = None
            logger.info("Building stopped")

    def _build_policy(self) -> tuple[DecisionPolicy, DecisionPolicy | None]:
        """Return (policy, fallback). The LLM always gets a deterministic fallback."""
        if self._config.policy != "llm":
            return self._rules, None

        client = OllamaClient(OllamaSettings(model=self._config.llm_model))
        client.check_ready()  # fail at startup, not on the first decision of a demo
        self._llm = LlmPolicy(client=client, tuning=self._tuning, limits=self._limits)
        return self._llm, self._rules

    # --- reading -----------------------------------------------------------

    @property
    def config(self) -> ServiceConfig:
        return self._config

    @property
    def limits(self) -> SafetyLimits:
        return self._limits

    @property
    def tuning(self) -> PolicyTuning:
        return self._tuning

    @property
    def zone_names(self) -> tuple[str, ...]:
        return self._zone_names

    def status(self) -> ServiceStatus:
        submitted, adjusted = self._control.counters
        engine = self._engine
        loop = self._loop

        return ServiceStatus(
            simulation_running=engine.is_running if engine else False,
            agent_running=loop.is_running if loop else False,
            timesteps_published=self._state.published_count,
            decisions_taken=len(loop.history()) if loop else 0,
            policy_failures=loop.failure_count if loop else 0,
            commands_submitted=submitted,
            commands_adjusted=adjusted,
            policy_name=self._policy.name,
            llm_latency_seconds=self._llm.mean_latency_seconds if self._llm else None,
            error=self._startup_error or (engine.status().error if engine else None),
        )

    def current(self) -> BuildingContext | None:
        snapshot = self._state.latest()
        return self._to_context(snapshot) if snapshot else None

    def history(self, limit: int = 200) -> tuple[BuildingContext, ...]:
        return tuple(self._to_context(s) for s in self._state.history(limit=limit))

    def history_since(self, sequence: int, limit: int = 500) -> tuple[BuildingContext, ...]:
        """Everything published after `sequence`, for a client catching up."""
        snapshots = self._state.history_since(sequence)[-limit:]
        return tuple(self._to_context(s) for s in snapshots)

    def decisions(self, limit: int = 20) -> tuple[DecisionRecord, ...]:
        return self._loop.history(limit=limit) if self._loop else ()

    def latest_decision(self) -> DecisionRecord | None:
        return self._loop.latest() if self._loop else None

    def _to_context(self, snapshot: SensorSnapshot) -> BuildingContext:
        return build_context(snapshot)

    # --- writing -----------------------------------------------------------

    def set_cooling_setpoint(self, setpoint_c: float, source: str = MANUAL_SOURCE) -> ClampResult:
        """Submit a manual setpoint.

        Deliberately routed through the same ControlStore the agent uses, so an
        operator, an MCP client and the language model are all subject to
        identical clamping. A second write path would be a second place for the
        safety envelope to be forgotten.
        """
        return self._control.submit(
            ControlCommand(
                action=ControlAction.LOWER_SETPOINT,
                cooling_setpoint_c=setpoint_c,
                source=source,
            )
        )

    def release_control(self) -> None:
        """Hand the building back to its own schedule."""
        self._control.release()

    def current_command(self) -> ControlCommand | None:
        return self._control.current()

    def last_clamp(self) -> ClampResult | None:
        return self._control.last_result()


def check_llm_available(model: str) -> str | None:
    """Return an error message if the model is unusable, otherwise None."""
    try:
        OllamaClient(OllamaSettings(model=model)).check_ready()
    except OllamaError as exc:
        return str(exc)
    return None
