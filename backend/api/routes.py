"""HTTP endpoints. Translation only -- every decision lives in BuildingService."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from backend.api.schemas import (
    BenchmarkOut,
    CommandOut,
    ConfigOut,
    DecisionOut,
    GeometryOut,
    MetricsOut,
    ReportOut,
    SetpointIn,
    StatusOut,
)
from backend.services.building_service import BuildingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Replaced by the app factory at startup; kept as a module-level holder so route
# functions can declare it as a dependency without importing the app.
_service: BuildingService | None = None


def set_service(service: BuildingService) -> None:
    global _service
    _service = service


def get_service() -> BuildingService:
    if _service is None:
        raise HTTPException(status_code=503, detail="Service is not initialised")
    return _service


@router.get("/status", response_model=StatusOut)
def read_status(service: BuildingService = Depends(get_service)) -> StatusOut:
    return StatusOut.from_domain(service.status())


@router.get("/metrics", response_model=MetricsOut)
def read_metrics(service: BuildingService = Depends(get_service)) -> MetricsOut:
    context = service.current()
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No sensor data yet; the simulation is still warming up",
        )
    return MetricsOut.from_domain(context)


@router.get("/history", response_model=list[MetricsOut])
def read_history(
    limit: int = Query(default=200, ge=1, le=2000),
    since: int | None = Query(default=None, ge=0, description="last sequence already seen"),
    service: BuildingService = Depends(get_service),
) -> list[MetricsOut]:
    contexts = (
        service.history_since(since, limit=limit)
        if since is not None
        else service.history(limit=limit)
    )
    return [MetricsOut.from_domain(context) for context in contexts]


@router.get("/decisions", response_model=list[DecisionOut])
def read_decisions(
    limit: int = Query(default=20, ge=1, le=200),
    service: BuildingService = Depends(get_service),
) -> list[DecisionOut]:
    return [DecisionOut.from_domain(record) for record in service.decisions(limit=limit)]


@router.get("/benchmark", response_model=BenchmarkOut)
def read_benchmark(service: BuildingService = Depends(get_service)) -> BenchmarkOut:
    """The measured policy comparison. 404 until the benchmark has been run."""
    payload = service.benchmark()
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No benchmark recorded. Run: python scripts/compare_policies.py",
        )
    return BenchmarkOut(**payload)


@router.get("/geometry", response_model=GeometryOut)
def read_geometry(service: BuildingService = Depends(get_service)) -> GeometryOut:
    """The building's real plan geometry. Static, so a client fetches it once."""
    geometry = service.geometry
    if geometry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Geometry is available once the building has started",
        )
    return GeometryOut.from_domain(geometry)


@router.post("/simulation/pause", response_model=StatusOut)
def pause_simulation(service: BuildingService = Depends(get_service)) -> StatusOut:
    """Hold the simulation where it is, for narrating a moment during a demo."""
    service.pause()
    return StatusOut.from_domain(service.status())


@router.post("/simulation/resume", response_model=StatusOut)
def resume_simulation(service: BuildingService = Depends(get_service)) -> StatusOut:
    service.resume()
    return StatusOut.from_domain(service.status())


@router.post("/simulation/step", response_model=StatusOut)
def step_simulation(service: BuildingService = Depends(get_service)) -> StatusOut:
    """Advance exactly one agent decision, then pause again."""
    service.step_one_decision()
    return StatusOut.from_domain(service.status())


@router.get("/report", response_model=ReportOut)
def read_report(
    limit: int = Query(default=2000, ge=1, le=5000, description="samples to summarise"),
    service: BuildingService = Depends(get_service),
) -> ReportOut:
    try:
        return ReportOut.from_domain(service.report(limit=limit))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/config", response_model=ConfigOut)
def read_config(service: BuildingService = Depends(get_service)) -> ConfigOut:
    return ConfigOut.from_domain(
        service.config, service.limits, service.tuning, service.zone_names
    )


@router.post("/control/setpoint", response_model=CommandOut)
def write_setpoint(
    payload: SetpointIn, service: BuildingService = Depends(get_service)
) -> CommandOut:
    """Manual override.

    Goes through the same ControlStore as the agent, so an operator gets exactly
    the same clamping. The response reports what was actually applied, which will
    differ from the request whenever the safety envelope intervenes.
    """
    result = service.set_cooling_setpoint(payload.cooling_setpoint_c, source=payload.source)
    if result.was_adjusted:
        logger.info("Manual setpoint adjusted: %s", "; ".join(result.adjustments))
    return CommandOut.from_domain(result)


@router.post("/control/release", status_code=status.HTTP_204_NO_CONTENT)
def release_control(service: BuildingService = Depends(get_service)) -> Response:
    """Hand the building back to its own schedule."""
    service.release_control()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
