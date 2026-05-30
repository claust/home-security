from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from home_security_api.dependencies import ConnectionDep
from home_security_api.models import IngestRecord, ScannerDetail, ScannerSummary

router = APIRouter(prefix="/scanners", tags=["scanners"])


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@router.get(
    "",
    response_model=list[ScannerSummary],
    summary="List scanners with totals",
)
def list_scanners(connection: ConnectionDep) -> list[ScannerSummary]:
    rows = connection.execute(
        """
        SELECT
          scanner_id,
          COUNT(*) AS observations,
          COUNT(DISTINCT address_observed) AS distinct_addresses,
          MIN(observed_at_utc) AS first_obs,
          MAX(observed_at_utc) AS last_obs
        FROM ble_address_observations
        GROUP BY scanner_id
        ORDER BY scanner_id
        """
    ).fetchall()
    return [
        ScannerSummary(
            scanner_id=row["scanner_id"],
            observations=row["observations"],
            distinct_addresses=row["distinct_addresses"],
            first_observed_utc=_parse(row["first_obs"]),
            last_observed_utc=_parse(row["last_obs"]),
        )
        for row in rows
    ]


@router.get(
    "/{scanner_id}",
    response_model=ScannerDetail,
    summary="Per-scanner detail with recent ingests",
    responses={404: {"description": "Unknown scanner_id"}},
)
def scanner_detail(
    connection: ConnectionDep,
    scanner_id: Annotated[
        str,
        Path(min_length=1, max_length=128, examples=["pi-livingroom"]),
    ],
    recent_ingests: Annotated[int, Query(ge=0, le=100)] = 10,
) -> ScannerDetail:
    summary = connection.execute(
        """
        SELECT
          scanner_id,
          COUNT(*) AS observations,
          COUNT(DISTINCT address_observed) AS distinct_addresses,
          MIN(observed_at_utc) AS first_obs,
          MAX(observed_at_utc) AS last_obs
        FROM ble_address_observations
        WHERE scanner_id = ?
        GROUP BY scanner_id
        """,
        (scanner_id,),
    ).fetchone()
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown scanner_id: {scanner_id}",
        )

    hostname_row = connection.execute(
        """
        SELECT hostname
        FROM snapshot_ingests
        WHERE scanner_id = ?
        ORDER BY ingested_at_utc DESC
        LIMIT 1
        """,
        (scanner_id,),
    ).fetchone()

    ingest_rows = connection.execute(
        """
        SELECT snapshot_taken_at_utc, ingested_at_utc,
               rows_in_snapshot, rows_inserted, rows_skipped,
               pi_package_version
        FROM snapshot_ingests
        WHERE scanner_id = ?
        ORDER BY ingested_at_utc DESC
        LIMIT ?
        """,
        (scanner_id, recent_ingests),
    ).fetchall()

    return ScannerDetail(
        scanner_id=summary["scanner_id"],
        observations=summary["observations"],
        distinct_addresses=summary["distinct_addresses"],
        first_observed_utc=_parse(summary["first_obs"]),
        last_observed_utc=_parse(summary["last_obs"]),
        hostname=hostname_row["hostname"] if hostname_row else None,
        recent_ingests=[
            IngestRecord(
                snapshot_taken_at_utc=datetime.fromisoformat(
                    row["snapshot_taken_at_utc"]
                ),
                ingested_at_utc=datetime.fromisoformat(row["ingested_at_utc"]),
                rows_in_snapshot=row["rows_in_snapshot"],
                rows_inserted=row["rows_inserted"],
                rows_skipped=row["rows_skipped"],
                pi_package_version=row["pi_package_version"],
            )
            for row in ingest_rows
        ],
    )
