from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCANNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_FIELDS = (
    "scanner_id",
    "hostname",
    "snapshot_taken_at_utc",
    "database_source",
    "row_count",
    "unique_addresses",
    "observed_at_utc_min",
    "observed_at_utc_max",
    "sha256",
    "integrity",
    "package_version",
)


class ManifestError(ValueError):
    """Raised when a snapshot manifest fails validation."""


@dataclass(frozen=True)
class Manifest:
    scanner_id: str
    hostname: str
    snapshot_taken_at_utc: str
    database_source: str
    row_count: int
    unique_addresses: int
    observed_at_utc_min: str | None
    observed_at_utc_max: str | None
    sha256: str
    integrity: str
    package_version: str

    @classmethod
    def from_path(cls, path: Path) -> Manifest:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(f"Manifest is not valid JSON: {path}") from exc
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Manifest:
        missing = [field for field in REQUIRED_FIELDS if field not in payload]
        if missing:
            raise ManifestError(
                "Manifest is missing required fields: " + ", ".join(sorted(missing))
            )

        scanner_id = payload["scanner_id"]
        if not isinstance(scanner_id, str) or not SCANNER_ID_PATTERN.fullmatch(
            scanner_id
        ):
            raise ManifestError(f"Manifest has invalid scanner_id: {scanner_id!r}")

        sha256 = payload["sha256"]
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            raise ManifestError(f"Manifest has invalid sha256: {sha256!r}")

        row_count = payload["row_count"]
        if not isinstance(row_count, int) or row_count < 0:
            raise ManifestError(f"Manifest has invalid row_count: {row_count!r}")

        unique_addresses = payload["unique_addresses"]
        if not isinstance(unique_addresses, int) or unique_addresses < 0:
            raise ManifestError(
                f"Manifest has invalid unique_addresses: {unique_addresses!r}"
            )

        return cls(
            scanner_id=scanner_id,
            hostname=str(payload["hostname"]),
            snapshot_taken_at_utc=str(payload["snapshot_taken_at_utc"]),
            database_source=str(payload["database_source"]),
            row_count=row_count,
            unique_addresses=unique_addresses,
            observed_at_utc_min=_optional_str(payload["observed_at_utc_min"]),
            observed_at_utc_max=_optional_str(payload["observed_at_utc_max"]),
            sha256=sha256,
            integrity=str(payload["integrity"]),
            package_version=str(payload["package_version"]),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
