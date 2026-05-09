from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from home_security_hub.archive import Archive
from home_security_hub.manifest import Manifest


def build_pi_snapshot(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE ble_address_observations (
              id INTEGER PRIMARY KEY,
              observed_at_utc TEXT NOT NULL,
              source TEXT NOT NULL,
              scanner TEXT NOT NULL,
              address_observed TEXT NOT NULL,
              name TEXT,
              local_name TEXT,
              rssi INTEGER,
              service_uuids_json TEXT NOT NULL,
              hostname TEXT NOT NULL
            )
            """
        )
        for row in rows:
            connection.execute(
                """
                INSERT INTO ble_address_observations (
                  observed_at_utc, source, scanner, address_observed,
                  name, local_name, rssi, service_uuids_json, hostname
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["observed_at_utc"],
                    row.get("source", "ble"),
                    row.get("scanner", "bleak"),
                    row["address_observed"],
                    row.get("name"),
                    row.get("local_name"),
                    row.get("rssi"),
                    row.get("service_uuids_json", "[]"),
                    row.get("hostname", "pi-test"),
                ),
            )


def manifest_for(scanner_id: str, **overrides: object) -> Manifest:
    fields = {
        "scanner_id": scanner_id,
        "hostname": scanner_id,
        "snapshot_taken_at_utc": "2026-05-09T12:33:30+00:00",
        "database_source": "/whatever/observations.sqlite3",
        "row_count": 0,
        "unique_addresses": 0,
        "observed_at_utc_min": None,
        "observed_at_utc_max": None,
        "sha256": "0" * 64,
        "integrity": "ok",
        "package_version": "0.1.0",
    }
    fields.update(overrides)
    return Manifest(**fields)


class ArchiveTests(unittest.TestCase):
    def test_initialize_creates_expected_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "archive.sqlite3"
            archive = Archive(archive_path)
            archive.initialize()

            with sqlite3.connect(archive_path) as connection:
                tables = sorted(
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                        """
                    )
                )
        self.assertEqual(tables, ["ble_address_observations", "snapshot_ingests"])

    def test_ingest_inserts_rows_with_scanner_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            archive_path = tmp / "archive.sqlite3"
            snapshot_path = tmp / "snap.sqlite3"
            manifest_path = tmp / "snap.json"

            build_pi_snapshot(
                snapshot_path,
                [
                    {
                        "observed_at_utc": "2026-05-09T10:00:00+00:00",
                        "address_observed": "AA",
                    },
                    {
                        "observed_at_utc": "2026-05-09T10:01:00+00:00",
                        "address_observed": "BB",
                    },
                ],
            )

            archive = Archive(archive_path)
            archive.initialize()
            result = archive.ingest_snapshot(
                snapshot_path=snapshot_path,
                manifest=manifest_for("pi-test", row_count=2, unique_addresses=2),
                manifest_path=manifest_path,
                ingested_at_utc=datetime(2026, 5, 9, 12, 30, tzinfo=UTC),
            )

            self.assertEqual(result.rows_in_snapshot, 2)
            self.assertEqual(result.rows_inserted, 2)
            self.assertEqual(result.rows_skipped, 0)

            with sqlite3.connect(archive_path) as connection:
                rows = connection.execute(
                    """
                    SELECT scanner_id, address_observed
                    FROM ble_address_observations
                    ORDER BY address_observed
                    """
                ).fetchall()
                ingest_rows = connection.execute(
                    "SELECT COUNT(*) FROM snapshot_ingests"
                ).fetchone()[0]

        self.assertEqual(rows, [("pi-test", "AA"), ("pi-test", "BB")])
        self.assertEqual(ingest_rows, 1)

    def test_repeated_ingest_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            archive_path = tmp / "archive.sqlite3"
            snapshot_path = tmp / "snap.sqlite3"
            manifest_path = tmp / "snap.json"

            build_pi_snapshot(
                snapshot_path,
                [
                    {
                        "observed_at_utc": "2026-05-09T10:00:00+00:00",
                        "address_observed": "AA",
                    }
                ],
            )

            archive = Archive(archive_path)
            archive.initialize()
            manifest = manifest_for("pi-test", row_count=1, unique_addresses=1)

            first = archive.ingest_snapshot(
                snapshot_path=snapshot_path,
                manifest=manifest,
                manifest_path=manifest_path,
                ingested_at_utc=datetime(2026, 5, 9, 12, 30, tzinfo=UTC),
            )
            second = archive.ingest_snapshot(
                snapshot_path=snapshot_path,
                manifest=manifest,
                manifest_path=manifest_path,
                ingested_at_utc=datetime(2026, 5, 9, 12, 31, tzinfo=UTC),
            )

            self.assertEqual(first.rows_inserted, 1)
            self.assertEqual(second.rows_inserted, 0)
            self.assertEqual(second.rows_skipped, 1)

            with sqlite3.connect(archive_path) as connection:
                row_count = connection.execute(
                    "SELECT COUNT(*) FROM ble_address_observations"
                ).fetchone()[0]
                ingest_count = connection.execute(
                    "SELECT COUNT(*) FROM snapshot_ingests"
                ).fetchone()[0]

        self.assertEqual(row_count, 1)
        self.assertEqual(ingest_count, 2)

    def test_ingest_keeps_rows_from_different_scanners_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            archive_path = tmp / "archive.sqlite3"
            archive = Archive(archive_path)
            archive.initialize()

            snapshot_a = tmp / "a.sqlite3"
            snapshot_b = tmp / "b.sqlite3"
            build_pi_snapshot(
                snapshot_a,
                [
                    {
                        "observed_at_utc": "2026-05-09T10:00:00+00:00",
                        "address_observed": "AA",
                        "hostname": "front-yard",
                    }
                ],
            )
            build_pi_snapshot(
                snapshot_b,
                [
                    {
                        "observed_at_utc": "2026-05-09T10:00:00+00:00",
                        "address_observed": "AA",
                        "hostname": "garage",
                    }
                ],
            )

            archive.ingest_snapshot(
                snapshot_path=snapshot_a,
                manifest=manifest_for("front-yard", row_count=1, unique_addresses=1),
                manifest_path=tmp / "a.json",
                ingested_at_utc=datetime(2026, 5, 9, 12, 30, tzinfo=UTC),
            )
            archive.ingest_snapshot(
                snapshot_path=snapshot_b,
                manifest=manifest_for("garage", row_count=1, unique_addresses=1),
                manifest_path=tmp / "b.json",
                ingested_at_utc=datetime(2026, 5, 9, 12, 31, tzinfo=UTC),
            )

            with sqlite3.connect(archive_path) as connection:
                scanners = sorted(
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT scanner_id FROM ble_address_observations"
                    )
                )

        self.assertEqual(scanners, ["front-yard", "garage"])

    def test_scanner_summary_returns_counts_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            archive_path = tmp / "archive.sqlite3"
            snapshot_path = tmp / "snap.sqlite3"

            build_pi_snapshot(
                snapshot_path,
                [
                    {
                        "observed_at_utc": "2026-05-09T10:00:00+00:00",
                        "address_observed": "AA",
                    },
                    {
                        "observed_at_utc": "2026-05-09T11:00:00+00:00",
                        "address_observed": "BB",
                    },
                ],
            )
            archive = Archive(archive_path)
            archive.initialize()
            archive.ingest_snapshot(
                snapshot_path=snapshot_path,
                manifest=manifest_for("pi-test", row_count=2, unique_addresses=2),
                manifest_path=tmp / "snap.json",
                ingested_at_utc=datetime(2026, 5, 9, 12, 30, tzinfo=UTC),
            )

            summary = archive.scanner_summary("pi-test")

        self.assertEqual(summary["row_count"], 2)
        self.assertEqual(summary["unique_addresses"], 2)
        self.assertEqual(summary["observed_at_utc_min"], "2026-05-09T10:00:00+00:00")
        self.assertEqual(summary["observed_at_utc_max"], "2026-05-09T11:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
