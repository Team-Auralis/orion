"""Structured logging.

JSON-compatible records (``timestamp``, ``level``, ``logger``, ``msg`` plus
any extra keyword fields passed to the log call) are written to a rotating
file at ``<data_dir>/logs/orion.log``, with a compact human-readable console
handler on top. Use :func:`get_logger` everywhere; the console handler keeps
extra fields in ``key=value`` form. Nothing here may be imported from
``orion.config`` with a hard dependency, so logging works even if config is
mid-bootstrap; the data dir is resolved through ``get_config()`` at first use.

Secret scrubbing: ``setup_logging`` calls ``orion.secrets.install_redaction_filter``
so every stored vault value is stripped from records on all streams. This
imports ``orion.secrets`` (which imports only stdlib + ``orion.config``, never
this module), so there is no circular dependency.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from orion.config import get_config
from orion.secrets import install_redaction_filter

# Standard logging.LogRecord attributes we never treat as "extra" fields.
_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "taskName",
    }
)

_ROOT_LOGGER = "orion"
_logging_configured = False


class JsonFormatter(logging.Formatter):
    """Render a record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Compact human-readable console line, extras as ``key=value``."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<8} {record.name} | {record.getMessage()}"
        extras = [
            f"{k}={v}"
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        ]
        if extras:
            base += "  " + " ".join(extras)
        return base


def setup_logging() -> None:
    """Idempotently configure the ``orion.*`` logger tree."""
    global _logging_configured
    if _logging_configured:
        return

    cfg = get_config()
    env = os.environ.get("ORION_ENV", "dev").strip() or "dev"

    log_dir = cfg.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    level = logging.INFO if env == "prod" else logging.DEBUG

    logger = logging.getLogger(_ROOT_LOGGER)
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        file_handler = RotatingFileHandler(
            log_dir / "orion.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)

        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(ConsoleFormatter())
        logger.addHandler(console)

    install_redaction_filter()
    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured ``orion.<name>`` logger."""
    setup_logging()
    return logging.getLogger(f"{_ROOT_LOGGER}.{name}")
