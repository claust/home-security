from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

from home_security_api.dependencies import ConnectionDep, SettingsDep
from home_security_api.models import Health, Overview

router = APIRouter(tags=["meta"])


def _package_version() -> str:
    try:
        return version("home-security-api")
    except PackageNotFoundError:
        return "0.0.0+unknown"


@router.get("/health", response_model=Health, summary="Liveness check")
def health(settings: SettingsDep, connection: ConnectionDep) -> Health:
    archive_path = settings.archive_path
    stat = archive_path.stat()
    last_ingest_row = connection.execute(
        "SELECT MAX(ingested_at_utc) AS last_ingest FROM snapshot_ingests"
    ).fetchone()
    last_ingest_value: str | None = (
        last_ingest_row["last_ingest"] if last_ingest_row else None
    )
    last_ingest = (
        datetime.fromisoformat(last_ingest_value) if last_ingest_value else None
    )
    return Health(
        archive_path=str(archive_path),
        archive_size_bytes=stat.st_size,
        archive_modified_at_utc=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        last_ingest_at_utc=last_ingest,
        package_version=_package_version(),
    )


@router.get(
    "/stats/overview",
    response_model=Overview,
    summary="Global counts and time range",
    tags=["stats"],
)
def overview(connection: ConnectionDep) -> Overview:
    obs = connection.execute(
        """
        SELECT
          COUNT(*) AS total,
          COUNT(DISTINCT address_observed) AS distinct_addrs,
          COUNT(DISTINCT scanner_id) AS scanners,
          MIN(observed_at_utc) AS first_obs,
          MAX(observed_at_utc) AS last_obs
        FROM ble_address_observations
        """
    ).fetchone()
    last_ingest_row = connection.execute(
        "SELECT MAX(ingested_at_utc) AS last_ingest FROM snapshot_ingests"
    ).fetchone()
    return Overview(
        total_observations=obs["total"],
        distinct_addresses=obs["distinct_addrs"],
        scanner_count=obs["scanners"],
        first_observed_utc=_parse(obs["first_obs"]),
        last_observed_utc=_parse(obs["last_obs"]),
        last_ingest_at_utc=_parse(last_ingest_row["last_ingest"]),
    )


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
