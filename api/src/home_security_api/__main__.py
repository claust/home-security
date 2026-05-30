from __future__ import annotations

import uvicorn

from home_security_api.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "home_security_api.app:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
