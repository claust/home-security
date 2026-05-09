from __future__ import annotations

import argparse
import asyncio
import json
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class BLEDeviceLike(Protocol):
    address: str
    name: str | None


class AdvertisementLike(Protocol):
    local_name: str | None
    service_uuids: list[str]
    manufacturer_data: dict[int, bytes]


class BLEScanUnavailable(RuntimeError):
    """Raised when the BLE scanner cannot run on the current host."""


@dataclass(frozen=True)
class SeenBLEDevice:
    address: str
    name: str | None
    local_name: str | None
    rssi: int | None
    service_uuids: list[str]
    manufacturer_data: dict[str, str]


def _get_rssi(device: BLEDeviceLike, advertisement: AdvertisementLike) -> int | None:
    value = getattr(advertisement, "rssi", None)
    if value is None:
        value = getattr(device, "rssi", None)
    return value if isinstance(value, int) else None


def _normalize_manufacturer_data(
    raw: dict[int, bytes] | None,
) -> dict[str, str]:
    if not raw:
        return {}
    return {
        f"{int(company_id):04x}": bytes(payload).hex()
        for company_id, payload in raw.items()
    }


def normalize_seen_device(
    device: BLEDeviceLike,
    advertisement: AdvertisementLike,
) -> SeenBLEDevice:
    return SeenBLEDevice(
        address=device.address,
        name=device.name,
        local_name=advertisement.local_name,
        rssi=_get_rssi(device, advertisement),
        service_uuids=sorted(str(uuid) for uuid in advertisement.service_uuids),
        manufacturer_data=_normalize_manufacturer_data(
            getattr(advertisement, "manufacturer_data", None)
        ),
    )


def build_result(
    devices: list[SeenBLEDevice],
    *,
    started_at: datetime,
    finished_at: datetime,
    duration_seconds: float,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "source": "ble",
        "scanner": "bleak",
        "timestamp_utc": finished_at.isoformat(),
        "started_at_utc": started_at.isoformat(),
        "duration_seconds": round(duration_seconds, 3),
        "hostname": socket.gethostname(),
        "device_count": len(devices),
        "devices": [
            {
                "address": device.address,
                "name": device.name,
                "local_name": device.local_name,
                "rssi": device.rssi,
                "service_uuids": device.service_uuids,
                "manufacturer_data": device.manufacturer_data,
            }
            for device in sorted(devices, key=lambda item: item.address)
        ],
    }


def build_unavailable_result(
    *,
    started_at: datetime,
    finished_at: datetime,
    duration_seconds: float,
    error: Exception,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "source": "ble",
        "scanner": "bleak",
        "timestamp_utc": finished_at.isoformat(),
        "started_at_utc": started_at.isoformat(),
        "duration_seconds": round(duration_seconds, 3),
        "hostname": socket.gethostname(),
        "device_count": 0,
        "devices": [],
        "error": {
            "type": type(error).__name__,
            "message": str(error),
            "hint": (
                "Ensure Bluetooth is enabled on the Pi. If the controller is blocked "
                "or powered off, run `sudo btmgmt power on` or use `bluetoothctl "
                "power on` from a session with permission."
            ),
        },
    }


async def scan_ble_devices(timeout: float) -> list[SeenBLEDevice]:
    try:
        from bleak import BleakScanner
        from bleak.exc import BleakError
    except ImportError as exc:
        raise BLEScanUnavailable(
            "bleak is not installed. Run `uv sync --frozen` before scanning."
        ) from exc

    try:
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except BleakError as exc:
        message = exc.args[0] if exc.args else str(exc)
        raise BLEScanUnavailable(str(message)) from exc

    return [
        normalize_seen_device(device, advertisement)
        for device, advertisement in discovered.values()
    ]


async def run_scan(timeout: float) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    try:
        devices = await scan_ble_devices(timeout)
    except BLEScanUnavailable as exc:
        finished_at = datetime.now(UTC)
        return build_unavailable_result(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
            error=exc,
        )

    finished_at = datetime.now(UTC)
    return build_result(
        devices,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=(finished_at - started_at).total_seconds(),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to scan for nearby BLE advertisements.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("run-results/ble-devices.json"),
        help="Path where the BLE scan result JSON will be written.",
    )
    args = parser.parse_args()

    result = asyncio.run(run_scan(args.timeout))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
