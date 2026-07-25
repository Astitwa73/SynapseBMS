import math

import pytest

from backend.control.actuators import ActuatorRegistry, ActuatorSpec
from backend.control.commands import (
    ControlAction,
    ControlCommand,
    SafetyLimits,
    clamp,
)
from backend.control.store import ControlStore

LIMITS = SafetyLimits()
ZONES = ("SPACE1-1", "SPACE2-1")
LIGHTS = {"SPACE1-1": "SPACE1-1 Lights 1", "SPACE2-1": "SPACE2-1 Lights 1"}


def cooling(value, **kwargs):
    return ControlCommand(cooling_setpoint_c=value, source="test", **kwargs)


# --- safety envelope -------------------------------------------------------


def test_reasonable_command_passes_through_unchanged():
    result = clamp(cooling(25.0), LIMITS)
    assert result.command.cooling_setpoint_c == 25.0
    assert not result.was_adjusted


def test_setpoint_above_maximum_is_clamped_and_reported():
    result = clamp(cooling(45.0), LIMITS)
    assert result.command.cooling_setpoint_c == LIMITS.max_cooling_setpoint_c
    assert any("above maximum" in note for note in result.adjustments)


def test_setpoint_below_minimum_is_clamped():
    result = clamp(cooling(4.0), LIMITS)
    assert result.command.cooling_setpoint_c == LIMITS.min_cooling_setpoint_c


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_rejected_not_clamped(bad):
    """min/max would happily propagate NaN, so it must be filtered first."""
    result = clamp(cooling(bad), LIMITS)
    assert result.command.cooling_setpoint_c is None
    assert any("finite" in note for note in result.adjustments)


# --- the deadband invariant, which EnergyPlus treats as fatal ---------------


def test_taking_cooling_setpoint_also_sets_a_safe_heating_setpoint():
    """Leaving the model's scheduled heating setpoint in place inverts the deadband."""
    result = clamp(cooling(22.0), LIMITS)
    assert result.command.heating_setpoint_c is not None
    assert result.command.heating_setpoint_c <= 22.0 - LIMITS.min_deadband_c


def test_inverted_setpoints_are_corrected_by_the_deadband_rule():
    """Uses overlapping bounds so the deadband rule is what does the work.

    With the default limits, cooling >= 22 and heating <= 20 already guarantee
    the gap, which would let this pass without the deadband logic existing.
    """
    overlapping = SafetyLimits(min_cooling_setpoint_c=18.0, max_heating_setpoint_c=26.0)
    command = ControlCommand(cooling_setpoint_c=23.0, heating_setpoint_c=26.0, source="test")
    result = clamp(command, overlapping)

    gap = result.command.cooling_setpoint_c - result.command.heating_setpoint_c
    assert gap >= overlapping.min_deadband_c
    assert any("deadband" in note for note in result.adjustments)


def test_deadband_holds_even_with_overlapping_bounds():
    overlapping = SafetyLimits(min_cooling_setpoint_c=18.0, max_heating_setpoint_c=26.0)
    for requested_cooling in range(10, 40):
        for requested_heating in range(10, 40):
            result = clamp(
                ControlCommand(
                    cooling_setpoint_c=float(requested_cooling),
                    heating_setpoint_c=float(requested_heating),
                ),
                overlapping,
            )
            gap = result.command.cooling_setpoint_c - result.command.heating_setpoint_c
            assert gap >= overlapping.min_deadband_c, (requested_cooling, requested_heating)


def test_deadband_holds_across_the_whole_allowed_range():
    """No reachable pair of requests may produce an inverted deadband."""
    for requested_cooling in range(0, 50):
        for requested_heating in range(0, 50):
            result = clamp(
                ControlCommand(
                    cooling_setpoint_c=float(requested_cooling),
                    heating_setpoint_c=float(requested_heating),
                ),
                LIMITS,
            )
            gap = result.command.cooling_setpoint_c - result.command.heating_setpoint_c
            assert gap >= LIMITS.min_deadband_c, (requested_cooling, requested_heating)


def test_deadband_survives_rate_limiting():
    """Rate limiting must never be able to reintroduce an inverted deadband."""
    previous = ControlCommand(cooling_setpoint_c=28.0, heating_setpoint_c=20.0)
    result = clamp(ControlCommand(cooling_setpoint_c=22.0, heating_setpoint_c=20.0), LIMITS,
                   previous=previous)
    gap = result.command.cooling_setpoint_c - result.command.heating_setpoint_c
    assert gap >= LIMITS.min_deadband_c


# --- rate limiting ---------------------------------------------------------


def test_large_jump_is_rate_limited_towards_the_target():
    previous = clamp(cooling(24.0), LIMITS).command
    result = clamp(cooling(28.0), LIMITS, previous=previous)

    assert result.command.cooling_setpoint_c == pytest.approx(
        24.0 + LIMITS.max_setpoint_change_c
    )
    assert any("per step" in note for note in result.adjustments)


def test_repeated_commands_converge_on_the_target():
    command = None
    for _ in range(20):
        command = clamp(cooling(28.0), LIMITS, previous=command).command
    assert command.cooling_setpoint_c == pytest.approx(LIMITS.max_cooling_setpoint_c)


def test_first_command_is_not_rate_limited():
    result = clamp(cooling(28.0), LIMITS, previous=None)
    assert result.command.cooling_setpoint_c == 28.0


# --- lighting --------------------------------------------------------------


def test_lighting_fraction_never_goes_below_the_floor():
    result = clamp(ControlCommand(lighting_fraction=0.0), LIMITS)
    assert result.command.lighting_fraction == LIMITS.min_lighting_fraction


# --- store -----------------------------------------------------------------


def test_store_starts_with_no_command_so_the_model_governs():
    store = ControlStore()
    assert store.current() is None


def test_store_clamps_on_submit_and_counts_adjustments():
    store = ControlStore()
    store.submit(cooling(25.0))
    store.submit(cooling(99.0))

    submitted, adjusted = store.counters
    assert (submitted, adjusted) == (2, 1)
    assert store.current().cooling_setpoint_c <= LIMITS.max_cooling_setpoint_c


def test_store_rate_limits_against_the_previous_command():
    store = ControlStore()
    store.submit(cooling(24.0))
    store.submit(cooling(28.0))
    assert store.current().cooling_setpoint_c == pytest.approx(
        24.0 + LIMITS.max_setpoint_change_c
    )


def test_release_returns_control_to_the_building():
    store = ControlStore()
    store.submit(cooling(25.0))
    store.release()
    assert store.current() is None


# --- actuator registry -----------------------------------------------------


class FakeExchange:
    def __init__(self, unavailable: set[str] | None = None) -> None:
        self.unavailable = unavailable or set()
        self.writes: list[tuple[int, float]] = []
        self.resets: list[int] = []
        self._next = 0

    def get_actuator_handle(self, state, component_type, control_type, key):
        if control_type in self.unavailable:
            return -1
        self._next += 1
        return self._next

    def set_actuator_value(self, state, handle, value):
        self.writes.append((handle, value))

    def reset_actuator(self, state, handle):
        self.resets.append(handle)


def make_registry(exchange):
    registry = ActuatorRegistry(exchange, ZONES, LIGHTS)
    registry.resolve_handles(state=None)
    return registry


def test_registry_covers_both_setpoints_and_lights_per_zone():
    registry = ActuatorRegistry(FakeExchange(), ZONES, LIGHTS)
    specs = registry.specs()
    assert len(specs) == len(ZONES) * 3
    assert ActuatorSpec("Zone Temperature Control", "Cooling Setpoint", "SPACE1-1") in specs


def test_applying_setpoints_writes_every_zone():
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.apply(state=None, command=clamp(cooling(25.0), LIMITS).command)

    # Heating is capped at max_heating_setpoint_c (20.0), which is tighter than
    # the deadband would require, so taking control widens the band.
    written = {value for _, value in exchange.writes}
    assert written == {25.0, 20.0}
    assert len(exchange.writes) == len(ZONES) * 2


def test_no_command_releases_control_instead_of_latching():
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.apply(state=None, command=None)

    assert exchange.writes == []
    assert exchange.resets, "actuators must be handed back, not left overridden"


def test_missing_actuator_is_skipped_without_failing():
    exchange = FakeExchange(unavailable={"Heating Setpoint"})
    registry = make_registry(exchange)
    registry.apply(state=None, command=clamp(cooling(25.0), LIMITS).command)

    assert all(value == 25.0 for _, value in exchange.writes)


def test_lighting_scales_the_observed_baseline():
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.observe_lighting({"SPACE1-1": 1000.0, "SPACE2-1": 500.0})
    registry.apply(
        state=None,
        command=ControlCommand(action=ControlAction.REDUCE_LIGHTING, lighting_fraction=0.6),
    )

    assert {value for _, value in exchange.writes} == {600.0, 300.0}


def test_lighting_baseline_ignores_our_own_output():
    """Refreshing the baseline while dimming would feed the override back in."""
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.observe_lighting({"SPACE1-1": 1000.0, "SPACE2-1": 1000.0})
    dim = ControlCommand(lighting_fraction=0.5)

    registry.apply(state=None, command=dim)
    registry.observe_lighting({"SPACE1-1": 500.0, "SPACE2-1": 500.0})
    exchange.writes.clear()
    registry.apply(state=None, command=dim)

    assert {value for _, value in exchange.writes} == {500.0}, "baseline must not decay"


def test_lighting_without_a_baseline_is_skipped():
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.apply(state=None, command=ControlCommand(lighting_fraction=0.5))
    assert exchange.writes == []


# --- control is state, not a stream of one-shot messages -------------------


def test_holding_carries_the_setpoint_forward_instead_of_blanking_it():
    """A hold that cleared the channels would hand the building back mid-demo."""
    store = ControlStore()
    store.submit(cooling(26.0))
    store.submit(ControlCommand(action=ControlAction.HOLD, source="test"))

    assert store.current().cooling_setpoint_c is not None
    assert store.current().heating_setpoint_c is not None


def test_explicit_values_still_override_the_carried_forward_ones():
    store = ControlStore()
    store.submit(ControlCommand(cooling_setpoint_c=26.0, lighting_fraction=0.3))
    store.submit(ControlCommand(lighting_fraction=1.0))

    assert store.current().lighting_fraction == 1.0
    assert store.current().cooling_setpoint_c is not None


def test_a_noop_command_no_longer_releases_the_actuators():
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.apply(state=None, command=clamp(cooling(25.0), LIMITS).command)
    exchange.resets.clear()

    registry.apply(state=None, command=ControlCommand(action=ControlAction.HOLD))
    assert exchange.resets == [], "holding must not hand control back"


def test_full_lighting_releases_the_lights_but_keeps_setpoints():
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.observe_lighting({"SPACE1-1": 1000.0, "SPACE2-1": 1000.0})
    registry.apply(state=None, command=ControlCommand(lighting_fraction=0.5))
    exchange.resets.clear()

    registry.apply(
        state=None,
        command=ControlCommand(cooling_setpoint_c=25.0, heating_setpoint_c=20.0,
                               lighting_fraction=1.0),
    )

    assert len(exchange.resets) == len(ZONES), "only the lights are handed back"
    assert 25.0 in {value for _, value in exchange.writes}


def test_baseline_refreshes_once_lighting_is_released():
    exchange = FakeExchange()
    registry = make_registry(exchange)
    registry.observe_lighting({"SPACE1-1": 1000.0, "SPACE2-1": 1000.0})
    registry.apply(state=None, command=ControlCommand(lighting_fraction=0.5))

    registry.apply(state=None, command=ControlCommand(lighting_fraction=1.0))
    registry.observe_lighting({"SPACE1-1": 2000.0, "SPACE2-1": 2000.0})
    exchange.writes.clear()
    registry.apply(state=None, command=ControlCommand(lighting_fraction=0.5))

    assert {value for _, value in exchange.writes} == {1000.0}, "must use the new baseline"
