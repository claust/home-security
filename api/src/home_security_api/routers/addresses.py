from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, status

from home_security_api.db import (
    SERVICES_PER_ADDRESS_CTE,
    VENDORS_PER_ADDRESS_CTE,
    split_concat,
)
from home_security_api.dependencies import ConnectionDep
from home_security_api.models import (
    AddressSummary,
    Observation,
    Page,
)
from home_security_api.pagination import decode_cursor, encode_cursor

router = APIRouter(prefix="/addresses", tags=["addresses"])


SortKey = Literal["last_seen", "first_seen", "observations"]


_SORT_COLUMN: dict[SortKey, str] = {
    "last_seen": "last_observed_utc",
    "first_seen": "first_observed_utc",
    "observations": "observations",
}


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@router.get(
    "",
    response_model=Page[AddressSummary],
    summary="Paginated, filterable list of addresses",
)
def list_addresses(
    connection: ConnectionDep,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=128,
            description="Substring match on address, name, or local_name.",
        ),
    ] = None,
    scanner_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    seen_since: Annotated[
        datetime | None,
        Query(description="Only addresses last seen at or after this UTC instant."),
    ] = None,
    sort: Annotated[SortKey, Query()] = "last_seen",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[AddressSummary]:
    sort_column = _SORT_COLUMN[sort]

    where: list[str] = []
    params: list[object] = []
    if q is not None:
        where.append(
            "(o.address_observed LIKE ? OR o.name LIKE ? OR o.local_name LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])

    having: list[str] = []
    if scanner_id is not None:
        having.append("SUM(CASE WHEN o.scanner_id = ? THEN 1 ELSE 0 END) > 0")
        params.append(scanner_id)
    if seen_since is not None:
        having.append("MAX(o.observed_at_utc) >= ?")
        params.append(seen_since.isoformat())

    cursor_payload = decode_cursor(cursor) if cursor else None
    if cursor_payload is not None:
        cur_value = cursor_payload.get("v")
        cur_address = cursor_payload.get("a")
        if cur_value is None or cur_address is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid cursor",
            )
        # Keyset: same ordering as the ORDER BY below.
        having.append(
            f"({sort_column} < ? OR ({sort_column} = ? AND o.address_observed > ?))"
        )
        params.extend([cur_value, cur_value, cur_address])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    having_sql = f"HAVING {' AND '.join(having)}" if having else ""

    sql = f"""
    WITH
    {VENDORS_PER_ADDRESS_CTE},
    {SERVICES_PER_ADDRESS_CTE}
    SELECT
      o.address_observed AS address,
      MAX(o.name) AS name,
      MAX(o.local_name) AS local_name,
      v.vendors,
      sv.services,
      GROUP_CONCAT(DISTINCT o.scanner_id) AS scanners,
      COUNT(*) AS observations,
      MIN(o.observed_at_utc) AS first_observed_utc,
      MAX(o.observed_at_utc) AS last_observed_utc
    FROM ble_address_observations o
    LEFT JOIN vendors_per_address v ON v.address_observed = o.address_observed
    LEFT JOIN services_per_address sv ON sv.address_observed = o.address_observed
    {where_sql}
    GROUP BY o.address_observed
    {having_sql}
    ORDER BY {sort_column} DESC, address ASC
    LIMIT ?
    """
    params.append(limit + 1)

    rows = connection.execute(sql, params).fetchall()
    page_rows = rows[:limit]

    items = [
        AddressSummary(
            address=row["address"],
            name=row["name"],
            local_name=row["local_name"],
            vendors=split_concat(row["vendors"]),
            services=split_concat(row["services"]),
            scanners=_split_scanners(row["scanners"]),
            observations=row["observations"],
            first_observed_utc=datetime.fromisoformat(row["first_observed_utc"]),
            last_observed_utc=datetime.fromisoformat(row["last_observed_utc"]),
        )
        for row in page_rows
    ]

    next_cursor: str | None = None
    if len(rows) > limit:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {
                "v": last[sort_column],
                "a": last["address"],
            }
        )

    return Page[AddressSummary](items=items, next_cursor=next_cursor)


@router.get(
    "/{address}",
    response_model=AddressSummary,
    summary="Single-address summary",
    responses={404: {"description": "Address not present in archive"}},
)
def address_detail(
    connection: ConnectionDep,
    address: Annotated[
        str,
        Path(min_length=1, max_length=64, examples=["AA:BB:CC:DD:EE:FF"]),
    ],
) -> AddressSummary:
    sql = f"""
    WITH
    {VENDORS_PER_ADDRESS_CTE},
    {SERVICES_PER_ADDRESS_CTE}
    SELECT
      o.address_observed AS address,
      MAX(o.name) AS name,
      MAX(o.local_name) AS local_name,
      v.vendors,
      sv.services,
      GROUP_CONCAT(DISTINCT o.scanner_id) AS scanners,
      COUNT(*) AS observations,
      MIN(o.observed_at_utc) AS first_observed_utc,
      MAX(o.observed_at_utc) AS last_observed_utc
    FROM ble_address_observations o
    LEFT JOIN vendors_per_address v ON v.address_observed = o.address_observed
    LEFT JOIN services_per_address sv ON sv.address_observed = o.address_observed
    WHERE o.address_observed = ?
    GROUP BY o.address_observed
    """
    row = connection.execute(sql, (address,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown address: {address}",
        )
    return AddressSummary(
        address=row["address"],
        name=row["name"],
        local_name=row["local_name"],
        vendors=split_concat(row["vendors"]),
        services=split_concat(row["services"]),
        scanners=_split_scanners(row["scanners"]),
        observations=row["observations"],
        first_observed_utc=datetime.fromisoformat(row["first_observed_utc"]),
        last_observed_utc=datetime.fromisoformat(row["last_observed_utc"]),
    )


@router.get(
    "/{address}/observations",
    response_model=Page[Observation],
    summary="Observation timeline for one address",
)
def address_observations(
    connection: ConnectionDep,
    address: Annotated[
        str,
        Path(min_length=1, max_length=64),
    ],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[Observation]:
    where = ["address_observed = ?"]
    params: list[object] = [address]
    if since is not None:
        where.append("observed_at_utc >= ?")
        params.append(since.isoformat())
    if until is not None:
        where.append("observed_at_utc < ?")
        params.append(until.isoformat())

    cursor_payload = decode_cursor(cursor) if cursor else None
    if cursor_payload is not None:
        cur_t = cursor_payload.get("t")
        cur_s = cursor_payload.get("s")
        if cur_t is None or cur_s is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid cursor",
            )
        where.append(
            "(observed_at_utc < ? OR (observed_at_utc = ? AND scanner_id > ?))"
        )
        params.extend([cur_t, cur_t, cur_s])

    sql = f"""
    SELECT observed_at_utc, scanner_id, address_observed, rssi,
           name, local_name, service_uuids_json, manufacturer_data_json
    FROM ble_address_observations
    WHERE {" AND ".join(where)}
    ORDER BY observed_at_utc DESC, scanner_id ASC
    LIMIT ?
    """
    params.append(limit + 1)
    rows = connection.execute(sql, params).fetchall()
    page_rows = rows[:limit]

    items = [_row_to_observation(row) for row in page_rows]
    next_cursor: str | None = None
    if len(rows) > limit:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"t": last["observed_at_utc"], "s": last["scanner_id"]}
        )
    return Page[Observation](items=items, next_cursor=next_cursor)


def _split_scanners(value: str | None) -> list[str]:
    """GROUP_CONCAT(DISTINCT ...) only supports the default ',' separator."""
    if not value:
        return []
    return [item for item in value.split(",") if item]


def _row_to_observation(row) -> Observation:  # noqa: ANN001 - sqlite3.Row
    return Observation(
        observed_at_utc=datetime.fromisoformat(row["observed_at_utc"]),
        scanner_id=row["scanner_id"],
        address=row["address_observed"],
        rssi=row["rssi"],
        name=row["name"],
        local_name=row["local_name"],
        service_uuids=json.loads(row["service_uuids_json"] or "[]"),
        manufacturer_data=json.loads(row["manufacturer_data_json"] or "{}"),
    )
