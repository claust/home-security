from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from home_security_api.app import create_app
from home_security_api.settings import Settings

# Schema mirrors the consolidated archive exactly: ble_address_observations and
# snapshot_ingests from hub/src/home_security_hub/archive.py, plus the
# reference tables company_identifiers and service_uuids populated by
# tools/home-security-vendors-refresh. Keeping every NOT NULL column here means
# the shared app fixture exercises endpoints against the production schema
# rather than failing on missing columns.
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
CREATE INDEX idx_ble_obs_address_time
  ON ble_address_observations(address_observed, observed_at_utc);
CREATE INDEX idx_ble_obs_scanner_time
  ON ble_address_observations(scanner_id, observed_at_utc);

CREATE TABLE snapshot_ingests (
  id INTEGER PRIMARY KEY,
  scanner_id TEXT NOT NULL,
  hostname TEXT NOT NULL,
  snapshot_taken_at_utc TEXT NOT NULL,
  snapshot_sha256 TEXT NOT NULL,
  manifest_path TEXT NOT NULL,
  rows_in_snapshot INTEGER NOT NULL,
  rows_inserted INTEGER NOT NULL,
  rows_skipped INTEGER NOT NULL,
  observed_at_utc_min TEXT,
  observed_at_utc_max TEXT,
  ingested_at_utc TEXT NOT NULL,
  pi_package_version TEXT NOT NULL
);
CREATE INDEX idx_snapshot_ingests_scanner_time
  ON snapshot_ingests(scanner_id, ingested_at_utc);

CREATE TABLE company_identifiers (
  company_id INTEGER PRIMARY KEY,
  company_id_hex TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL
);
CREATE INDEX idx_company_identifiers_name ON company_identifiers(name);

CREATE TABLE service_uuids (
  uuid INTEGER PRIMARY KEY,
  uuid_hex TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('sig', 'member')),
  identifier TEXT
);
CREATE INDEX idx_service_uuids_name ON service_uuids(name);
CREATE INDEX idx_service_uuids_kind ON service_uuids(kind);
"""

# A handful of reference rows so vendor/service joins resolve to real names.
_COMPANY_IDENTIFIERS = [
    (76, "004c", "Apple, Inc."),
    (6, "0006", "Microsoft"),
]
_SERVICE_UUIDS = [
    (6159, "180f", "Battery Service", "sig", "org.bluetooth.service.battery_service"),
    (65517, "fff0", "Member Service", "member", None),
]
_SCANNERS = ("pi-a", "pi-b", "pi-c")


def _build_archive(path: Path, *, rows: int) -> None:
    """Populate a synthetic archive large enough that concurrent aggregate
    queries genuinely overlap in the threadpool."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.executemany(
            "INSERT INTO company_identifiers (company_id, company_id_hex, name) "
            "VALUES (?, ?, ?)",
            _COMPANY_IDENTIFIERS,
        )
        connection.executemany(
            "INSERT INTO service_uuids (uuid, uuid_hex, name, kind, identifier) "
            "VALUES (?, ?, ?, ?, ?)",
            _SERVICE_UUIDS,
        )

        observations = []
        for i in range(rows):
            scanner = _SCANNERS[i % len(_SCANNERS)]
            # Spread across hours so /stats/hourly produces many buckets.
            hour = i % 96
            day = 10 + hour // 24
            observed = f"2026-05-{day:02d}T{hour % 24:02d}:{i % 60:02d}:00+00:00"
            address = f"AA:BB:CC:DD:{(i % 500) >> 8:02X}:{(i % 500) & 0xFF:02X}"
            # Give a slice of rows real manufacturer/service payloads so the
            # vendor and service joins exercise non-empty results.
            mfr = {"004c": "0215"} if i % 5 == 0 else {}
            svcs = ["0000180f-0000-1000-8000-00805f9b34fb"] if i % 7 == 0 else []
            observations.append(
                (
                    scanner,
                    observed,
                    "ble",
                    scanner,
                    address,
                    None,
                    None,
                    -50,
                    json.dumps(svcs),
                    json.dumps(mfr),
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
        connection.executemany(
            """
            INSERT INTO snapshot_ingests (
              scanner_id, hostname, snapshot_taken_at_utc, snapshot_sha256,
              manifest_path, rows_in_snapshot, rows_inserted, rows_skipped,
              observed_at_utc_min, observed_at_utc_max, ingested_at_utc,
              pi_package_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    scanner,
                    "host",
                    "2026-05-30T00:00:00+00:00",
                    "0" * 64,
                    f"manifests/{scanner}.json",
                    1000,
                    1000,
                    0,
                    "2026-05-10T00:00:00+00:00",
                    "2026-05-13T23:59:00+00:00",
                    "2026-05-30T00:00:00+00:00",
                    "0.1.0",
                )
                for scanner in _SCANNERS
            ],
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
