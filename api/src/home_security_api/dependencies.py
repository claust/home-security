from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from home_security_api.db import open_readonly
from home_security_api.settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_connection(request: Request) -> Iterator[sqlite3.Connection]:
    """Yield a fresh read-only sqlite connection scoped to this request.

    FastAPI dispatches sync endpoints to a threadpool, so a single
    process-wide connection would be used concurrently by multiple threads.
    sqlite3 connections are not safe to share that way -- concurrent queries
    corrupt each other's cursors (``sqlite3.InterfaceError: bad parameter or
    other API misuse``, or aggregates silently returning ``None``), which
    surfaces as a 500. The archive is opened read-only (``mode=ro`` +
    ``PRAGMA query_only``), so a per-request connection is cheap and fully
    concurrency-safe. If the archive disappears at runtime, surface a 503.
    """
    settings: Settings = request.app.state.settings
    try:
        connection = open_readonly(settings.archive_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="archive connection not available",
        ) from exc
    try:
        yield connection
    finally:
        connection.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
ConnectionDep = Annotated[sqlite3.Connection, Depends(get_connection)]
