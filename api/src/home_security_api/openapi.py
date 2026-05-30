from __future__ import annotations

import json
import sys
from pathlib import Path

from home_security_api.app import create_app


def main() -> None:
    """Dump the OpenAPI schema as JSON.

    Writes to the path given as the first argument, or to stdout otherwise.
    Builds the schema from the route definitions only; the archive is never
    opened, so this runs without a database present.
    """
    schema = create_app().openapi()
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
