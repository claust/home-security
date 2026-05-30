from __future__ import annotations

import argparse
import json
import platform
import socket
from datetime import UTC, datetime
from pathlib import Path

from home_security_pi import __version__
from home_security_pi.snapshot import (
    DEFAULT_SCANNER_ID_FILE,
    SnapshotError,
    read_scanner_id_file,
)


def read_scanner_id_or_none() -> str | None:
    try:
        return read_scanner_id_file(DEFAULT_SCANNER_ID_FILE)
    except SnapshotError:
        return None


def build_result() -> dict[str, str | None]:
    return {
        "status": "ok",
        "package": "home-security-pi",
        "version": __version__,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "scanner_id": read_scanner_id_or_none(),
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("run-results/latest.json"),
        help="Path where the verification result JSON will be written.",
    )
    args = parser.parse_args()

    result = build_result()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
