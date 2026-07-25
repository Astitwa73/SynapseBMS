"""FastAPI application factory.

The simulation starts with the app and stops with it, via the lifespan hook,
so there is one lifecycle to reason about rather than a server and a separate
building that have to be kept in step.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import routes, websocket
from backend.config.logging import configure_logging
from backend.services.building_service import BuildingService, ServiceConfig

logger = logging.getLogger(__name__)

# The dashboard is served by Vite in development, on its own origin.
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def create_app(config: ServiceConfig | None = None, autostart: bool = True) -> FastAPI:
    service = BuildingService(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        routes.set_service(service)
        if autostart:
            try:
                service.start()
            except Exception as exc:  # noqa: BLE001 - the API must come up to report it
                service.record_startup_failure(f"{type(exc).__name__}: {exc}")
                logger.exception("Could not start the building; API is up but idle")
        yield
        service.stop()

    app = FastAPI(
        title="Autonomous Building Management System",
        description=(
            "Live EnergyPlus building simulation under AI supervisory control. "
            "Every command passes a safety envelope before reaching an actuator."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEV_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes.router)
    app.include_router(websocket.router)

    @app.get("/health")
    def health() -> dict:
        """Liveness only: reports that the API is up, not that the building is."""
        return {"status": "ok"}

    return app


configure_logging()
app = create_app()
