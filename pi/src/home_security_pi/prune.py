from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_DATABASE = Path.home() / ".local/state/home-security/observations.sqlite3"
DEFAULT_KEEP_LAST_DAYS = 14
BUSY_TIMEOUT_MS = 5000


class PruneError(RuntimeError):
    """Raised when a prune cannot be completed."""


@dataclass(frozen=True)
class PruneResult:
    database: str
    requested_before_utc: str
    effective_before_utc: str
    keep_last_days: int
    rows_deleted: int
    pruned_at_utc: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_iso_utc(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PruneError(f"--before is not an ISO timestamp: {value!r}") from exc
    if moment.tzinfo is None:
        raise PruneError(
            f"--before must include a timezone offset (e.g. +00:00): {value!r}"
        )
    return moment.astimezone(UTC)


def compute_effective_before(
    *,
    requested_before: datetime,
    keep_last_days: int,
    now: datetime,
) -> datetime:
    if keep_last_days < 0:
        raise PruneError(f"--keep-last-days must be >= 0: {keep_last_days}")
    floor = now - timedelta(days=keep_last_days)
    return min(requested_before, floor)


def prune_observations(
    *,
    database: Path,
    requested_before: datetime,
    keep_last_days: int,
    now: datetime,
) -> PruneResult:
    if not database.exists():
        raise PruneError(f"Database does not exist: {database}")

    effective_before = compute_effective_before(
        requested_before=requested_before,
        keep_last_days=keep_last_days,
        now=now,
    )
    effective_before_iso = effective_before.isoformat()

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        cursor = connection.execute(
            """
            DELETE FROM ble_address_observations
            WHERE observed_at_utc <= ?
            """,
            (effective_before_iso,),
        )
        rows_deleted = cursor.rowcount
        connection.commit()

    return PruneResult(
        database=str(database),
        requested_before_utc=requested_before.isoformat(),
        effective_before_utc=effective_before_iso,
        keep_last_days=keep_last_days,
        rows_deleted=int(rows_deleted),
        pruned_at_utc=now.isoformat(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Delete BLE address observations confirmed-ingested by the hub. "
            "A safety floor (--keep-last-days) caps how recent rows can be "
            "regardless of the --before watermark."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Observation SQLite database to prune.",
    )
    parser.add_argument(
        "--before",
        required=True,
        help=(
            "ISO 8601 UTC timestamp; rows with observed_at_utc <= this are "
            "candidates for deletion."
        ),
    )
    parser.add_argument(
        "--keep-last-days",
        type=int,
        default=DEFAULT_KEEP_LAST_DAYS,
        help=(
            "Always keep observations from the last N days, regardless of "
            "--before. Defaults to %(default)s."
        ),
    )
    args = parser.parse_args()

    try:
        requested_before = parse_iso_utc(args.before)
        result = prune_observations(
            database=args.database,
            requested_before=requested_before,
            keep_last_days=args.keep_last_days,
            now=utc_now(),
        )
    except PruneError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
