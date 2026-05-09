from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from home_security_pi.ble_observe import BLEObservationStore
from home_security_pi.snapshot import (
    SnapshotError,
    create_snapshot,
    read_scanner_id_file,
    sha256_file,
    validate_scanner_id,
)


def insert_observation(
    database: Path,
    *,
    observed_at_utc: str,
    address_observed: str,
    hostname: str = "test-host",
) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO ble_address_observations (
              observed_at_utc, source, scanner, address_observed,
              name, local_name, rssi, service_uuids_json, hostname
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_at_utc,
                "ble",
                "bleak",
                address_observed,
                None,
                None,
                None,
                "[]",
                hostname,
            ),
        )


class SnapshotTests(unittest.TestCase):
    def test_creates_snapshot_and_manifest_with_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            database = tmp / "obs.sqlite3"
            output_dir = tmp / "snap"
            BLEObservationStore(database).initialize()
            insert_observation(
                database,
                observed_at_utc="2026-01-01T00:00:00+00:00",
                address_observed="AA",
            )
            insert_observation(
                database,
                observed_at_utc="2026-01-02T00:00:00+00:00",
                address_observed="BB",
            )

            taken_at = datetime(2026, 1, 3, 12, 30, 45, tzinfo=UTC)
            snapshot_path, manifest_path, manifest = create_snapshot(
                database=database,
                output_dir=output_dir,
                scanner_id="test-scanner",
                snapshot_taken_at=taken_at,
                hostname="test-host",
            )

            self.assertTrue(snapshot_path.is_file())
            self.assertTrue(manifest_path.is_file())
            self.assertEqual(
                snapshot_path.name,
                "test-scanner__20260103T123045Z.sqlite3",
            )
            self.assertEqual(
                manifest_path.name,
                "test-scanner__20260103T123045Z.json",
            )

            self.assertEqual(manifest.row_count, 2)
            self.assertEqual(manifest.unique_addresses, 2)
            self.assertEqual(manifest.observed_at_utc_min, "2026-01-01T00:00:00+00:00")
            self.assertEqual(manifest.observed_at_utc_max, "2026-01-02T00:00:00+00:00")
            self.assertEqual(manifest.integrity, "ok")
            self.assertEqual(manifest.scanner_id, "test-scanner")
            self.assertEqual(manifest.hostname, "test-host")
            self.assertEqual(manifest.sha256, sha256_file(snapshot_path))

            disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(disk_manifest["row_count"], 2)
            self.assertEqual(disk_manifest["sha256"], manifest.sha256)
            self.assertEqual(
                disk_manifest["snapshot_taken_at_utc"],
                "2026-01-03T12:30:45+00:00",
            )

            with sqlite3.connect(snapshot_path) as connection:
                rows = connection.execute(
                    "SELECT COUNT(*) FROM ble_address_observations"
                ).fetchone()[0]
            self.assertEqual(rows, 2)

    def test_snapshot_with_empty_table_has_null_observed_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            database = tmp / "obs.sqlite3"
            output_dir = tmp / "snap"
            BLEObservationStore(database).initialize()

            taken_at = datetime(2026, 1, 3, 12, 30, 45, tzinfo=UTC)
            _, _, manifest = create_snapshot(
                database=database,
                output_dir=output_dir,
                scanner_id="empty",
                snapshot_taken_at=taken_at,
                hostname="test-host",
            )

            self.assertEqual(manifest.row_count, 0)
            self.assertEqual(manifest.unique_addresses, 0)
            self.assertIsNone(manifest.observed_at_utc_min)
            self.assertIsNone(manifest.observed_at_utc_max)
            self.assertEqual(manifest.integrity, "ok")

    def test_invalid_scanner_id_raises(self) -> None:
        for invalid in [
            "bad/id",
            "with space",
            "with__double_underscore",
            "-leading-dash",
            ".leading-dot",
            "",
        ]:
            with self.assertRaises(SnapshotError):
                validate_scanner_id(invalid)

    def test_valid_scanner_ids_pass(self) -> None:
        for valid in ["pi-test", "front-yard", "Garage.Indoor-1", "abc123"]:
            self.assertEqual(validate_scanner_id(valid), valid)

    def test_read_scanner_id_file_returns_validated_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner-id"
            path.write_text("pi-livingroom\n", encoding="utf-8")
            self.assertEqual(read_scanner_id_file(path), "pi-livingroom")

    def test_read_scanner_id_file_missing_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner-id"
            with self.assertRaises(SnapshotError):
                read_scanner_id_file(path)

    def test_read_scanner_id_file_empty_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner-id"
            path.write_text("   \n", encoding="utf-8")
            with self.assertRaises(SnapshotError):
                read_scanner_id_file(path)

    def test_read_scanner_id_file_invalid_value_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner-id"
            path.write_text("bad id with spaces\n", encoding="utf-8")
            with self.assertRaises(SnapshotError):
                read_scanner_id_file(path)

    def test_missing_database_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            taken_at = datetime(2026, 1, 3, 12, 30, 45, tzinfo=UTC)
            with self.assertRaises(SnapshotError):
                create_snapshot(
                    database=tmp / "missing.sqlite3",
                    output_dir=tmp / "snap",
                    scanner_id="x",
                    snapshot_taken_at=taken_at,
                    hostname="h",
                )


if __name__ == "__main__":
    unittest.main()
