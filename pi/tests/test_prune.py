from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from home_security_pi.prune import (
    PruneError,
    compute_effective_before,
    parse_iso_utc,
    prune_observations,
)


def build_observations_db(path: Path, observed_at_utcs: list[str]) -> None:
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
              manufacturer_data_json TEXT NOT NULL,
              hostname TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO ble_address_observations (
              observed_at_utc, source, scanner, address_observed,
              name, local_name, rssi, service_uuids_json,
              manufacturer_data_json, hostname
            ) VALUES (?, 'ble', 'bleak', 'AA:BB:CC:DD:EE:FF',
                      NULL, NULL, NULL, '[]', '{}', 'pi-test')
            """,
            [(value,) for value in observed_at_utcs],
        )


class ParseIsoUtcTests(unittest.TestCase):
    def test_accepts_utc_offset(self) -> None:
        result = parse_iso_utc("2026-05-09T12:00:00+00:00")
        self.assertEqual(result, datetime(2026, 5, 9, 12, 0, tzinfo=UTC))

    def test_converts_other_offsets_to_utc(self) -> None:
        result = parse_iso_utc("2026-05-09T14:00:00+02:00")
        self.assertEqual(result, datetime(2026, 5, 9, 12, 0, tzinfo=UTC))

    def test_rejects_naive_timestamp(self) -> None:
        with self.assertRaises(PruneError):
            parse_iso_utc("2026-05-09T12:00:00")

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(PruneError):
            parse_iso_utc("not-a-timestamp")


class ComputeEffectiveBeforeTests(unittest.TestCase):
    def test_takes_floor_when_before_is_more_recent(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        requested = now - timedelta(days=1)
        floor_keep = 14
        result = compute_effective_before(
            requested_before=requested,
            keep_last_days=floor_keep,
            now=now,
        )
        self.assertEqual(result, now - timedelta(days=floor_keep))

    def test_takes_requested_when_before_is_older_than_floor(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        requested = now - timedelta(days=30)
        result = compute_effective_before(
            requested_before=requested,
            keep_last_days=14,
            now=now,
        )
        self.assertEqual(result, requested)

    def test_zero_keep_last_days_uses_requested(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        requested = now - timedelta(hours=1)
        result = compute_effective_before(
            requested_before=requested,
            keep_last_days=0,
            now=now,
        )
        self.assertEqual(result, requested)

    def test_negative_keep_last_days_raises(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with self.assertRaises(PruneError):
            compute_effective_before(
                requested_before=now,
                keep_last_days=-1,
                now=now,
            )


class PruneObservationsTests(unittest.TestCase):
    def test_deletes_rows_at_or_before_effective_watermark(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            build_observations_db(
                database,
                [
                    (now - timedelta(days=30)).isoformat(),
                    (now - timedelta(days=20)).isoformat(),
                    (now - timedelta(days=10)).isoformat(),
                    (now - timedelta(days=1)).isoformat(),
                ],
            )

            result = prune_observations(
                database=database,
                requested_before=now,
                keep_last_days=14,
                now=now,
            )

            with sqlite3.connect(database) as connection:
                remaining = [
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT observed_at_utc
                        FROM ble_address_observations
                        ORDER BY observed_at_utc
                        """
                    )
                ]

        self.assertEqual(result.rows_deleted, 2)
        self.assertEqual(
            result.effective_before_utc,
            (now - timedelta(days=14)).isoformat(),
        )
        self.assertEqual(
            remaining,
            [
                (now - timedelta(days=10)).isoformat(),
                (now - timedelta(days=1)).isoformat(),
            ],
        )

    def test_no_op_when_floor_protects_everything(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            build_observations_db(
                database,
                [
                    (now - timedelta(days=2)).isoformat(),
                    (now - timedelta(days=1)).isoformat(),
                ],
            )

            result = prune_observations(
                database=database,
                requested_before=now,
                keep_last_days=14,
                now=now,
            )

            with sqlite3.connect(database) as connection:
                remaining_count = connection.execute(
                    "SELECT COUNT(*) FROM ble_address_observations"
                ).fetchone()[0]

        self.assertEqual(result.rows_deleted, 0)
        self.assertEqual(remaining_count, 2)

    def test_no_op_when_table_is_empty(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            build_observations_db(database, [])

            result = prune_observations(
                database=database,
                requested_before=now - timedelta(days=30),
                keep_last_days=14,
                now=now,
            )

        self.assertEqual(result.rows_deleted, 0)

    def test_prunes_wifi_table_when_present(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            build_observations_db(
                database,
                [
                    (now - timedelta(days=30)).isoformat(),
                    (now - timedelta(days=1)).isoformat(),
                ],
            )
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    CREATE TABLE wifi_address_observations (
                      id INTEGER PRIMARY KEY,
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
                      hostname TEXT NOT NULL
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO wifi_address_observations (
                      observed_at_utc, source, scanner, address_observed,
                      frame_type, ssid, rssi, channel, is_randomized_mac,
                      information_elements_json, hostname
                    ) VALUES (?, 'wifi', 'scapy', 'a6:00:00:00:00:01',
                              'probe_req', NULL, -50, 6, 1, '{}', 'pi-test')
                    """,
                    [
                        ((now - timedelta(days=30)).isoformat(),),
                        ((now - timedelta(days=20)).isoformat(),),
                        ((now - timedelta(days=1)).isoformat(),),
                    ],
                )

            result = prune_observations(
                database=database,
                requested_before=now,
                keep_last_days=14,
                now=now,
            )

            with sqlite3.connect(database) as connection:
                wifi_remaining = connection.execute(
                    "SELECT COUNT(*) FROM wifi_address_observations"
                ).fetchone()[0]

        self.assertEqual(result.rows_deleted, 1)
        self.assertEqual(result.wifi_rows_deleted, 2)
        self.assertEqual(wifi_remaining, 1)

    def test_wifi_rows_deleted_is_zero_when_table_absent(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            build_observations_db(database, [(now - timedelta(days=30)).isoformat()])

            result = prune_observations(
                database=database,
                requested_before=now,
                keep_last_days=14,
                now=now,
            )

        self.assertEqual(result.wifi_rows_deleted, 0)

    def test_missing_database_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.sqlite3"
            with self.assertRaises(PruneError):
                prune_observations(
                    database=database,
                    requested_before=datetime(2026, 5, 9, tzinfo=UTC),
                    keep_last_days=14,
                    now=datetime(2026, 5, 9, 12, tzinfo=UTC),
                )

    def test_result_carries_metadata(self) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        requested_before = now - timedelta(days=30)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            build_observations_db(database, [])

            result = prune_observations(
                database=database,
                requested_before=requested_before,
                keep_last_days=14,
                now=now,
            )

        self.assertEqual(result.database, str(database))
        self.assertEqual(result.requested_before_utc, requested_before.isoformat())
        self.assertEqual(result.keep_last_days, 14)
        self.assertEqual(result.pruned_at_utc, now.isoformat())


if __name__ == "__main__":
    unittest.main()
