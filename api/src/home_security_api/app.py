from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from home_security_api.db import open_readonly
from home_security_api.routers import (
    addresses,
    meta,
    observations,
    scanners,
    search,
    stats,
    wifi,
)
from home_security_api.settings import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # Validate the archive is openable at startup (fail fast). Each request
    # opens its own short-lived read-only connection via
    # dependencies.get_connection, so nothing concurrency-sensitive is shared.
    open_readonly(settings.archive_path).close()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Home Security API",
        version="0.1.0",
        summary=("Read-only HTTP API over the consolidated home-security archive."),
        lifespan=_lifespan,
    )
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    app.include_router(meta.router)
    app.include_router(scanners.router)
    app.include_router(addresses.router)
    app.include_router(observations.router)
    app.include_router(stats.router)
    app.include_router(search.router)
    app.include_router(wifi.router)
    return app


app = create_app()
