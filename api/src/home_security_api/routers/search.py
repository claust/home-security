from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from home_security_api.dependencies import ConnectionDep
from home_security_api.models import SearchHit

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=list[SearchHit],
    summary="Unified search across addresses, names, vendors, and services",
)
def search(
    connection: ConnectionDep,
    q: Annotated[str, Query(min_length=1, max_length=128)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[SearchHit]:
    like = f"%{q}%"

    # Addresses (and addresses that match by name) - take latest observation
    address_rows = connection.execute(
        """
        SELECT
          address_observed AS address,
          MAX(name) AS name,
          MAX(local_name) AS local_name,
          MAX(observed_at_utc) AS last_observed_utc
        FROM ble_address_observations
        WHERE address_observed LIKE ?
           OR name LIKE ?
           OR local_name LIKE ?
        GROUP BY address_observed
        ORDER BY last_observed_utc DESC
        LIMIT ?
        """,
        (like, like, like, limit),
    ).fetchall()

    hits: list[SearchHit] = []
    for row in address_rows:
        kind = "name" if (row["name"] or row["local_name"]) else "address"
        label = row["name"] or row["local_name"] or row["address"]
        detail = (
            row["address"] if label != row["address"] else (row["local_name"] or None)
        )
        hits.append(
            SearchHit(
                kind=kind,  # type: ignore[arg-type]
                address=row["address"],
                label=label,
                detail=detail,
                last_observed_utc=datetime.fromisoformat(row["last_observed_utc"]),
            )
        )

    if len(hits) < limit:
        vendor_rows = connection.execute(
            """
            SELECT company_id_hex, name
            FROM company_identifiers
            WHERE name LIKE ?
            ORDER BY name
            LIMIT ?
            """,
            (like, limit - len(hits)),
        ).fetchall()
        hits.extend(
            SearchHit(
                kind="vendor",
                label=row["name"],
                detail=f"company_id 0x{row['company_id_hex']}",
            )
            for row in vendor_rows
        )

    if len(hits) < limit:
        service_rows = connection.execute(
            """
            SELECT uuid_hex, name, kind
            FROM service_uuids
            WHERE name LIKE ?
            ORDER BY name
            LIMIT ?
            """,
            (like, limit - len(hits)),
        ).fetchall()
        hits.extend(
            SearchHit(
                kind="service",
                label=row["name"],
                detail=f"{row['kind']} uuid 0x{row['uuid_hex']}",
            )
            for row in service_rows
        )

    return hits
