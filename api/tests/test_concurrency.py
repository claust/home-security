"""Regression tests for the cold concurrent page-load pattern.

The web dashboard fires /stats/overview (a heavy COUNT(*) + COUNT(DISTINCT))
and /stats/hourly concurrently on load. A single process-wide sqlite3
connection shared across the FastAPI threadpool corrupted cursors under that
overlap and 500'd. Each request now gets its own read-only connection.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import Counter

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from home_security_api.dependencies import get_connection


def test_get_connection_is_per_request(app: FastAPI) -> None:
    """Each call must yield a distinct connection -- never a shared one."""
    request = type("R", (), {"app": app})()

    gen_a = get_connection(request)
    conn_a = next(gen_a)
    gen_b = get_connection(request)
    conn_b = next(gen_b)
    try:
        assert conn_a is not conn_b
    finally:
        for gen in (gen_a, gen_b):
            try:
                next(gen)
            except StopIteration:
                pass

    # The per-request connection is closed once the generator is exhausted.
    with pytest.raises(sqlite3.ProgrammingError):
        conn_a.execute("SELECT 1")


def test_concurrent_overview_and_hourly_all_succeed(app: FastAPI) -> None:
    """Hammer the cold-load fan-out; every response must be 200."""
    codes: Counter[tuple[str, int]] = Counter()
    lock = threading.Lock()

    with TestClient(app) as client:

        def hit(path: str, iterations: int) -> None:
            for _ in range(iterations):
                response = client.get(path)
                with lock:
                    codes[(path, response.status_code)] += 1

        threads: list[threading.Thread] = []
        for _ in range(6):
            threads.append(threading.Thread(target=hit, args=("/stats/overview", 20)))
            threads.append(threading.Thread(target=hit, args=("/stats/hourly", 20)))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    non_200 = {key: count for key, count in codes.items() if key[1] != 200}
    assert not non_200, f"unexpected non-200 responses: {non_200}"
    assert codes[("/stats/overview", 200)] == 120
    assert codes[("/stats/hourly", 200)] == 120
