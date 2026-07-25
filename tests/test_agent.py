import pytest

from backend.agent.llm_policy import LlmPolicy
from backend.agent.ollama_client import LlmResponse, OllamaError
from backend.agent.prompt import SYSTEM_PROMPT, build_user_prompt
from backend.control.commands import ControlAction
from backend.decision.actions import command_for, shifted_setpoint
from backend.control.commands import SafetyLimits
from backend.decision.policy import DecisionPolicy
from backend.processing.context import build_context
from backend.simulation.state import (
    EnergyReading,
    SensorSnapshot,
    SimulationClock,
    SiteReading,
    ZoneReading,
)

LIMITS = SafetyLimits()


def context(temperature=25.0, occupants=10, setpoint=25.0):
    return build_context(
        SensorSnapshot(
            clock=SimulationClock(month=7, day=2, hour=14, minute=0),
            zones=(
                ZoneReading(
                    name="SPACE1-1",
                    air_temperature_c=temperature,
                    relative_humidity_pct=50.0,
                    occupant_count=occupants,
                    cooling_setpoint_c=setpoint,
                    ventilation_mass_flow_kg_s=0.4,
                ),
            ),
            site=SiteReading(outdoor_air_temperature_c=31.0),
            energy=EnergyReading(building_electricity_j=9.9e6, plant_electricity_j=3e6),
        )
    )


class FakeClient:
    """Stands in for Ollama. `payload` is whatever the model 'returned'."""

    model = "fake-model"

    def __init__(self, payload, latency=0.4):
        self.payload = payload
        self.latency = latency
        self.calls: list[tuple[str, str]] = []

    def chat_json(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if isinstance(self.payload, Exception):
            raise self.payload
        return LlmResponse(payload=self.payload, latency_seconds=self.latency)


def policy_with(payload):
    return LlmPolicy(client=FakeClient(payload))


# --- shared arithmetic -----------------------------------------------------


def test_both_policies_share_the_same_setpoint_arithmetic():
    ctx = context(setpoint=25.0)
    assert shifted_setpoint(ctx, 1.0, LIMITS) == 26.0
    assert shifted_setpoint(ctx, -1.0, LIMITS) == 24.0


def test_shifted_setpoint_respects_the_safety_envelope():
    assert shifted_setpoint(context(setpoint=27.5), 5.0, LIMITS) == LIMITS.max_cooling_setpoint_c
    assert shifted_setpoint(context(setpoint=22.5), -5.0, LIMITS) == LIMITS.min_cooling_setpoint_c


def test_hold_commands_no_setpoint():
    command = command_for(ControlAction.HOLD, context(), 1.0, LIMITS, "test")
    assert command.cooling_setpoint_c is None


def test_occupied_actions_restore_full_lighting():
    """Control state is sticky, so an earlier dim would otherwise persist."""
    command = command_for(ControlAction.HOLD, context(occupants=10), 1.0, LIMITS, "test")
    assert command.lighting_fraction == 1.0


def test_empty_building_dims_whatever_action_was_chosen():
    """Lighting follows occupancy: an empty building is dimmed either way."""
    for action in (ControlAction.RAISE_SETPOINT, ControlAction.HOLD):
        command = command_for(action, context(occupants=0), 1.0, LIMITS, "t")
        assert command.lighting_fraction == 0.3, action


def test_reduce_lighting_dims():
    command = command_for(ControlAction.REDUCE_LIGHTING, context(occupants=0), 1.0, LIMITS, "t")
    assert command.lighting_fraction == 0.3


# --- the model never produces a number -------------------------------------


def test_model_choosing_an_action_produces_a_computed_setpoint():
    decision = policy_with({"action": "lower_setpoint", "reasoning": "zone is warm"}).decide(
        context(setpoint=26.0)
    )

    assert decision.action == ControlAction.LOWER_SETPOINT
    assert decision.command.cooling_setpoint_c == 25.0, "arithmetic is ours, not the model's"
    assert decision.reasoning == "zone is warm"


def test_a_setpoint_in_the_model_response_is_ignored():
    """The model has no channel for numbers, so a stray one cannot reach the building."""
    decision = policy_with(
        {"action": "hold", "reasoning": "fine", "cooling_setpoint_c": 4.0}
    ).decide(context(setpoint=26.0))

    assert decision.command.cooling_setpoint_c is None


# --- malformed responses ---------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"reasoning": "no action given"},
        {"action": "turn_off_the_building", "reasoning": "creative"},
        {"action": 42, "reasoning": "wrong type"},
        {"action": None, "reasoning": "null"},
    ],
)
def test_unusable_responses_raise_so_the_loop_can_fall_back(payload):
    with pytest.raises(OllamaError):
        policy_with(payload).decide(context())


def test_action_parsing_tolerates_case_and_whitespace():
    decision = policy_with({"action": "  RAISE_SETPOINT ", "reasoning": "ok"}).decide(context())
    assert decision.action == ControlAction.RAISE_SETPOINT


def test_missing_reasoning_keeps_the_decision_rather_than_discarding_it():
    decision = policy_with({"action": "hold"}).decide(context())

    assert decision.action == ControlAction.HOLD
    assert "without giving a reason" in decision.reasoning


def test_overlong_reasoning_is_truncated():
    decision = policy_with({"action": "hold", "reasoning": "x" * 5000}).decide(context())
    assert len(decision.reasoning) <= 400


def test_client_failure_propagates_for_the_loop_to_handle():
    policy = LlmPolicy(client=FakeClient(OllamaError("model did not answer within 25s")))
    with pytest.raises(OllamaError):
        policy.decide(context())


# --- interface and instrumentation -----------------------------------------


def test_llm_policy_satisfies_the_policy_interface():
    assert isinstance(policy_with({"action": "hold", "reasoning": "ok"}), DecisionPolicy)


def test_latency_is_recorded_for_the_dashboard():
    policy = policy_with({"action": "hold", "reasoning": "ok"})
    policy.decide(context())
    policy.decide(context())

    assert policy.last_latency_seconds == pytest.approx(0.4)
    assert policy.mean_latency_seconds == pytest.approx(0.4)


def test_decision_observations_include_model_latency():
    decision = policy_with({"action": "hold", "reasoning": "ok"}).decide(context())
    assert any("llm" in note for note in decision.observations)


# --- prompt ----------------------------------------------------------------


def test_prompt_states_every_allowed_action():
    for action in ControlAction:
        assert action.value in SYSTEM_PROMPT


def test_prompt_carries_the_facts_a_decision_depends_on():
    prompt = build_user_prompt(context(temperature=27.0, occupants=52, setpoint=24.0))

    for expected in ("Time:", "Occupancy: 52", "PMV", "Cooling setpoint: 24.0", "CO2"):
        assert expected in prompt


def test_prompt_omits_sensors_that_are_unavailable():
    empty = build_context(
        SensorSnapshot(
            clock=SimulationClock(month=7, day=2, hour=3, minute=0),
            zones=(ZoneReading(name="DARK"),),
            site=SiteReading(),
            energy=EnergyReading(),
        )
    )
    prompt = build_user_prompt(empty)

    assert "PMV" not in prompt, "a missing sensor must not become a blank or zero"
    assert "Time:" in prompt


def test_prompt_stays_small_enough_for_an_8b_model():
    prompt = SYSTEM_PROMPT + build_user_prompt(context())
    assert len(prompt) < 2000, "long prompts dilute attention and cost latency"
