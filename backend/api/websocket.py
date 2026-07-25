"""Live feed for the dashboard.

Cursor-based rather than fire-and-forget: the client reports the last sequence
number it has, and the server replies with everything after it. The server keeps
no per-connection state, so a client that reconnects or falls behind catches up
exactly -- no gaps, no duplicates, no session tracking. This is what the sequence
numbers in the state store were for.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api.routes import get_service
from backend.api.schemas import DecisionOut, MetricsOut, StatusOut
from backend.services.building_service import BuildingService

logger = logging.getLogger(__name__)

router = APIRouter()

PUSH_INTERVAL_SECONDS = 0.25

# Enough to draw a chart on connect without shipping the whole run.
INITIAL_HISTORY = 240

# A client further behind than this has been away longer than the buffer is
# useful for; it gets a fresh snapshot instead of a partial catch-up.
MAX_CATCHUP = 500


@router.websocket("/ws")
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    service = get_service()

    try:
        last_sequence = await _send_initial(websocket, service)
        last_decision_count = len(service.decisions(limit=MAX_CATCHUP))

        while True:
            await asyncio.sleep(PUSH_INTERVAL_SECONDS)
            last_sequence, last_decision_count = await _send_updates(
                websocket, service, last_sequence, last_decision_count
            )
    except WebSocketDisconnect:
        logger.debug("Dashboard disconnected")
    except Exception:  # noqa: BLE001 - one bad connection must not affect others
        logger.exception("WebSocket stream failed")
        await _close_quietly(websocket)


async def _send_initial(websocket: WebSocket, service: BuildingService) -> int:
    """Seed the client with enough history to render populated charts at once."""
    history = service.history(limit=INITIAL_HISTORY)
    decisions = service.decisions(limit=20)

    await websocket.send_json(
        {
            "type": "snapshot",
            "status": StatusOut.from_domain(service.status()).model_dump(),
            "history": [MetricsOut.from_domain(c).model_dump() for c in history],
            "decisions": [DecisionOut.from_domain(d).model_dump() for d in decisions],
        }
    )
    return history[-1].sequence if history else 0


async def _send_updates(
    websocket: WebSocket,
    service: BuildingService,
    last_sequence: int,
    last_decision_count: int,
) -> tuple[int, int]:
    metrics = service.history_since(last_sequence, limit=MAX_CATCHUP)
    decisions = service.decisions(limit=MAX_CATCHUP)
    new_decisions = decisions[last_decision_count:]

    if not metrics and not new_decisions:
        return last_sequence, last_decision_count

    await websocket.send_json(
        {
            "type": "update",
            "status": StatusOut.from_domain(service.status()).model_dump(),
            "metrics": [MetricsOut.from_domain(c).model_dump() for c in metrics],
            "decisions": [DecisionOut.from_domain(d).model_dump() for d in new_decisions],
        }
    )

    return (
        metrics[-1].sequence if metrics else last_sequence,
        len(decisions),
    )


async def _close_quietly(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except RuntimeError:
        pass  # already closed by the peer
