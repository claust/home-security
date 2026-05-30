from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from home_security_api.app import create_app
from home_security_api.settings import Settings

# Schema mirrors hub/src/home_security_hub/archive.py (the consolidated archive
# the API reads). Only the columns the API queries are populated with realistic
# values; the remaining NOT NULL columns get placeholders.
_SCHEMA = """
CREATE TABLE ble_address_observations (
  scanner_id TEXT NOT NULL,
  observed_at_utc TEXT NOT NULL,
  source TEXT NOT NULL,
  scanner TEXT NOT NULL,
  address_observed TEXT NOT NULL,
  name TEXT,
  local_name TEXT,
  rssi INTEGER,
  service_uuids_json TEXT NOT NULL,
  manufacturer_data_json TEXT NOT NULL,
  hostname TEXT NOT NULL,
  ingested_at_utc TEXT NOT NULL,
  PRIMARY KEY (scanner_id, observed_at_utc, address_observed)
);
CREATE TABLE snapshot_ingests (
  id INTEGER PRIMARY KEY,
  scanner_id TEXT NOT NULL,
  ingested_at_utc TEXT NOT NULL
);
"""


def _build_archive(path: Path, *, rows: int) -> None:
    """Populate a synthetic archive large enough that concurrent aggregate
    queries genuinely overlap in the threadpool."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        scanners = ("pi-a", "pi-b", "pi-c")
        observations = []
        for i in range(rows):
            scanner = scanners[i % len(scanners)]
            # Spread across hours so /stats/hourly produces many buckets.
            hour = i % 96
            day = 10 + hour // 24
            observed = f"2026-05-{day:02d}T{hour % 24:02d}:{i % 60:02d}:00+00:00"
            observations.append(
                (
                    scanner,
                    observed,
                    "ble",
                    scanner,
                    f"AA:BB:CC:DD:{(i % 500) >> 8:02X}:{(i % 500) & 0xFF:02X}",
                    None,
                    None,
                    -50,
                    json.dumps([]),
                    json.dumps({}),
                    "host",
                    "2026-05-30T00:00:00+00:00",
                )
            )
        connection.executemany(
            """
            INSERT OR IGNORE INTO ble_address_observations (
              scanner_id, observed_at_utc, source, scanner, address_observed,
              name, local_name, rssi, service_uuids_json, manufacturer_data_json,
              hostname, ingested_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            observations,
        )
        connection.execute(
            "INSERT INTO snapshot_ingests (scanner_id, ingested_at_utc) "
            "VALUES ('pi-a', '2026-05-30T00:00:00+00:00')"
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture(scope="session")
def archive_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("archive") / "archive.sqlite3"
    _build_archive(path, rows=40_000)
    return path


@pytest.fixture
def settings(archive_path: Path) -> Settings:
    return Settings(archive_path=archive_path)


@pytest.fixture
def app(settings: Settings) -> Iterator[object]:
    yield create_app(settings)
