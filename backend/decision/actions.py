"""Turning an action into numbers.

Shared by every policy so that the rule engine and the language model are
compared on judgment alone: same action space, same arithmetic, same limits. If
each policy did its own setpoint maths, a difference in outcome could not be
attributed to a difference in reasoning.

This is also the boundary that keeps arithmetic away from the LLM. Choosing
between four labelled actions is a classification problem, which language models
handle well; computing "26.9 minus one degree, bounded to the comfort envelope"
is not, and there is no reason to ask.
"""

from __future__ import annotations

from backend.control.commands import ControlAction, ControlCommand, SafetyLimits
from backend.processing.context import BuildingContext


def shifted_setpoint(
    context: BuildingContext, delta_c: float, limits: SafetyLimits
) -> float | None:
    """Move from where the building actually is, bounded by the safety envelope."""
    current = context.mean_cooling_setpoint_c
    if current is None:
        return None
    return min(
        max(current + delta_c, limits.min_cooling_setpoint_c),
        limits.max_cooling_setpoint_c,
    )


def command_for(
    action: ControlAction,
    context: BuildingContext,
    step_c: float,
    limits: SafetyLimits,
    source: str,
    setback_lighting_fraction: float = 0.3,
    occupied_lighting_fraction: float = 1.0,
) -> ControlCommand:
    """Build the command a chosen action implies."""
    setpoint = None
    if action is ControlAction.RAISE_SETPOINT:
        setpoint = shifted_setpoint(context, step_c, limits)
    elif action is ControlAction.LOWER_SETPOINT:
        setpoint = shifted_setpoint(context, -step_c, limits)

    return ControlCommand(
        action=action,
        cooling_setpoint_c=setpoint,
        lighting_fraction=_lighting_for(
            action, context, setback_lighting_fraction, occupied_lighting_fraction
        ),
        source=source,
    )


def _lighting_for(
    action: ControlAction,
    context: BuildingContext,
    setback_fraction: float,
    occupied_fraction: float,
) -> float:
    """Lighting follows occupancy, not the chosen action.

    Dimming an empty building is not a judgment call -- nobody is there. Making
    it one of the actions forced a choice between two things that are both
    unconditionally correct when the building is empty, and a policy that
    preferred the setpoint never dimmed at all. Measured against the rule engine
    that cost 9.3 kWh of lighting in a single day.

    So occupancy decides, and the model's action only governs the setpoint. An
    explicit dim request is still honoured, which is the one case where the
    caller knows something occupancy does not.

    Control state is sticky, so this always returns a value: an occupied decision
    has to restate full output or an earlier setback would persist all day.
    """
    if action is ControlAction.REDUCE_LIGHTING:
        return setback_fraction
    return occupied_fraction if context.is_occupied else setback_fraction
