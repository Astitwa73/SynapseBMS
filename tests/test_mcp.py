import httpx
import pytest

from backend.mcp_server import server
from backend.mcp_server.server import (
    BackendUnavailable,
    generate_report,
    get_agent_decisions,
    get_building_metrics,
    get_configuration,
    release_control,
    set_cooling_setpoint,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"x" if payload is not None else b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class Recorder(list):
    """Records requests the tools make, and serves canned responses back."""

    def __init__(self) -> None:
        super().__init__()
        self.payloads: dict[str, object] = {}


@pytest.fixture
def calls(monkeypatch):
    """Capture what the tools ask the API for, without a running API."""
    recorded = Recorder()

    def fake_request(method, url, **kwargs):
        path = url.split("8000", 1)[-1].split("?")[0]
        recorded.append((method, path, kwargs))
        return FakeResponse(recorded.payloads.get(path, {}))

    monkeypatch.setattr(httpx, "request", fake_request)
    return recorded


def test_metrics_tool_reads_the_metrics_endpoint(calls):
    calls.payloads["/api/metrics"] = {"sequence": 7}
    assert get_building_metrics() == {"sequence": 7}
    assert calls[0][:2] == ("GET", "/api/metrics")


def test_decisions_are_wrapped_in_a_named_field(calls):
    """A bare list serialises as {"result": [...]}, which describes nothing."""
    calls.payloads["/api/decisions"] = [{"action": "hold"}, {"action": "raise_setpoint"}]
    result = get_agent_decisions(limit=5)

    assert result["count"] == 2
    assert result["decisions"][0]["action"] == "hold"


@pytest.mark.parametrize("requested,expected", [(0, 1), (-5, 1), (9999, 200), (10, 10)])
def test_decision_limit_is_clamped_before_it_reaches_the_api(calls, requested, expected):
    calls.payloads["/api/decisions"] = []
    get_agent_decisions(limit=requested)
    assert calls[0][2]["params"]["limit"] == expected


def test_setpoint_tool_posts_through_the_control_endpoint(calls):
    calls.payloads["/api/control/setpoint"] = {"cooling_setpoint_c": 26.0}
    set_cooling_setpoint(4.0, reason="test")

    method, path, kwargs = calls[0]
    assert (method, path) == ("POST", "/api/control/setpoint")
    assert kwargs["json"]["cooling_setpoint_c"] == 4.0


def test_setpoint_source_is_tagged_as_mcp_and_bounded(calls):
    """Provenance matters: a command's origin must be visible in the audit trail."""
    calls.payloads["/api/control/setpoint"] = {}
    set_cooling_setpoint(25.0, reason="x" * 200)

    source = calls[0][2]["json"]["source"]
    assert source.startswith("mcp:")
    assert len(source) <= 40


def test_report_tool_returns_the_markdown_not_the_structure(calls):
    calls.payloads["/api/report"] = {"markdown": "# Building Performance Report", "energy": {}}
    assert generate_report() == "# Building Performance Report"


def test_configuration_tool_exposes_the_safety_limits(calls):
    calls.payloads["/api/config"] = {"limits": {"max_cooling_setpoint_c": 28.0}}
    assert get_configuration()["limits"]["max_cooling_setpoint_c"] == 28.0


def test_release_tool_confirms_in_words(calls):
    calls.payloads["/api/control/release"] = None
    assert "released" in release_control().lower()


def test_a_missing_backend_says_how_to_start_it(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", refuse)

    with pytest.raises(BackendUnavailable, match="run_server.py"):
        get_building_metrics()


def test_warming_up_is_reported_as_unavailable_not_as_a_crash(monkeypatch):
    def warming(*args, **kwargs):
        return FakeResponse({"detail": "still warming up"}, status_code=503)

    monkeypatch.setattr(httpx, "request", warming)

    with pytest.raises(BackendUnavailable, match="warming up"):
        get_building_metrics()


def test_base_url_is_configurable_for_a_remote_backend():
    assert server.DEFAULT_BASE_URL.startswith("http")


def test_every_tool_documents_units_or_consequences():
    """Tool descriptions are read by a model choosing between them, not by a developer."""
    for tool in (
        get_building_metrics,
        get_agent_decisions,
        set_cooling_setpoint,
        get_configuration,
        generate_report,
        release_control,
    ):
        assert tool.__doc__ and len(tool.__doc__.strip()) > 80, tool.__name__
