from __future__ import annotations

import json
import unittest

from home_security_hub.fetch import (
    FetchError,
    build_remote_snapshot_script,
    parse_remote_snapshot_output,
)


class BuildRemoteSnapshotCommandTests(unittest.TestCase):
    def test_default_command_runs_uv_in_remote_dir(self) -> None:
        command = build_remote_snapshot_script(
            remote_dir="home-security-pi",
            scanner_id=None,
        )
        self.assertIn("cd home-security-pi", command)
        self.assertIn("uv run --no-dev home-security-pi-snapshot", command)
        self.assertNotIn("--scanner-id", command)

    def test_command_includes_scanner_id_when_provided(self) -> None:
        command = build_remote_snapshot_script(
            remote_dir="home-security-pi",
            scanner_id="front-yard",
        )
        self.assertIn("--scanner-id front-yard", command)

    def test_command_quotes_dangerous_input(self) -> None:
        command = build_remote_snapshot_script(
            remote_dir="weird dir",
            scanner_id="weird id",
        )
        self.assertIn("'weird dir'", command)
        self.assertIn("'weird id'", command)


class ParseRemoteSnapshotOutputTests(unittest.TestCase):
    def test_parses_well_formed_payload(self) -> None:
        payload = {
            "snapshot_path": "/x/snap.sqlite3",
            "manifest_path": "/x/snap.json",
            "manifest": {"scanner_id": "pi-test"},
        }
        result = parse_remote_snapshot_output(json.dumps(payload))
        self.assertEqual(result.snapshot_path, "/x/snap.sqlite3")
        self.assertEqual(result.manifest_path, "/x/snap.json")
        self.assertEqual(result.manifest["scanner_id"], "pi-test")

    def test_invalid_json_raises_fetch_error(self) -> None:
        with self.assertRaises(FetchError):
            parse_remote_snapshot_output("not json")

    def test_missing_field_raises_fetch_error(self) -> None:
        payload = {"snapshot_path": "/x", "manifest_path": "/y"}
        with self.assertRaises(FetchError):
            parse_remote_snapshot_output(json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
