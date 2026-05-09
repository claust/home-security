from __future__ import annotations

import argparse
import json
import platform
import socket
from datetime import UTC, datetime
from pathlib import Path

from home_security_pi import __version__


def build_result() -> dict[str, str]:
    return {
        "status": "ok",
        "package": "home-security-pi",
        "version": __version__,
        "timestamp_utc": datetime.now(UTC).isoformat(),
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
