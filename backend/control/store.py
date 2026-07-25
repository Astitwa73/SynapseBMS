"""Thread-safe hand-off of control commands from the agent to the simulation.

Mirrors SimulationStateStore in the other direction. The agent submits at its own
pace; the simulation reads the current command every timestep. Neither waits for
the other, which is what keeps a slow or failed agent from stalling the building.

Fail-safe by construction: with no command submitted, `current` returns None and
the simulation runs on its own schedule. Absence of an agent is a valid state,
not an error state.
"""

from __future__ import annotations

import logging
import threading

from backend.control.commands import ClampResult, ControlCommand, SafetyLimits, clamp

logger = logging.getLogger(__name__)


class ControlStore:
    """Holds the command currently in force, after safety clamping."""

    def __init__(self, limits: SafetyLimits | None = None) -> None:
        self._limits = limits or SafetyLimits()
        self._lock = threading.Lock()
        self._current: ControlCommand | None = None
        self._last_result: ClampResult | None = None
        self._submitted = 0
        self._adjusted = 0

    @property
    def limits(self) -> SafetyLimits:
        return self._limits

    def submit(self, command: ControlCommand) -> ClampResult:
        """Clamp a command and make it the one in force. Returns what was applied."""
        with self._lock:
            result = clamp(command, self._limits, previous=self._current)
            self._current = result.command
            self._last_result = result
            self._submitted += 1
            if result.was_adjusted:
                self._adjusted += 1

        for adjustment in result.adjustments:
            logger.warning("Command from %s adjusted: %s", command.source, adjustment)
        return result

    def current(self) -> ControlCommand | None:
        with self._lock:
            return self._current

    def last_result(self) -> ClampResult | None:
        with self._lock:
            return self._last_result

    def release(self) -> None:
        """Hand control back to the building's own schedule."""
        with self._lock:
            self._current = None
            self._last_result = None

    @property
    def counters(self) -> tuple[int, int]:
        """(commands submitted, commands the safety layer had to adjust)."""
        with self._lock:
            return (self._submitted, self._adjusted)
