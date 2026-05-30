from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from home_security_pi import __version__

DEFAULT_DATABASE = Path.home() / ".local/state/home-security/observations.sqlite3"
DEFAULT_OUTPUT_DIR = Path.home() / ".local/state/home-security/snapshots"
DEFAULT_SCANNER_ID_FILE = Path.home() / ".local/state/home-security/scanner-id"

SCANNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be produced."""


def read_scanner_id_file(path: Path) -> str:
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SnapshotError(
            f"Scanner identity file is missing: {path}. "
            "Run bootstrap with HOME_SECURITY_SCANNER_ID set."
        ) from exc
    scanner_id = contents.strip()
    if not scanner_id:
        raise SnapshotError(f"Scanner identity file is empty: {path}")
    return validate_scanner_id(scanner_id)


@dataclass(frozen=True)
class SnapshotManifest:
    scanner_id: str
    hostname: str
    snapshot_taken_at_utc: str
    database_source: str
    row_count: int
    unique_addresses: int
    observed_at_utc_min: str | None
    observed_at_utc_max: str | None
    sha256: str
    integrity: str
    package_version: str
    # Wi-Fi observations are optional per Pi (only some have a monitor-capable
    # adapter). When the wifi_address_observations table is absent these report
    # zero / None so the manifest shape stays stable across all Pis.
    wifi_row_count: int = 0
    wifi_unique_addresses: int = 0
    wifi_observed_at_utc_min: str | None = None
    wifi_observed_at_utc_max: str | None = None


@dataclass(frozen=True)
class TableSummary:
    row_count: int
    unique_addresses: int
    observed_at_utc_min: str | None
    observed_at_utc_max: str | None


def utc_now() -> datetime:
    return datetime.now(UTC)


def compact_utc_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def validate_scanner_id(scanner_id: str) -> str:
    if not SCANNER_ID_PATTERN.fullmatch(scanner_id):
        raise SnapshotError(
            "scanner_id must start with an alphanumeric and contain only "
            f"letters, digits, dots and dashes: {scanner_id!r}"
        )
    return scanner_id


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def take_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with (
        closing(sqlite3.connect(source)) as src,
        closing(sqlite3.connect(destination)) as dst,
    ):
        src.backup(dst)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _summarize_table(connection: sqlite3.Connection, table: str) -> TableSummary:
    if not _table_exists(connection, table):
        return TableSummary(0, 0, None, None)
    row = connection.execute(
        f"""
        SELECT
          COUNT(*) AS row_count,
          COUNT(DISTINCT address_observed) AS unique_addresses,
          MIN(observed_at_utc) AS observed_at_utc_min,
          MAX(observed_at_utc) AS observed_at_utc_max
        FROM {table}
        """  # table name is a fixed internal constant, never user input
    ).fetchone()
    return TableSummary(
        int(row["row_count"]),
        int(row["unique_addresses"]),
        row["observed_at_utc_min"],
        row["observed_at_utc_max"],
    )


def summarize_snapshot(
    snapshot_path: Path,
) -> tuple[TableSummary, TableSummary, str]:
    with closing(sqlite3.connect(snapshot_path)) as connection:
        connection.row_factory = sqlite3.Row
        ble = _summarize_table(connection, "ble_address_observations")
        wifi = _summarize_table(connection, "wifi_address_observations")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    return ble, wifi, str(integrity)


def create_snapshot(
    *,
    database: Path,
    output_dir: Path,
    scanner_id: str,
    snapshot_taken_at: datetime,
    hostname: str,
) -> tuple[Path, Path, SnapshotManifest]:
    if not database.exists():
        raise SnapshotError(f"Database does not exist: {database}")
    validate_scanner_id(scanner_id)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{scanner_id}__{compact_utc_timestamp(snapshot_taken_at)}"
    snapshot_path = output_dir / f"{stem}.sqlite3"
    manifest_path = output_dir / f"{stem}.json"

    take_snapshot(database, snapshot_path)
    ble, wifi, integrity = summarize_snapshot(snapshot_path)
    digest = sha256_file(snapshot_path)

    manifest = SnapshotManifest(
        scanner_id=scanner_id,
        hostname=hostname,
        snapshot_taken_at_utc=snapshot_taken_at.astimezone(UTC).isoformat(),
        database_source=str(database),
        row_count=ble.row_count,
        unique_addresses=ble.unique_addresses,
        observed_at_utc_min=ble.observed_at_utc_min,
        observed_at_utc_max=ble.observed_at_utc_max,
        sha256=digest,
        integrity=integrity,
        package_version=__version__,
        wifi_row_count=wifi.row_count,
        wifi_unique_addresses=wifi.unique_addresses,
        wifi_observed_at_utc_min=wifi.observed_at_utc_min,
        wifi_observed_at_utc_max=wifi.observed_at_utc_max,
    )
    manifest_path.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot_path, manifest_path, manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a SQLite snapshot of the BLE observation database "
            "alongside a JSON manifest describing it."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Source observation SQLite database.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the snapshot and manifest pair are written.",
    )
    parser.add_argument(
        "--scanner-id",
        default=None,
        help=(
            "Stable scanner identifier. Defaults to the contents of "
            f"{DEFAULT_SCANNER_ID_FILE}, which is written once at bootstrap."
        ),
    )
    parser.add_argument(
        "--scanner-id-file",
        type=Path,
        default=DEFAULT_SCANNER_ID_FILE,
        help="Path to the scanner identity file (used when --scanner-id is not given).",
    )
    args = parser.parse_args()

    snapshot_taken_at = utc_now()
    try:
        scanner_id = (
            validate_scanner_id(args.scanner_id)
            if args.scanner_id
            else read_scanner_id_file(args.scanner_id_file)
        )
        snapshot_path, manifest_path, manifest = create_snapshot(
            database=args.database,
            output_dir=args.output_dir,
            scanner_id=scanner_id,
            snapshot_taken_at=snapshot_taken_at,
            hostname=socket.gethostname(),
        )
    except SnapshotError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        json.dumps(
            {
                "snapshot_path": str(snapshot_path),
                "manifest_path": str(manifest_path),
                "manifest": asdict(manifest),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
