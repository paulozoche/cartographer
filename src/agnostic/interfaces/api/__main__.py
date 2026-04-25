from __future__ import annotations

import uvicorn

from agnostic.config import load_app_config


def main() -> None:
    config = load_app_config()
    uvicorn.run(
        "agnostic.interfaces.api.app:create_app",
        factory=True,
        host=config.server.host,
        port=config.server.port,
        access_log=config.server.access_log,
    )


if __name__ == "__main__":
    main()
