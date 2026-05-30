from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from home_security_api.dependencies import ConnectionDep
from home_security_api.models import HourlyBucket, VendorBucket

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    "/hourly",
    response_model=list[HourlyBucket],
    summary="Observations per scanner per UTC hour",
)
def hourly(
    connection: ConnectionDep,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    scanner_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 168,
) -> list[HourlyBucket]:
    where: list[str] = []
    params: list[object] = []
    if since is not None:
        where.append("observed_at_utc >= ?")
        params.append(since.isoformat())
    if until is not None:
        where.append("observed_at_utc < ?")
        params.append(until.isoformat())
    if scanner_id is not None:
        where.append("scanner_id = ?")
        params.append(scanner_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    sql = f"""
    SELECT
      substr(observed_at_utc, 1, 13) || ':00:00+00:00' AS hour_utc,
      scanner_id,
      COUNT(*) AS observations,
      COUNT(DISTINCT address_observed) AS distinct_addresses
    FROM ble_address_observations
    {where_sql}
    GROUP BY hour_utc, scanner_id
    ORDER BY hour_utc DESC, scanner_id ASC
    LIMIT ?
    """
    params.append(limit)
    rows = connection.execute(sql, params).fetchall()
    return [
        HourlyBucket(
            hour_utc=datetime.fromisoformat(row["hour_utc"]),
            scanner_id=row["scanner_id"],
            observations=row["observations"],
            distinct_addresses=row["distinct_addresses"],
        )
        for row in rows
    ]


@router.get(
    "/vendors",
    response_model=list[VendorBucket],
    summary="Manufacturer-data company-ID breakdown",
)
def vendors(
    connection: ConnectionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[VendorBucket]:
    rows = connection.execute(
        """
        SELECT
          m.key AS company_id_hex,
          COALESCE(c.name, '(unknown)') AS vendor,
          COUNT(*) AS observations,
          COUNT(DISTINCT o.address_observed) AS distinct_addresses
        FROM ble_address_observations o,
             json_each(o.manufacturer_data_json) m
        LEFT JOIN company_identifiers c
          ON c.company_id_hex = m.key
        GROUP BY m.key
        ORDER BY observations DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        VendorBucket(
            company_id_hex=row["company_id_hex"],
            vendor=row["vendor"],
            observations=row["observations"],
            distinct_addresses=row["distinct_addresses"],
        )
        for row in rows
    ]
