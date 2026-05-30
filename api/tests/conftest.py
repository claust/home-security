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

CREATE TABLE wifi_address_observations (
  scanner_id TEXT NOT NULL,
  observed_at_utc TEXT NOT NULL,
  source TEXT NOT NULL,
  scanner TEXT NOT NULL,
  address_observed TEXT NOT NULL,
  frame_type TEXT NOT NULL,
  ssid TEXT,
  rssi INTEGER,
  channel INTEGER,
  is_randomized_mac INTEGER NOT NULL,
  information_elements_json TEXT NOT NULL,
  hostname TEXT NOT NULL,
  ingested_at_utc TEXT NOT NULL,
  PRIMARY KEY (scanner_id, observed_at_utc, address_observed)
);
CREATE INDEX idx_wifi_obs_address_time
  ON wifi_address_observations(address_observed, observed_at_utc);
CREATE INDEX idx_wifi_obs_scanner_time
  ON wifi_address_observations(scanner_id, observed_at_utc);

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
  wifi_rows_in_snapshot INTEGER NOT NULL DEFAULT 0,
  wifi_rows_inserted INTEGER NOT NULL DEFAULT 0,
  wifi_rows_skipped INTEGER NOT NULL DEFAULT 0,
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
              wifi_rows_in_snapshot, wifi_rows_inserted, wifi_rows_skipped,
              observed_at_utc_min, observed_at_utc_max, ingested_at_utc,
              pi_package_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    500,
                    500,
                    0,
                    "2026-05-10T00:00:00+00:00",
                    "2026-05-13T23:59:00+00:00",
                    "2026-05-30T00:00:00+00:00",
                    "0.1.0",
                )
                for scanner in _SCANNERS
            ],
        )

        _build_wifi(connection, rows=6_000)
        connection.commit()
    finally:
        connection.close()


_WIFI_FRAME_TYPES = ("probe_req", "beacon", "probe_resp", "data")
_WIFI_SSIDS = (None, "Gustav", "GuestNet", "eduroam")


def _build_wifi(connection: sqlite3.Connection, *, rows: int) -> None:
    """Populate synthetic Wi-Fi observations spanning randomized and stable
    MACs, several frame types, and a 2.4 GHz channel spread."""
    observations = []
    for i in range(rows):
        scanner = _SCANNERS[i % len(_SCANNERS)]
        hour = i % 96
        day = 10 + hour // 24
        observed = f"2026-05-{day:02d}T{hour % 24:02d}:{i % 60:02d}:00+00:00"
        # Half the MACs are locally-administered (randomized); encode that in
        # the first octet's second-least-significant bit.
        randomized = i % 2 == 0
        first_octet = 0xA6 if randomized else 0xA4
        address = (
            f"{first_octet:02x}:83:e7:{(i % 300) >> 8:02x}:"
            f"{(i % 300) & 0xFF:02x}:{i % 7:02x}"
        )
        frame_type = _WIFI_FRAME_TYPES[i % len(_WIFI_FRAME_TYPES)]
        ssid = _WIFI_SSIDS[i % len(_WIFI_SSIDS)]
        channel = (i % 13) + 1
        ies = {
            "tag_order": [0, 1, 50, 45, 127, 221],
            "supported_rates": ["1", "2", "5.5", "11"],
            "vendor_specific": ["0017f2"],
        }
        observations.append(
            (
                scanner,
                observed,
                "wifi",
                "scapy",
                address,
                frame_type,
                ssid,
                -60,
                channel,
                1 if randomized else 0,
                json.dumps(ies, separators=(",", ":"), sort_keys=True),
                "host",
                "2026-05-30T00:00:00+00:00",
            )
        )
    connection.executemany(
        """
        INSERT OR IGNORE INTO wifi_address_observations (
          scanner_id, observed_at_utc, source, scanner, address_observed,
          frame_type, ssid, rssi, channel, is_randomized_mac,
          information_elements_json, hostname, ingested_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        observations,
    )


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
