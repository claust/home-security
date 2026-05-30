from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, status

from home_security_api.dependencies import ConnectionDep
from home_security_api.models import (
    Page,
    WifiAddressSummary,
    WifiObservation,
    WifiOverview,
)
from home_security_api.pagination import decode_cursor, encode_cursor

router = APIRouter(prefix="/wifi", tags=["wifi"])


SortKey = Literal["last_seen", "first_seen", "observations"]

_SORT_COLUMN: dict[SortKey, str] = {
    "last_seen": "last_observed_utc",
    "first_seen": "first_observed_utc",
    "observations": "observations",
}


def _split(value: str | None) -> list[str]:
    """GROUP_CONCAT(DISTINCT ...) only supports the default ',' separator."""
    if not value:
        return []
    return [item for item in value.split(",") if item]


def _split_channels(value: str | None) -> list[int]:
    return sorted({int(item) for item in _split(value)})


def _row_to_observation(row) -> WifiObservation:  # noqa: ANN001 - sqlite3.Row
    return WifiObservation(
        observed_at_utc=datetime.fromisoformat(row["observed_at_utc"]),
        scanner_id=row["scanner_id"],
        address=row["address_observed"],
        frame_type=row["frame_type"],
        ssid=row["ssid"],
        rssi=row["rssi"],
        channel=row["channel"],
        is_randomized_mac=bool(row["is_randomized_mac"]),
        information_elements=json.loads(row["information_elements_json"] or "{}"),
    )


@router.get(
    "/stats/overview",
    response_model=WifiOverview,
    summary="Global Wi-Fi counts and time range",
)
def overview(connection: ConnectionDep) -> WifiOverview:
    row = connection.execute(
        """
        SELECT
          COUNT(*) AS total,
          COUNT(DISTINCT address_observed) AS distinct_addrs,
          COUNT(DISTINCT CASE WHEN is_randomized_mac = 1
                THEN address_observed END) AS randomized_addrs,
          COUNT(DISTINCT scanner_id) AS scanners,
          MIN(observed_at_utc) AS first_obs,
          MAX(observed_at_utc) AS last_obs
        FROM wifi_address_observations
        """
    ).fetchone()
    return WifiOverview(
        total_observations=row["total"],
        distinct_addresses=row["distinct_addrs"],
        randomized_addresses=row["randomized_addrs"],
        scanner_count=row["scanners"],
        first_observed_utc=_parse(row["first_obs"]),
        last_observed_utc=_parse(row["last_obs"]),
    )


@router.get(
    "/observations",
    response_model=Page[WifiObservation],
    summary="Recent Wi-Fi frames across all scanners",
)
def list_observations(
    connection: ConnectionDep,
    scanner_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    address: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    frame_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    ssid: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[WifiObservation]:
    where: list[str] = []
    params: list[object] = []
    if scanner_id is not None:
        where.append("scanner_id = ?")
        params.append(scanner_id)
    if address is not None:
        where.append("address_observed = ?")
        params.append(address)
    if frame_type is not None:
        where.append("frame_type = ?")
        params.append(frame_type)
    if ssid is not None:
        where.append("ssid = ?")
        params.append(ssid)
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
    SELECT observed_at_utc, scanner_id, address_observed, frame_type, ssid,
           rssi, channel, is_randomized_mac, information_elements_json
    FROM wifi_address_observations
    {where_sql}
    ORDER BY observed_at_utc DESC, scanner_id ASC, address_observed ASC
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
            {
                "t": last["observed_at_utc"],
                "s": last["scanner_id"],
                "a": last["address_observed"],
            }
        )
    return Page[WifiObservation](items=items, next_cursor=next_cursor)


@router.get(
    "/addresses",
    response_model=Page[WifiAddressSummary],
    summary="Paginated, filterable list of Wi-Fi transmitter MACs",
)
def list_addresses(
    connection: ConnectionDep,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=128, description="Substring match on MAC."),
    ] = None,
    scanner_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    randomized: Annotated[
        bool | None,
        Query(description="Filter to randomized (true) or stable (false) MACs."),
    ] = None,
    seen_since: Annotated[datetime | None, Query()] = None,
    sort: Annotated[SortKey, Query()] = "last_seen",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[WifiAddressSummary]:
    sort_column = _SORT_COLUMN[sort]

    where: list[str] = []
    params: list[object] = []
    if q is not None:
        where.append("address_observed LIKE ?")
        params.append(f"%{q}%")
    if randomized is not None:
        where.append("is_randomized_mac = ?")
        params.append(1 if randomized else 0)

    having: list[str] = []
    if scanner_id is not None:
        having.append("SUM(CASE WHEN scanner_id = ? THEN 1 ELSE 0 END) > 0")
        params.append(scanner_id)
    if seen_since is not None:
        having.append("MAX(observed_at_utc) >= ?")
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
        having.append(
            f"({sort_column} < ? OR ({sort_column} = ? AND address_observed > ?))"
        )
        params.extend([cur_value, cur_value, cur_address])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    having_sql = f"HAVING {' AND '.join(having)}" if having else ""
    sql = f"""
    SELECT
      address_observed AS address,
      MAX(is_randomized_mac) AS is_randomized_mac,
      GROUP_CONCAT(DISTINCT ssid) AS ssids,
      GROUP_CONCAT(DISTINCT frame_type) AS frame_types,
      GROUP_CONCAT(DISTINCT channel) AS channels,
      GROUP_CONCAT(DISTINCT scanner_id) AS scanners,
      COUNT(*) AS observations,
      MIN(observed_at_utc) AS first_observed_utc,
      MAX(observed_at_utc) AS last_observed_utc
    FROM wifi_address_observations
    {where_sql}
    GROUP BY address_observed
    {having_sql}
    ORDER BY {sort_column} DESC, address ASC
    LIMIT ?
    """
    params.append(limit + 1)
    rows = connection.execute(sql, params).fetchall()
    page_rows = rows[:limit]

    items = [_row_to_summary(row) for row in page_rows]
    next_cursor: str | None = None
    if len(rows) > limit:
        last = page_rows[-1]
        next_cursor = encode_cursor({"v": last[sort_column], "a": last["address"]})
    return Page[WifiAddressSummary](items=items, next_cursor=next_cursor)


@router.get(
    "/addresses/{address}",
    response_model=WifiAddressSummary,
    summary="Single Wi-Fi MAC summary",
    responses={404: {"description": "Address not present in archive"}},
)
def address_detail(
    connection: ConnectionDep,
    address: Annotated[
        str,
        Path(min_length=1, max_length=64, examples=["a4:83:e7:00:11:22"]),
    ],
) -> WifiAddressSummary:
    row = connection.execute(
        """
        SELECT
          address_observed AS address,
          MAX(is_randomized_mac) AS is_randomized_mac,
          GROUP_CONCAT(DISTINCT ssid) AS ssids,
          GROUP_CONCAT(DISTINCT frame_type) AS frame_types,
          GROUP_CONCAT(DISTINCT channel) AS channels,
          GROUP_CONCAT(DISTINCT scanner_id) AS scanners,
          COUNT(*) AS observations,
          MIN(observed_at_utc) AS first_observed_utc,
          MAX(observed_at_utc) AS last_observed_utc
        FROM wifi_address_observations
        WHERE address_observed = :address
        GROUP BY address_observed
        """,
        {"address": address},
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown address: {address}",
        )
    return _row_to_summary(row)


@router.get(
    "/addresses/{address}/observations",
    response_model=Page[WifiObservation],
    summary="Frame timeline for one Wi-Fi MAC",
)
def address_observations(
    connection: ConnectionDep,
    address: Annotated[str, Path(min_length=1, max_length=64)],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[WifiObservation]:
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
    SELECT observed_at_utc, scanner_id, address_observed, frame_type, ssid,
           rssi, channel, is_randomized_mac, information_elements_json
    FROM wifi_address_observations
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
    return Page[WifiObservation](items=items, next_cursor=next_cursor)


def _row_to_summary(row) -> WifiAddressSummary:  # noqa: ANN001 - sqlite3.Row
    return WifiAddressSummary(
        address=row["address"],
        is_randomized_mac=bool(row["is_randomized_mac"]),
        ssids=_split(row["ssids"]),
        frame_types=_split(row["frame_types"]),
        channels=_split_channels(row["channels"]),
        scanners=_split(row["scanners"]),
        observations=row["observations"],
        first_observed_utc=datetime.fromisoformat(row["first_observed_utc"]),
        last_observed_utc=datetime.fromisoformat(row["last_observed_utc"]),
    )


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
