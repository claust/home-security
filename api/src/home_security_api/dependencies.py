from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from home_security_api.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_connection(request: Request) -> Iterator[sqlite3.Connection]:
    """Yield the shared read-only sqlite connection.

    SQLite handles many concurrent readers; we keep one process-wide
    connection and rely on its thread-safety for short reads. If the
    archive disappears at runtime, surface a 503.
    """
    connection: sqlite3.Connection | None = getattr(request.app.state, "db", None)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="archive connection not available",
        )
    yield connection


SettingsDep = Annotated[Settings, Depends(get_settings)]
ConnectionDep = Annotated[sqlite3.Connection, Depends(get_connection)]
