from __future__ import annotations

import argparse
import asyncio
import json
import signal
import socket
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from home_security_pi.ble_scan import (
    AdvertisementLike,
    BLEDeviceLike,
    BLEScanUnavailable,
    normalize_seen_device,
)


DEFAULT_DATABASE = Path.home() / ".local/state/home-security/observations.sqlite3"


class Clock(Protocol):
    def __call__(self) -> datetime: ...


@dataclass(frozen=True)
class AddressObservation:
    observed_at_utc: datetime
    source: str
    scanner: str
    address_observed: str
    name: str | None
    local_name: str | None
    rssi: int | None
    service_uuids: list[str]
    hostname: str


class BLEObservationStore:
    def __init__(self, database: Path) -> None:
        self.database = database

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ble_address_observations (
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
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ble_address_observations_address_time
                ON ble_address_observations(address_observed, observed_at_utc)
                """
            )

    def insert(self, observation: AddressObservation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ble_address_observations (
                  observed_at_utc,
                  source,
                  scanner,
                  address_observed,
                  name,
                  local_name,
                  rssi,
                  service_uuids_json,
                  hostname
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.observed_at_utc.isoformat(),
                    observation.source,
                    observation.scanner,
                    observation.address_observed,
                    observation.name,
                    observation.local_name,
                    observation.rssi,
                    json.dumps(observation.service_uuids, separators=(",", ":")),
                    observation.hostname,
                ),
            )

    def latest_observed_at(self, address_observed: str) -> datetime | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT observed_at_utc
                FROM ble_address_observations
                WHERE address_observed = ?
                ORDER BY observed_at_utc DESC
                LIMIT 1
                """,
                (address_observed,),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(str(row["observed_at_utc"]))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection


class ObservationLimiter:
    def __init__(
        self,
        store: BLEObservationStore,
        *,
        min_interval: timedelta,
        clock: Clock,
    ) -> None:
        self.store = store
        self.min_interval = min_interval
        self.clock = clock
        self._last_recorded_at: dict[str, datetime] = {}

    def should_record(self, address_observed: str) -> bool:
        now = self.clock()
        last_recorded_at = self._last_recorded_at.get(address_observed)
        if last_recorded_at is None:
            last_recorded_at = self.store.latest_observed_at(address_observed)
        return last_recorded_at is None or now - last_recorded_at >= self.min_interval

    def mark_recorded(self, address_observed: str, observed_at_utc: datetime) -> None:
        self._last_recorded_at[address_observed] = observed_at_utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_observation(
    device: BLEDeviceLike,
    advertisement: AdvertisementLike,
    *,
    observed_at_utc: datetime,
    hostname: str,
) -> AddressObservation:
    seen = normalize_seen_device(device, advertisement)
    return AddressObservation(
        observed_at_utc=observed_at_utc,
        source="ble",
        scanner="bleak",
        address_observed=seen.address,
        name=seen.name,
        local_name=seen.local_name,
        rssi=seen.rssi,
        service_uuids=seen.service_uuids,
        hostname=hostname,
    )


def record_if_due(
    store: BLEObservationStore,
    limiter: ObservationLimiter,
    observation: AddressObservation,
) -> bool:
    if not limiter.should_record(observation.address_observed):
        return False
    store.insert(observation)
    limiter.mark_recorded(
        observation.address_observed,
        observation.observed_at_utc,
    )
    return True


async def observe_ble_addresses(
    *,
    database: Path,
    min_interval_seconds: float,
    stop_event: asyncio.Event,
    status: Callable[[str], None] = print,
) -> None:
    try:
        from bleak import BleakScanner
        from bleak.exc import BleakError
    except ImportError as exc:
        raise BLEScanUnavailable(
            "bleak is not installed. Run `uv sync --frozen` before observing."
        ) from exc

    store = BLEObservationStore(database)
    store.initialize()
    limiter = ObservationLimiter(
        store,
        min_interval=timedelta(seconds=min_interval_seconds),
        clock=utc_now,
    )
    hostname = socket.gethostname()

    def on_detection(device: BLEDeviceLike, advertisement: AdvertisementLike) -> None:
        observed_at_utc = utc_now()
        observation = build_observation(
            device,
            advertisement,
            observed_at_utc=observed_at_utc,
            hostname=hostname,
        )
        if record_if_due(store, limiter, observation):
            status(
                json.dumps(
                    {
                        "status": "recorded",
                        "observed_at_utc": observation.observed_at_utc.isoformat(),
                        "address_observed": observation.address_observed,
                        "rssi": observation.rssi,
                    },
                    sort_keys=True,
                )
            )

    try:
        scanner = BleakScanner(detection_callback=on_detection)
        async with scanner:
            await stop_event.wait()
    except BleakError as exc:
        message = exc.args[0] if exc.args else str(exc)
        raise BLEScanUnavailable(str(message)) from exc


async def run_observer(database: Path, min_interval_seconds: float) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop_event.set)

    await observe_ble_addresses(
        database=database,
        min_interval_seconds=min_interval_seconds,
        stop_event=stop_event,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="SQLite database path for BLE address observations.",
    )
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=60.0,
        help="Minimum seconds between stored observations for the same BLE address.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_observer(args.database, args.min_interval_seconds))
    except BLEScanUnavailable as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
