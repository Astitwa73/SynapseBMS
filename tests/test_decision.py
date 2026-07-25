import time

import pytest

from backend.control.commands import ControlAction, ControlCommand
from backend.control.store import ControlStore
from backend.decision.loop import DecisionLoop
from backend.decision.policy import (
    Decision,
    DecisionPolicy,
    PolicyTuning,
    RuleBasedPolicy,
)
from backend.processing.context import build_context
from backend.simulation.state import (
    EnergyReading,
    SensorSnapshot,
    SimulationClock,
    SimulationStateStore,
    SiteReading,
    ZoneReading,
)

POLICY = RuleBasedPolicy()
TUNING = PolicyTuning()


def snapshot(temperature=25.0, occupants=10, setpoint=24.0, humidity=50.0, hour=14):
    return SensorSnapshot(
        clock=SimulationClock(month=7, day=2, hour=hour, minute=0),
        zones=(
            ZoneReading(
                name="SPACE1-1",
                air_temperature_c=temperature,
                relative_humidity_pct=humidity,
                occupant_count=occupants,
                cooling_setpoint_c=setpoint,
                ventilation_mass_flow_kg_s=0.4,
            ),
        ),
        site=SiteReading(outdoor_air_temperature_c=31.0),
        energy=EnergyReading(building_electricity_j=9_900_000.0, plant_electricity_j=3e6),
    )


def context(**kwargs):
    return build_context(snapshot(**kwargs))


# --- the rule ladder -------------------------------------------------------


def test_empty_building_gets_setback_and_dimmed_lights():
    decision = POLICY.decide(context(occupants=0))

    assert decision.action == ControlAction.RAISE_SETPOINT
    assert decision.command.cooling_setpoint_c == TUNING.setback_setpoint_c
    assert decision.command.lighting_fraction == TUNING.setback_lighting_fraction
    assert "no occupants" in decision.reasoning.lower()


def test_setback_outranks_comfort_because_nobody_is_there():
    """Rule order is the policy: an empty hot building is a saving, not a complaint."""
    decision = POLICY.decide(context(temperature=30.0, occupants=0))
    assert decision.command.cooling_setpoint_c == TUNING.setback_setpoint_c


def test_warm_occupied_zone_lowers_the_setpoint():
    decision = POLICY.decide(context(temperature=29.0, setpoint=26.0))

    assert decision.action == ControlAction.LOWER_SETPOINT
    assert decision.command.cooling_setpoint_c < 26.0
    assert "SPACE1-1" in decision.reasoning


def test_overcooled_zone_raises_the_setpoint():
    decision = POLICY.decide(context(temperature=20.0, setpoint=22.0))

    assert decision.action == ControlAction.RAISE_SETPOINT
    assert decision.command.cooling_setpoint_c > 22.0
    assert "overcool" in decision.reasoning.lower()


def test_comfort_headroom_is_converted_into_savings():
    """23.9C at 0.5 clo is mildly cool, so there is margin to give back."""
    decision = POLICY.decide(context(temperature=23.9, setpoint=23.9))

    assert decision.action == ControlAction.RAISE_SETPOINT
    assert decision.command.cooling_setpoint_c == pytest.approx(24.4)
    assert "comfort limit" in decision.reasoning


def test_no_headroom_and_no_complaint_holds():
    """26.5C is PMV ~ +0.36: inside the band, but too close to it to harvest."""
    decision = POLICY.decide(context(temperature=26.5, setpoint=26.5))

    assert decision.action == ControlAction.HOLD
    assert not decision.command.touches_setpoints, "holding must not restate a setpoint"
    assert decision.command.lighting_fraction == 1.0, "lights stay at full while occupied"


def test_harvesting_settles_just_inside_the_comfort_band():
    """Repeatedly harvesting must converge, not drift to the setpoint ceiling."""
    setpoint = 23.9
    for _ in range(20):
        decision = POLICY.decide(context(temperature=setpoint, setpoint=setpoint))
        if decision.action == ControlAction.HOLD:
            break
        setpoint = decision.command.cooling_setpoint_c

    assert decision.action == ControlAction.HOLD
    assert setpoint < 28.0, "must stop short of the ceiling, not run to it"


def test_setpoint_targets_never_leave_the_safety_envelope():
    for temperature in range(15, 40):
        decision = POLICY.decide(context(temperature=float(temperature), setpoint=28.0))
        target = decision.command.cooling_setpoint_c
        if target is not None:
            assert 22.0 <= target <= 28.0


def test_every_decision_carries_reasoning_and_observations():
    for kwargs in ({"occupants": 0}, {"temperature": 30.0}, {"temperature": 19.0}, {}):
        decision = POLICY.decide(context(**kwargs))
        assert decision.reasoning.strip()
        assert decision.observations
        assert any("PMV" in note for note in decision.observations)


def test_rule_policy_satisfies_the_policy_interface():
    assert isinstance(POLICY, DecisionPolicy)


def test_policy_is_deterministic():
    first = POLICY.decide(context(temperature=29.0))
    second = POLICY.decide(context(temperature=29.0))
    assert first.command.cooling_setpoint_c == second.command.cooling_setpoint_c


# --- the loop --------------------------------------------------------------


class CountingPolicy:
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def decide(self, ctx) -> Decision:
        self.calls += 1
        return Decision(
            command=ControlCommand(action=ControlAction.HOLD, source=self.name),
            reasoning="counting",
        )


class BrokenPolicy:
    name = "broken"

    def decide(self, ctx) -> Decision:
        raise RuntimeError("model unavailable")


def drive_loop(policy, batches, cadence=4, fallback=None, timeout=3.0):
    """Publish `cadence` timesteps at a time, waiting for each decision.

    Publishing everything at once would not test the cadence: the loop reads the
    latest snapshot, so a burst of timesteps is one observation, not several.
    """
    state = SimulationStateStore()
    control = ControlStore()
    loop = DecisionLoop(
        policy, state, control, timesteps_per_decision=cadence, fallback=fallback
    )
    loop.start()
    try:
        for batch in range(batches):
            for _ in range(cadence):
                state.publish(snapshot())
            deadline = time.perf_counter() + timeout
            while len(loop.history()) < batch + 1 and time.perf_counter() < deadline:
                time.sleep(0.01)
    finally:
        loop.stop()
    return loop, control


def test_loop_decides_once_per_cadence_not_once_per_timestep():
    policy = CountingPolicy()
    loop, _ = drive_loop(policy, batches=3, cadence=4)

    assert len(loop.history()) == 3
    assert policy.calls == 3, "12 timesteps must produce 3 decisions, not 12"


def test_loop_acts_on_current_state_and_skips_missed_intervals():
    """Supervisory control reacts to the building now, not to a backlog.

    If the loop falls behind, replaying stale intervals would issue decisions
    for conditions that have already passed.
    """
    state = SimulationStateStore()
    control = ControlStore()
    policy = CountingPolicy()
    loop = DecisionLoop(policy, state, control, timesteps_per_decision=4)
    loop.start()
    try:
        for _ in range(40):
            state.publish(snapshot())
        deadline = time.perf_counter() + 1.0
        while not loop.history() and time.perf_counter() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
    finally:
        loop.stop()

    assert len(loop.history()) == 1, "40 buffered timesteps are one observation"


def test_loop_records_decision_command_and_context_together():
    loop, _ = drive_loop(RuleBasedPolicy(), batches=1, cadence=4)
    record = loop.latest()

    assert record is not None
    assert record.decision.reasoning
    assert record.context.zones
    assert record.clamp.command is not None


def test_loop_submits_commands_through_the_safety_layer():
    loop, control = drive_loop(RuleBasedPolicy(), batches=2, cadence=4)
    submitted, _ = control.counters
    assert submitted == len(loop.history()) == 2


def test_a_failing_policy_does_not_kill_the_loop():
    state = SimulationStateStore()
    control = ControlStore()
    loop = DecisionLoop(BrokenPolicy(), state, control, timesteps_per_decision=2)
    loop.start()
    try:
        for _ in range(2):
            state.publish(snapshot())
        deadline = time.perf_counter() + 1.0
        while loop.failure_count == 0 and time.perf_counter() < deadline:
            time.sleep(0.01)

        assert loop.failure_count > 0
        assert loop.is_running, "the loop must survive a policy that raises"

        for _ in range(2):
            state.publish(snapshot())
        time.sleep(0.2)
        assert loop.failure_count > 1, "it must keep trying after a failure"
    finally:
        loop.stop()


def test_failing_policy_falls_back_to_the_deterministic_one():
    fallback = RuleBasedPolicy()
    loop, control = drive_loop(BrokenPolicy(), batches=1, cadence=4, fallback=fallback)

    record = loop.latest()
    assert record is not None, "fallback must still produce a decision"
    assert record.decision.command.source == fallback.name
    assert loop.failure_count > 0


def test_loop_rejects_a_nonsense_cadence():
    with pytest.raises(ValueError):
        DecisionLoop(POLICY, SimulationStateStore(), ControlStore(), timesteps_per_decision=0)


# --- knowing what it cannot do ---------------------------------------------


def test_cold_zone_at_the_setpoint_ceiling_holds_instead_of_pretending():
    """Relaxing a cooling setpoint stops cooling; it cannot add heat."""
    decision = POLICY.decide(context(temperature=19.0, setpoint=28.0))

    assert decision.action == ControlAction.HOLD
    assert "maximum" in decision.reasoning
    assert "heating control" in decision.reasoning


def test_warm_zone_at_the_setpoint_floor_holds():
    decision = POLICY.decide(context(temperature=31.0, setpoint=22.0))

    assert decision.action == ControlAction.HOLD
    assert "minimum" in decision.reasoning


def test_no_decision_ever_commands_the_setpoint_it_already_has():
    for temperature in range(16, 38):
        for setpoint in (22.0, 24.0, 26.0, 28.0):
            decision = POLICY.decide(context(temperature=float(temperature), setpoint=setpoint))
            target = decision.command.cooling_setpoint_c
            if target is not None and decision.action != ControlAction.HOLD:
                assert abs(target - setpoint) > 1e-6, (temperature, setpoint)


# --- playback control ------------------------------------------------------


def test_throttling_survives_a_timestep_where_nothing_was_paused():
    """A deadline reset on every timestep silently disables pacing entirely."""
    import time as _time

    from backend.config.settings import SimulationSettings
    from backend.simulation.engine import SimulationEngine
    from backend.simulation.sensors import SensorCatalog

    engine = SimulationEngine(
        settings=SimulationSettings(seconds_per_timestep=0.05),
        catalog=SensorCatalog(zone_names=("Z",)),
        store=SimulationStateStore(),
    )
    engine._next_deadline = _time.perf_counter()

    started = _time.perf_counter()
    for _ in range(4):
        engine._throttle()
    elapsed = _time.perf_counter() - started

    assert elapsed >= 0.12, f"four 0.05s timesteps must take real time, took {elapsed:.3f}s"


def test_stepping_releases_exactly_the_requested_timesteps():
    from backend.config.settings import SimulationSettings
    from backend.simulation.engine import SimulationEngine
    from backend.simulation.sensors import SensorCatalog

    engine = SimulationEngine(
        settings=SimulationSettings(seconds_per_timestep=0.0),
        catalog=SensorCatalog(zone_names=("Z",)),
        store=SimulationStateStore(),
    )
    engine.step(2)
    assert engine.is_paused

    engine._wait_while_paused()
    engine._wait_while_paused()
    assert engine._step_budget == 0, "both steps consumed"

    engine.resume()
    assert not engine.is_paused
