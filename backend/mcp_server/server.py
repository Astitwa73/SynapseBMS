"""MCP server exposing the building to any MCP client.

An adapter, not a second brain. Every tool calls the same HTTP endpoints the
dashboard uses, so an MCP client has exactly the authority an operator has and
no more -- in particular, setpoint writes go through the same ControlStore and
are clamped identically. There is no direct access to the stores from here,
because a second write path would be a second place to forget the safety
envelope.

Runs over stdio and talks to a running backend, which is what lets it be
registered in a desktop MCP client:

    python scripts/run_mcp_server.py

Tool descriptions are written for a language model rather than a developer: they
state units, ranges and consequences, because that is what the caller needs to
choose correctly.
"""

from __future__ import annotations

import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = os.environ.get("BMS_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_SECONDS = 15.0

mcp = FastMCP("building-management")


class BackendUnavailable(RuntimeError):
    """The building API is not reachable."""


def _get(path: str, **params) -> dict | list:
    return _request("GET", path, params=params or None)


def _post(path: str, payload: dict) -> dict:
    return _request("POST", path, json=payload)


def _request(method: str, path: str, **kwargs) -> dict | list:
    try:
        response = httpx.request(
            method, f"{DEFAULT_BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS, **kwargs
        )
    except httpx.HTTPError as exc:
        raise BackendUnavailable(
            f"Cannot reach the building API at {DEFAULT_BASE_URL}. "
            "Start it with: python scripts/run_server.py"
        ) from exc

    if response.status_code == 503:
        detail = response.json().get("detail", "service unavailable")
        raise BackendUnavailable(detail)

    response.raise_for_status()
    return response.json() if response.content else {}


@mcp.tool()
def get_building_metrics() -> dict:
    """Read the building's current state.

    Returns per-zone air temperature (C), relative humidity (%), occupancy, PMV
    thermal comfort (-3 cold to +3 hot, comfortable between -0.5 and +0.5),
    estimated CO2 (ppm), and the cooling setpoint, plus an electrical power
    breakdown in kW and a summary of the whole building.
    """
    return _get("/api/metrics")


@mcp.tool()
def get_agent_decisions(limit: int = 10) -> dict:
    """Read recent decisions taken by the autonomous control agent.

    Each entry gives the action chosen, the reasoning behind it, the observations
    it was based on, and any adjustments the safety layer made to the resulting
    command. Use this to explain why the building is in its current state.
    Decisions are returned oldest first.
    """
    # Wrapped in a named field rather than returned bare: a top-level list gets
    # serialised as {"result": [...]}, which tells a reader nothing about what
    # it is looking at.
    decisions = _get("/api/decisions", limit=max(1, min(limit, 200)))
    return {"decisions": decisions, "count": len(decisions)}


@mcp.tool()
def set_cooling_setpoint(setpoint_celsius: float, reason: str = "") -> dict:
    """Request a new cooling setpoint for the building, in degrees Celsius.

    The request is advisory. A safety layer clamps it to the building's comfort
    envelope, enforces a minimum gap between heating and cooling setpoints, and
    limits how far the setpoint may move in a single step. The response reports
    the value actually applied and lists every adjustment made, so always read
    `cooling_setpoint_c` back rather than assuming the request took effect.

    Typical useful range is 22 to 28 C. Higher values save cooling energy;
    lower values cool the building further at greater energy cost.
    """
    return _post(
        "/api/control/setpoint",
        {"cooling_setpoint_c": setpoint_celsius, "source": f"mcp:{reason or 'unspecified'}"[:40]},
    )


@mcp.tool()
def get_configuration() -> dict:
    """Read the building configuration and the safety limits commands are held to.

    Includes the zones under control, the decision policy in use, and the exact
    setpoint bounds, deadband and rate limit that constrain every command.
    """
    return _get("/api/config")


@mcp.tool()
def generate_report(samples: int = 2000) -> str:
    """Generate a performance report for the run so far, as markdown.

    Covers energy by end use, comfort and air quality statistics, what the agent
    did, and an estimated saving. The saving is an estimate and the report states
    the basis it was derived from; quote it with that caveat attached.
    """
    report = _get("/api/report", limit=max(1, min(samples, 5000)))
    return report["markdown"]


@mcp.tool()
def release_control() -> str:
    """Hand the building back to its own schedule, ending agent and manual overrides.

    Use this to return to baseline operation. The simulation keeps running.
    """
    _post("/api/control/release", {})
    return "Control released; the building is running on its own schedule."


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
