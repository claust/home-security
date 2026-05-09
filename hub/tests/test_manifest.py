from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from home_security_hub.manifest import Manifest, ManifestError


def valid_payload(**overrides: object) -> dict:
    payload = {
        "scanner_id": "pi-test",
        "hostname": "pi-test",
        "snapshot_taken_at_utc": "2026-05-09T12:33:30+00:00",
        "database_source": "/state/home-security/observations.sqlite3",
        "row_count": 3126,
        "unique_addresses": 199,
        "observed_at_utc_min": "2026-05-09T10:50:35+00:00",
        "observed_at_utc_max": "2026-05-09T12:33:29+00:00",
        "sha256": "0" * 64,
        "integrity": "ok",
        "package_version": "0.1.0",
    }
    payload.update(overrides)
    return payload


class ManifestTests(unittest.TestCase):
    def test_from_dict_parses_valid_payload(self) -> None:
        manifest = Manifest.from_dict(valid_payload())
        self.assertEqual(manifest.scanner_id, "pi-test")
        self.assertEqual(manifest.row_count, 3126)
        self.assertEqual(manifest.integrity, "ok")
        self.assertEqual(manifest.observed_at_utc_min, "2026-05-09T10:50:35+00:00")

    def test_from_dict_allows_null_observed_at_bounds(self) -> None:
        manifest = Manifest.from_dict(
            valid_payload(
                row_count=0,
                unique_addresses=0,
                observed_at_utc_min=None,
                observed_at_utc_max=None,
            )
        )
        self.assertIsNone(manifest.observed_at_utc_min)
        self.assertIsNone(manifest.observed_at_utc_max)

    def test_missing_field_raises(self) -> None:
        payload = valid_payload()
        del payload["sha256"]
        with self.assertRaises(ManifestError):
            Manifest.from_dict(payload)

    def test_invalid_scanner_id_raises(self) -> None:
        with self.assertRaises(ManifestError):
            Manifest.from_dict(valid_payload(scanner_id="bad/id"))

    def test_invalid_sha256_raises(self) -> None:
        with self.assertRaises(ManifestError):
            Manifest.from_dict(valid_payload(sha256="not-a-hash"))

    def test_negative_row_count_raises(self) -> None:
        with self.assertRaises(ManifestError):
            Manifest.from_dict(valid_payload(row_count=-1))

    def test_from_path_reads_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(valid_payload()), encoding="utf-8")
            manifest = Manifest.from_path(path)
        self.assertEqual(manifest.scanner_id, "pi-test")

    def test_from_path_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ManifestError):
                Manifest.from_path(path)


if __name__ == "__main__":
    unittest.main()
