from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def open_readonly(archive_path: Path) -> sqlite3.Connection:
    """Open the archive in read-only mode via SQLite URI."""
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found at {archive_path}")
    uri = f"file:{archive_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


@contextmanager
def cursor(connection: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    cur = connection.cursor()
    try:
        yield cur
    finally:
        cur.close()


# Reusable SQL fragments matching the joins used in
# hub/datasette-metadata.yaml. The 16-bit short UUID is extracted from any
# advertised UUID that matches the Bluetooth SIG base UUID
# (xxxxxxxx-0000-1000-8000-00805f9b34fb).
SHORT_UUID_EXPR = """
CASE
  WHEN lower(s.value) LIKE '0000____-0000-1000-8000-00805f9b34fb'
    THEN substr(lower(s.value), 5, 4)
END
""".strip()


def vendors_per_address_cte(*, scoped: bool = False) -> str:
    """Build the `vendors_per_address` CTE.

    When ``scoped`` is true the inner scans are restricted to a single
    ``:address`` bound parameter, so a per-address lookup no longer pays a
    full-table ``json_each`` expansion over every observation.
    """
    mfr_filter = "WHERE o.address_observed = :address" if scoped else ""
    svc_filter = "AND o.address_observed = :address" if scoped else ""
    return f"""
vendors_per_address AS (
  SELECT address_observed, GROUP_CONCAT(vendor, ' | ') AS vendors
  FROM (
    SELECT DISTINCT
      o.address_observed,
      COALESCE(c.name, '0x' || m.key) AS vendor
    FROM ble_address_observations o,
         json_each(o.manufacturer_data_json) m
    LEFT JOIN company_identifiers c
      ON c.company_id_hex = m.key
    {mfr_filter}
    UNION
    SELECT DISTINCT
      o.address_observed,
      u.name AS vendor
    FROM ble_address_observations o,
         json_each(o.service_uuids_json) s
    JOIN service_uuids u
      ON u.uuid_hex = {SHORT_UUID_EXPR}
    WHERE u.kind = 'member' {svc_filter}
  )
  GROUP BY address_observed
)
""".strip()


def services_per_address_cte(*, scoped: bool = False) -> str:
    """Build the `services_per_address` CTE; see :func:`vendors_per_address_cte`."""
    svc_filter = "AND o.address_observed = :address" if scoped else ""
    return f"""
services_per_address AS (
  SELECT address_observed, GROUP_CONCAT(service, ' | ') AS services
  FROM (
    SELECT DISTINCT
      o.address_observed,
      u.name AS service
    FROM ble_address_observations o,
         json_each(o.service_uuids_json) s
    JOIN service_uuids u
      ON u.uuid_hex = {SHORT_UUID_EXPR}
    WHERE u.kind = 'sig' {svc_filter}
  )
  GROUP BY address_observed
)
""".strip()


# Unscoped fragments for the full-table list query, where every address is
# grouped anyway.
VENDORS_PER_ADDRESS_CTE = vendors_per_address_cte()
SERVICES_PER_ADDRESS_CTE = services_per_address_cte()


def split_concat(value: str | None) -> list[str]:
    """Turn a GROUP_CONCAT(... , ' | ') result into a list."""
    if not value:
        return []
    return [item for item in value.split(" | ") if item]
