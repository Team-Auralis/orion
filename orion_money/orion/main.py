"""HTTP entry point — ``python -m orion.main`` serves the FastAPI app.

Bind address/port come from ``config api.host`` / ``api.port`` (defaults
127.0.0.1:8765, avoiding the commonly-occupied 8000). ``app`` is re-exported
so ``uvicorn orion.main:app`` works too.
"""

from __future__ import annotations

import uvicorn

from orion.api import app
from orion.config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(app, host=cfg.api.host, port=cfg.api.port)


if __name__ == "__main__":
    main()
