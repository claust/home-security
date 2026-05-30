from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_DATABASE = Path.home() / ".local/state/home-security/observations.sqlite3"


@dataclass(frozen=True)
class WifiObservation:
    observed_at_utc: datetime
    source: str  # "wifi"
    scanner: str  # "scapy"
    address_observed: str  # transmitter MAC (may be randomized)
    frame_type: str  # "probe_req" | "beacon" | "probe_resp" | "data" | ...
    ssid: str | None
    rssi: int | None
    channel: int | None
    is_randomized_mac: bool
    information_elements: dict[str, object]
    hostname: str


class WifiObservationStore:
    """SQLite-backed store for Wi-Fi observations.

    Lives in the *same* ``observations.sqlite3`` as the BLE store so the Pi
    snapshot (a whole-file ``src.backup`` copy) picks it up for free. WAL mode
    is enabled so the BLE observer and Wi-Fi observer can write the one file
    concurrently without blocking on a single-writer lock.
    """

    def __init__(self, database: Path) -> None:
        self.database = database

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS wifi_address_observations (
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
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_wifi_address_observations_address_time
                ON wifi_address_observations(address_observed, observed_at_utc)
                """
            )

    def insert(self, observation: WifiObservation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO wifi_address_observations (
                  observed_at_utc,
                  source,
                  scanner,
                  address_observed,
                  frame_type,
                  ssid,
                  rssi,
                  channel,
                  is_randomized_mac,
                  information_elements_json,
                  hostname
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.observed_at_utc.isoformat(),
                    observation.source,
                    observation.scanner,
                    observation.address_observed,
                    observation.frame_type,
                    observation.ssid,
                    observation.rssi,
                    observation.channel,
                    1 if observation.is_randomized_mac else 0,
                    json.dumps(
                        observation.information_elements,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    observation.hostname,
                ),
            )

    def latest_observed_at(self, address_observed: str) -> datetime | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT observed_at_utc
                FROM wifi_address_observations
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
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
