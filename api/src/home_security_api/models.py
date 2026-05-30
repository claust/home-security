from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT")


class _Model(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class Health(_Model):
    status: Literal["ok"] = "ok"
    archive_path: str
    archive_size_bytes: int
    archive_modified_at_utc: datetime
    last_ingest_at_utc: datetime | None
    package_version: str


class Overview(_Model):
    total_observations: int
    distinct_addresses: int
    scanner_count: int
    first_observed_utc: datetime | None
    last_observed_utc: datetime | None
    last_ingest_at_utc: datetime | None


class ScannerSummary(_Model):
    scanner_id: str
    observations: int
    distinct_addresses: int
    first_observed_utc: datetime | None
    last_observed_utc: datetime | None


class IngestRecord(_Model):
    snapshot_taken_at_utc: datetime
    ingested_at_utc: datetime
    rows_in_snapshot: int
    rows_inserted: int
    rows_skipped: int
    pi_package_version: str


class ScannerDetail(ScannerSummary):
    hostname: str | None = None
    recent_ingests: list[IngestRecord] = Field(default_factory=list)


class AddressSummary(_Model):
    address: str = Field(description="BLE MAC address as observed.")
    name: str | None
    local_name: str | None
    vendors: list[str]
    services: list[str]
    scanners: list[str]
    observations: int
    first_observed_utc: datetime
    last_observed_utc: datetime


class Observation(_Model):
    observed_at_utc: datetime
    scanner_id: str
    address: str
    rssi: int | None
    name: str | None
    local_name: str | None
    service_uuids: list[str]
    manufacturer_data: dict[str, str]


class HourlyBucket(_Model):
    hour_utc: datetime
    scanner_id: str
    observations: int
    distinct_addresses: int


class VendorBucket(_Model):
    company_id_hex: str
    vendor: str
    observations: int
    distinct_addresses: int


class SearchHit(_Model):
    kind: Literal["address", "name", "vendor", "service"]
    address: str | None = None
    label: str
    detail: str | None = None
    last_observed_utc: datetime | None = None


class Page(_Model, Generic[ItemT]):
    items: list[ItemT]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor; pass to ?cursor= for the next page.",
    )
