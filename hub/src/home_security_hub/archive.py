from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from home_security_hub.manifest import Manifest


@dataclass(frozen=True)
class IngestResult:
    rows_in_snapshot: int
    rows_inserted: int
    rows_skipped: int


class Archive:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ble_address_observations (
                  scanner_id TEXT NOT NULL,
                  observed_at_utc TEXT NOT NULL,
                  source TEXT NOT NULL,
                  scanner TEXT NOT NULL,
                  address_observed TEXT NOT NULL,
                  name TEXT,
                  local_name TEXT,
                  rssi INTEGER,
                  service_uuids_json TEXT NOT NULL,
                  hostname TEXT NOT NULL,
                  ingested_at_utc TEXT NOT NULL,
                  PRIMARY KEY (scanner_id, observed_at_utc, address_observed)
                );

                CREATE INDEX IF NOT EXISTS idx_ble_obs_address_time
                  ON ble_address_observations(address_observed, observed_at_utc);

                CREATE INDEX IF NOT EXISTS idx_ble_obs_scanner_time
                  ON ble_address_observations(scanner_id, observed_at_utc);

                CREATE TABLE IF NOT EXISTS snapshot_ingests (
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

                CREATE INDEX IF NOT EXISTS idx_snapshot_ingests_scanner_time
                  ON snapshot_ingests(scanner_id, ingested_at_utc);
                """
            )
            connection.commit()

    def ingest_snapshot(
        self,
        *,
        snapshot_path: Path,
        manifest: Manifest,
        manifest_path: Path,
        ingested_at_utc: datetime,
    ) -> IngestResult:
        ingested_at_iso = ingested_at_utc.isoformat()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("ATTACH DATABASE ? AS src", (str(snapshot_path),))
            try:
                rows_in_snapshot = connection.execute(
                    "SELECT COUNT(*) FROM src.ble_address_observations"
                ).fetchone()[0]

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO main.ble_address_observations (
                      scanner_id, observed_at_utc, source, scanner,
                      address_observed, name, local_name, rssi,
                      service_uuids_json, hostname, ingested_at_utc
                    )
                    SELECT
                      ?, observed_at_utc, source, scanner,
                      address_observed, name, local_name, rssi,
                      service_uuids_json, hostname, ?
                    FROM src.ble_address_observations
                    """,
                    (manifest.scanner_id, ingested_at_iso),
                )
                rows_inserted = cursor.rowcount
                rows_skipped = rows_in_snapshot - rows_inserted

                connection.execute(
                    """
                    INSERT INTO snapshot_ingests (
                      scanner_id, hostname, snapshot_taken_at_utc,
                      snapshot_sha256, manifest_path,
                      rows_in_snapshot, rows_inserted, rows_skipped,
                      observed_at_utc_min, observed_at_utc_max,
                      ingested_at_utc, pi_package_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        manifest.scanner_id,
                        manifest.hostname,
                        manifest.snapshot_taken_at_utc,
                        manifest.sha256,
                        str(manifest_path),
                        rows_in_snapshot,
                        rows_inserted,
                        rows_skipped,
                        manifest.observed_at_utc_min,
                        manifest.observed_at_utc_max,
                        ingested_at_iso,
                        manifest.package_version,
                    ),
                )
                connection.commit()
            finally:
                connection.execute("DETACH DATABASE src")

        return IngestResult(
            rows_in_snapshot=rows_in_snapshot,
            rows_inserted=rows_inserted,
            rows_skipped=rows_skipped,
        )

    def scanner_summary(self, scanner_id: str) -> dict[str, int | str | None]:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT
                  COUNT(*) AS row_count,
                  COUNT(DISTINCT address_observed) AS unique_addresses,
                  MIN(observed_at_utc) AS observed_at_utc_min,
                  MAX(observed_at_utc) AS observed_at_utc_max
                FROM ble_address_observations
                WHERE scanner_id = ?
                """,
                (scanner_id,),
            ).fetchone()
        return dict(row)
