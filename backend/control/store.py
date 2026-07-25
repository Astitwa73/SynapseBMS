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

from dataclasses import replace

from backend.control.commands import ClampResult, ControlCommand, SafetyLimits, clamp

logger = logging.getLogger(__name__)

_STICKY_FIELDS = ("cooling_setpoint_c", "heating_setpoint_c", "lighting_fraction")


def _carry_forward(command: ControlCommand, current: ControlCommand | None) -> ControlCommand:
    """Fill unset channels from the command currently in force."""
    if current is None:
        return command

    inherited = {
        field: getattr(current, field)
        for field in _STICKY_FIELDS
        if getattr(command, field) is None
    }
    return replace(command, **inherited) if inherited else command


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
        """Clamp a command and make it the one in force. Returns what was applied.

        The store holds the *current state of control*, not a stream of one-shot
        messages: a field left unset carries forward from the command in force.
        Otherwise a decision to hold would blank every channel and hand the
        building back to its own schedule.
        """
        with self._lock:
            merged = _carry_forward(command, self._current)
            result = clamp(merged, self._limits, previous=self._current)
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
