from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from home_security_api.dependencies import ConnectionDep
from home_security_api.models import Observation, Page
from home_security_api.pagination import decode_cursor, encode_cursor

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get(
    "",
    response_model=Page[Observation],
    summary="Recent observations across all scanners",
)
def list_observations(
    connection: ConnectionDep,
    scanner_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    address: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[Observation]:
    where: list[str] = []
    params: list[object] = []
    if scanner_id is not None:
        where.append("scanner_id = ?")
        params.append(scanner_id)
    if address is not None:
        where.append("address_observed = ?")
        params.append(address)
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
        cur_a = cursor_payload.get("a")
        if cur_t is None or cur_s is None or cur_a is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid cursor",
            )
        where.append(
            """(
                observed_at_utc < ?
                OR (observed_at_utc = ? AND scanner_id > ?)
                OR (observed_at_utc = ? AND scanner_id = ? AND address_observed > ?)
            )"""
        )
        params.extend([cur_t, cur_t, cur_s, cur_t, cur_s, cur_a])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
    SELECT observed_at_utc, scanner_id, address_observed, rssi,
           name, local_name, service_uuids_json, manufacturer_data_json
    FROM ble_address_observations
    {where_sql}
    ORDER BY observed_at_utc DESC, scanner_id ASC, address_observed ASC
    LIMIT ?
    """
    params.append(limit + 1)
    rows = connection.execute(sql, params).fetchall()
    page_rows = rows[:limit]

    items = [
        Observation(
            observed_at_utc=datetime.fromisoformat(row["observed_at_utc"]),
            scanner_id=row["scanner_id"],
            address=row["address_observed"],
            rssi=row["rssi"],
            name=row["name"],
            local_name=row["local_name"],
            service_uuids=json.loads(row["service_uuids_json"] or "[]"),
            manufacturer_data=json.loads(row["manufacturer_data_json"] or "{}"),
        )
        for row in page_rows
    ]
    next_cursor: str | None = None
    if len(rows) > limit:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {
                "t": last["observed_at_utc"],
                "s": last["scanner_id"],
                "a": last["address_observed"],
            }
        )
    return Page[Observation](items=items, next_cursor=next_cursor)
