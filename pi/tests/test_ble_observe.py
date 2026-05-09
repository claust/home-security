from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from home_security_pi.ble_observe import (
    BLEObservationStore,
    ObservationLimiter,
    build_observation,
    record_if_due,
)


@dataclass(frozen=True)
class FakeDevice:
    address: str
    name: str | None
    rssi: int | None = None


@dataclass(frozen=True)
class FakeAdvertisement:
    local_name: str | None
    service_uuids: list[str]
    rssi: int | None = None


class AdjustableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class BLEObserveTests(unittest.TestCase):
    def test_initialize_creates_single_observation_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state/observations.sqlite3"
            store = BLEObservationStore(database)

            store.initialize()

            with sqlite3.connect(database) as connection:
                tables = [
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                ]

        self.assertEqual(tables, ["ble_address_observations"])

    def test_records_address_observed_once_per_minute(self) -> None:
        started_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        clock = AdjustableClock(started_at)

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            store = BLEObservationStore(database)
            store.initialize()
            limiter = ObservationLimiter(
                store,
                min_interval=timedelta(seconds=60),
                clock=clock,
            )

            first = build_observation(
                FakeDevice(address="AA:BB:CC:DD:EE:FF", name="Device"),
                FakeAdvertisement(
                    local_name="Advertised",
                    service_uuids=["180f"],
                    rssi=-70,
                ),
                observed_at_utc=clock(),
                hostname="test-host",
            )
            self.assertTrue(record_if_due(store, limiter, first))

            clock.current = started_at + timedelta(seconds=59)
            duplicate = build_observation(
                FakeDevice(address="AA:BB:CC:DD:EE:FF", name="Device"),
                FakeAdvertisement(
                    local_name="Advertised",
                    service_uuids=["180f"],
                    rssi=-68,
                ),
                observed_at_utc=clock(),
                hostname="test-host",
            )
            self.assertFalse(record_if_due(store, limiter, duplicate))

            clock.current = started_at + timedelta(seconds=60)
            later = build_observation(
                FakeDevice(address="AA:BB:CC:DD:EE:FF", name="Device"),
                FakeAdvertisement(
                    local_name="Advertised",
                    service_uuids=["180f"],
                    rssi=-65,
                ),
                observed_at_utc=clock(),
                hostname="test-host",
            )
            self.assertTrue(record_if_due(store, limiter, later))

            with sqlite3.connect(database) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM ble_address_observations"
                ).fetchone()[0]

        self.assertEqual(count, 2)

    def test_records_different_addresses_immediately(self) -> None:
        observed_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        clock = AdjustableClock(observed_at)

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "observations.sqlite3"
            store = BLEObservationStore(database)
            store.initialize()
            limiter = ObservationLimiter(
                store,
                min_interval=timedelta(seconds=60),
                clock=clock,
            )

            for address in ["AA", "BB"]:
                observation = build_observation(
                    FakeDevice(address=address, name=None),
                    FakeAdvertisement(local_name=None, service_uuids=[]),
                    observed_at_utc=observed_at,
                    hostname="test-host",
                )
                self.assertTrue(record_if_due(store, limiter, observation))

            with sqlite3.connect(database) as connection:
                addresses = [
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT address_observed
                        FROM ble_address_observations
                        ORDER BY address_observed
                        """
                    )
                ]

        self.assertEqual(addresses, ["AA", "BB"])


if __name__ == "__main__":
    unittest.main()
