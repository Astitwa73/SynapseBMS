"""Prompt construction for the building agent.

Written for an 8B model, which means short and structured. Every line either
defines the output contract or supplies a fact the decision depends on; anything
else dilutes attention and costs latency.

The action descriptions carry the operating policy. This is where domain
knowledge enters the system, and keeping it in one readable string is
deliberate -- it is the part a building engineer should be able to review
without reading Python.
"""

from __future__ import annotations

from backend.processing.context import BuildingContext

SYSTEM_PROMPT = """\
You are the supervisory controller for a commercial office building. Each hour \
you review the building and choose exactly one action.

PMV measures how occupants feel:
- NEGATIVE PMV means occupants feel COLD. The building is being over-cooled.
- POSITIVE PMV means occupants feel WARM. The building needs more cooling.
- Comfortable is -0.5 to +0.5.

The cooling setpoint is the temperature the building cools down to. Moving it \
changes the room the same way:
- RAISING the setpoint makes the room WARMER and uses LESS energy.
- LOWERING the setpoint makes the room COOLER and uses MORE energy.

Actions:
- raise_setpoint: setpoint up 1C. Room gets warmer, saves energy.
- lower_setpoint: setpoint down 1C. Room gets cooler, costs energy.
- reduce_lighting: dim the lights to 30%.
- hold: change nothing.

How to choose:
1. Nobody present? Choose raise_setpoint or reduce_lighting. An empty building \
has no comfort cost, so relax it aggressively.
2. Occupants too warm (PMV above +0.5)? Choose lower_setpoint.
3. Occupants too cold (PMV below -0.5)? The building is over-cooled. Choose \
raise_setpoint. Do NOT choose lower_setpoint, that would make them colder.
4. Comfortable but cool (PMV below 0)? Choose raise_setpoint to save energy \
while staying comfortable.
5. Comfortable and slightly warm (PMV 0 to +0.5)? Choose hold.

Energy is only saved by raising the setpoint. Never choose lower_setpoint \
unless someone is genuinely too warm.

Reply with JSON only, exactly these two fields:
{"action": "raise_setpoint|lower_setpoint|reduce_lighting|hold", "reasoning": "one sentence, under 30 words"}\
"""


def build_user_prompt(context: BuildingContext) -> str:
    """Render the building state as compact, labelled facts."""
    lines = [
        f"Time: {context.clock.label}",
        f"Occupancy: {context.total_occupancy:.0f} people",
    ]

    if context.mean_pmv is not None:
        lines.append(f"Mean comfort PMV: {context.mean_pmv:+.2f}")

    worst = context.worst_zone
    if worst is not None and worst.pmv is not None:
        lines.append(
            f"Least comfortable zone: {worst.name} at PMV {worst.pmv:+.2f}"
            f" ({worst.comfort.value if worst.comfort else 'unknown'})"
        )

    if context.mean_cooling_setpoint_c is not None:
        lines.append(f"Cooling setpoint: {context.mean_cooling_setpoint_c:.1f} C")
    if context.site.outdoor_air_temperature_c is not None:
        lines.append(f"Outdoor temperature: {context.site.outdoor_air_temperature_c:.1f} C")
    if context.total_power_kw is not None:
        lines.append(f"Electrical load: {context.total_power_kw:.1f} kW")
    if context.peak_co2_ppm is not None:
        lines.append(f"Peak zone CO2: {context.peak_co2_ppm:.0f} ppm")

    lines.append("\nChoose one action.")
    return "\n".join(lines)
