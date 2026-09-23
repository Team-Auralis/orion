"""Database engine, session factory and bootstrap.

Single SQLite database at ``<data_dir>/orion.db`` (see :mod:`orion.config`).
Migrations are ``Base.metadata.create_all`` — idempotent, no Alembic — plus
an append-only ``schema_version`` table recording each bootstrap. The engine
is created lazily so tests can point the config at a temp dir and rebuild.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from orion.config import get_config
from orion.log import get_logger

log = get_logger("db")

SCHEMA_VERSION = 2


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine = None
_engine_lock = threading.Lock()

# Bound per use (see get_session); bind=None so tests can swap engines.
SessionLocal = sessionmaker(
    bind=None, class_=Session, autoflush=False, expire_on_commit=False
)


def get_engine():
    """Return the process SQLAlchemy engine, creating it once."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                cfg = get_config()
                url = f"sqlite:///{cfg.db_path.as_posix()}"
                _engine = create_engine(
                    url,
                    connect_args={"check_same_thread": False},
                    future=True,
                )
                log.debug("engine created", extra={"url": url})
    return _engine


def _reset_engine() -> None:
    """Drop the cached engine (test helper; hot-reload path)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


@contextmanager
def get_session() -> Iterator[Session]:
    """Context manager yielding a bound Session; commits on success."""
    session = SessionLocal(bind=get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables (idempotent) and record the schema version.

    Safe to call repeatedly and concurrently-safe enough for a single process.
    """
    # Import side-effect registers every model on Base.metadata.
    from orion import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(engine)
    _ensure_columns(engine)

    with get_session() as session:
        latest = (
            session.query(models.SchemaVersion)
            .order_by(models.SchemaVersion.version.desc())
            .first()
        )
        if latest is None or latest.version < SCHEMA_VERSION:
            session.add(
                models.SchemaVersion(
                    version=SCHEMA_VERSION,
                    applied_at=models.utc_now_iso(),
                    notes="create_all bootstrap",
                )
            )
            log.info("schema version recorded", extra={"version": SCHEMA_VERSION})
    log.debug("init_db complete", extra={"db": str(get_config().db_path)})


# Columns added after the first bootstrap. ``create_all`` never ALTERs an
# existing table, so pre-existing databases need the columns injected here
# (all names are code constants — no user input reaches the DDL).
_DEFERRED_COLUMNS: dict[str, dict[str, str]] = {
    "jobs": {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "error": "TEXT",
        "priority": "INTEGER NOT NULL DEFAULT 0",
        "started_at": "VARCHAR(32)",
        "finished_at": "VARCHAR(32)",
    },
    "approval_requests": {
        "consumed_at": "VARCHAR(32)",
    },
}


def _ensure_columns(engine) -> None:
    """ALTER in columns that older bootstraps of this schema are missing."""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    for table, columns in _DEFERRED_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name in existing:
                continue
            with engine.begin() as conn:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            log.info("schema column added", extra={"table": table, "column": name})
