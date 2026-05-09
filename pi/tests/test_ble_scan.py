from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, datetime

from home_security_pi.ble_scan import (
    build_result,
    build_unavailable_result,
    normalize_seen_device,
)


@dataclass(frozen=True)
class FakeDevice:
    address: str
    name: str | None
    rssi: int | None = None


@dataclass(frozen=True)
class FakeAdvertisement:
    local_name: str | None
    service_uuids: list[str]
    rssi: int | None = None


class BLESSCanTests(unittest.TestCase):
    def test_normalize_seen_device_uses_advertisement_rssi_first(self) -> None:
        device = FakeDevice(address="AA:BB:CC:DD:EE:FF", name="Device", rssi=-80)
        advertisement = FakeAdvertisement(
            local_name="Advertised",
            service_uuids=["b", "a"],
            rssi=-61,
        )

        seen = normalize_seen_device(device, advertisement)

        self.assertEqual(seen.address, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(seen.name, "Device")
        self.assertEqual(seen.local_name, "Advertised")
        self.assertEqual(seen.rssi, -61)
        self.assertEqual(seen.service_uuids, ["a", "b"])

    def test_build_result_sorts_devices_by_address(self) -> None:
        started_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        finished_at = datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        devices = [
            normalize_seen_device(
                FakeDevice(address="BB", name=None),
                FakeAdvertisement(local_name=None, service_uuids=[]),
            ),
            normalize_seen_device(
                FakeDevice(address="AA", name="Known"),
                FakeAdvertisement(local_name="Local", service_uuids=["180f"], rssi=-50),
            ),
        ]

        result = build_result(
            devices,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=10,
        )

        self.assertEqual(result["source"], "ble")
        self.assertEqual(result["device_count"], 2)
        self.assertEqual(
            [device["address"] for device in result["devices"]],
            ["AA", "BB"],
        )

    def test_build_unavailable_result_reports_scanner_error(self) -> None:
        started_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        finished_at = datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)

        result = build_unavailable_result(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=1,
            error=RuntimeError("adapter unavailable"),
        )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["device_count"], 0)
        self.assertEqual(result["devices"], [])
        self.assertEqual(result["error"]["type"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
