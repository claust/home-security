from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from home_security_hub.archive import Archive, IngestResult
from home_security_hub.manifest import Manifest, ManifestError

DEFAULT_HOST_ENV = "HOME_SECURITY_PI_HOST"
DEFAULT_HOST = "home-security-pi"
DEFAULT_REMOTE_DIR = "home-security-pi"
DEFAULT_ARCHIVE = Path.home() / ".local/state/home-security/archive.sqlite3"
DEFAULT_INBOX_DIR = Path.home() / ".local/state/home-security/inbox"

REMOTE_SNAPSHOT_SCRIPT_TEMPLATE = (
    "set -eu\n"
    'export PATH="$HOME/.local/bin:$PATH"\n'
    "cd {remote_dir}\n"
    "uv run --no-dev home-security-pi-snapshot{scanner_arg}\n"
)

REMOTE_PRUNE_SCRIPT_TEMPLATE = (
    "set -eu\n"
    'export PATH="$HOME/.local/bin:$PATH"\n'
    "cd {remote_dir}\n"
    "uv run --no-dev home-security-pi-prune --before {before_arg}\n"
)


class FetchError(RuntimeError):
    """Raised when a remote fetch cannot complete."""


@dataclass(frozen=True)
class RemoteSnapshotResult:
    snapshot_path: str
    manifest_path: str
    manifest: dict


@dataclass(frozen=True)
class RemotePruneResult:
    database: str
    requested_before_utc: str
    effective_before_utc: str
    keep_last_days: int
    rows_deleted: int
    pruned_at_utc: str


@dataclass(frozen=True)
class FetchSummary:
    host: str
    scanner_id: str
    snapshot_path_local: str
    manifest_path_local: str
    snapshot_path_remote: str
    manifest_path_remote: str
    manifest: dict
    ingest: IngestResult
    remote_cleanup: bool
    remote_prune: RemotePruneResult | None


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_remote_snapshot_script(
    *,
    remote_dir: str,
    scanner_id: str | None,
) -> str:
    scanner_arg = f" --scanner-id {shlex.quote(scanner_id)}" if scanner_id else ""
    return REMOTE_SNAPSHOT_SCRIPT_TEMPLATE.format(
        remote_dir=shlex.quote(remote_dir),
        scanner_arg=scanner_arg,
    )


def parse_remote_snapshot_output(stdout: str) -> RemoteSnapshotResult:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FetchError(
            f"Could not parse remote snapshot JSON.\nOutput was:\n{stdout}"
        ) from exc

    for key in ("snapshot_path", "manifest_path", "manifest"):
        if key not in payload:
            raise FetchError(f"Remote snapshot output missing field: {key}")

    return RemoteSnapshotResult(
        snapshot_path=str(payload["snapshot_path"]),
        manifest_path=str(payload["manifest_path"]),
        manifest=dict(payload["manifest"]),
    )


def run_remote_snapshot(
    *,
    host: str,
    remote_dir: str,
    scanner_id: str | None,
) -> RemoteSnapshotResult:
    script = build_remote_snapshot_script(
        remote_dir=remote_dir,
        scanner_id=scanner_id,
    )
    completed = subprocess.run(
        ["ssh", "-T", host, "bash", "-s"],
        input=script,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise FetchError(
            "Remote snapshot command failed "
            f"(exit {completed.returncode}).\n"
            f"stderr:\n{completed.stderr}\n"
            f"stdout:\n{completed.stdout}"
        )
    return parse_remote_snapshot_output(completed.stdout)


def build_remote_prune_script(*, remote_dir: str, before_utc: str) -> str:
    return REMOTE_PRUNE_SCRIPT_TEMPLATE.format(
        remote_dir=shlex.quote(remote_dir),
        before_arg=shlex.quote(before_utc),
    )


def parse_remote_prune_output(stdout: str) -> RemotePruneResult:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FetchError(
            f"Could not parse remote prune JSON.\nOutput was:\n{stdout}"
        ) from exc

    required = (
        "database",
        "requested_before_utc",
        "effective_before_utc",
        "keep_last_days",
        "rows_deleted",
        "pruned_at_utc",
    )
    for key in required:
        if key not in payload:
            raise FetchError(f"Remote prune output missing field: {key}")

    return RemotePruneResult(
        database=str(payload["database"]),
        requested_before_utc=str(payload["requested_before_utc"]),
        effective_before_utc=str(payload["effective_before_utc"]),
        keep_last_days=int(payload["keep_last_days"]),
        rows_deleted=int(payload["rows_deleted"]),
        pruned_at_utc=str(payload["pruned_at_utc"]),
    )


def run_remote_prune(
    *,
    host: str,
    remote_dir: str,
    before_utc: str,
) -> RemotePruneResult:
    script = build_remote_prune_script(
        remote_dir=remote_dir,
        before_utc=before_utc,
    )
    completed = subprocess.run(
        ["ssh", "-T", host, "bash", "-s"],
        input=script,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise FetchError(
            "Remote prune command failed "
            f"(exit {completed.returncode}).\n"
            f"stderr:\n{completed.stderr}\n"
            f"stdout:\n{completed.stdout}"
        )
    return parse_remote_prune_output(completed.stdout)


def rsync_files(*, host: str, remote_paths: list[str], local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    sources = [f"{host}:{remote_path}" for remote_path in remote_paths]
    completed = subprocess.run(
        ["rsync", "-a", *sources, f"{local_dir}/"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise FetchError(
            f"rsync failed (exit {completed.returncode}).\nstderr:\n{completed.stderr}"
        )


def remote_cleanup(*, host: str, remote_paths: list[str]) -> None:
    quoted = " ".join(shlex.quote(path) for path in remote_paths)
    completed = subprocess.run(
        ["ssh", "-T", host, f"rm -f -- {quoted}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise FetchError(
            "Remote cleanup failed "
            f"(exit {completed.returncode}) for: {quoted}\n"
            f"stderr:\n{completed.stderr}"
        )


def verify_local_snapshot(snapshot_path: Path, manifest: Manifest) -> None:
    actual = sha256_file(snapshot_path)
    if actual != manifest.sha256:
        raise FetchError(
            "Local snapshot sha256 does not match manifest.\n"
            f"  expected: {manifest.sha256}\n"
            f"  actual:   {actual}\n"
            f"  path:     {snapshot_path}"
        )
    if manifest.integrity != "ok":
        raise FetchError(f"Snapshot integrity check is not ok: {manifest.integrity!r}")


def fetch(
    *,
    host: str,
    remote_dir: str,
    scanner_id: str | None,
    archive_path: Path,
    inbox_dir: Path,
    keep_remote: bool,
    no_prune: bool,
) -> FetchSummary:
    remote_result = run_remote_snapshot(
        host=host,
        remote_dir=remote_dir,
        scanner_id=scanner_id,
    )
    effective_scanner_id = remote_result.manifest["scanner_id"]
    scanner_inbox = inbox_dir / effective_scanner_id

    rsync_files(
        host=host,
        remote_paths=[remote_result.snapshot_path, remote_result.manifest_path],
        local_dir=scanner_inbox,
    )

    local_snapshot = scanner_inbox / Path(remote_result.snapshot_path).name
    local_manifest_path = scanner_inbox / Path(remote_result.manifest_path).name

    manifest = Manifest.from_path(local_manifest_path)
    verify_local_snapshot(local_snapshot, manifest)

    archive = Archive(archive_path)
    archive.initialize()
    ingest = archive.ingest_snapshot(
        snapshot_path=local_snapshot,
        manifest=manifest,
        manifest_path=local_manifest_path,
        ingested_at_utc=utc_now(),
    )

    cleaned_remote = False
    if not keep_remote:
        remote_cleanup(
            host=host,
            remote_paths=[
                remote_result.snapshot_path,
                remote_result.manifest_path,
            ],
        )
        cleaned_remote = True

    prune_result: RemotePruneResult | None = None
    if not no_prune:
        prune_result = run_remote_prune(
            host=host,
            remote_dir=remote_dir,
            before_utc=manifest.snapshot_taken_at_utc,
        )

    return FetchSummary(
        host=host,
        scanner_id=effective_scanner_id,
        snapshot_path_local=str(local_snapshot),
        manifest_path_local=str(local_manifest_path),
        snapshot_path_remote=remote_result.snapshot_path,
        manifest_path_remote=remote_result.manifest_path,
        manifest=remote_result.manifest,
        ingest=ingest,
        remote_cleanup=cleaned_remote,
        remote_prune=prune_result,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a BLE observation snapshot from a monitor Pi and ingest "
            "it into the local archive."
        )
    )
    parser.add_argument(
        "--host",
        default=os.environ.get(DEFAULT_HOST_ENV, DEFAULT_HOST),
        help="SSH alias or hostname of the monitor Pi.",
    )
    parser.add_argument(
        "--remote-dir",
        default=os.environ.get("HOME_SECURITY_PI_REMOTE_DIR", DEFAULT_REMOTE_DIR),
        help="Directory on the Pi where the deployed package lives.",
    )
    parser.add_argument(
        "--scanner-id",
        default=None,
        help=(
            "Override the scanner identifier passed to the Pi. "
            "When omitted, the Pi defaults to its hostname."
        ),
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_ARCHIVE,
        help="Path to the consolidated archive SQLite database.",
    )
    parser.add_argument(
        "--inbox-dir",
        type=Path,
        default=DEFAULT_INBOX_DIR,
        help="Directory under which inbox/<scanner_id>/ snapshot pairs are placed.",
    )
    parser.add_argument(
        "--keep-remote",
        action="store_true",
        help="Do not delete the snapshot pair on the Pi after ingest.",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help=(
            "Skip pruning ingested observation rows on the Pi. "
            "By default, after a successful ingest the hub asks the Pi to "
            "delete observations with observed_at_utc <= snapshot_taken_at_utc "
            "(subject to the Pi's --keep-last-days safety floor)."
        ),
    )
    args = parser.parse_args()

    try:
        summary = fetch(
            host=args.host,
            remote_dir=args.remote_dir,
            scanner_id=args.scanner_id,
            archive_path=args.archive,
            inbox_dir=args.inbox_dir,
            keep_remote=args.keep_remote,
            no_prune=args.no_prune,
        )
    except (FetchError, ManifestError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    payload = {
        "host": summary.host,
        "scanner_id": summary.scanner_id,
        "snapshot_path_local": summary.snapshot_path_local,
        "manifest_path_local": summary.manifest_path_local,
        "snapshot_path_remote": summary.snapshot_path_remote,
        "manifest_path_remote": summary.manifest_path_remote,
        "remote_cleanup": summary.remote_cleanup,
        "manifest": summary.manifest,
        "ingest": asdict(summary.ingest),
        "remote_prune": (
            asdict(summary.remote_prune) if summary.remote_prune else None
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
