"""Tests for the ORION persistent job queue (:mod:`orion.jobs`).

Enqueue -> run -> SUCCESS/FAILED, crash recovery of stale RUNNING rows, the
attempt cap, and status filtering. Each test runs against a private SQLite
DB in a pytest tmp dir.
"""

from __future__ import annotations

import pytest

from orion.config import get_config
from orion.db import _reset_engine, get_session, init_db
from orion.jobs import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    enqueue,
    list_jobs,
    recover_stale,
    register_handler,
    requeue_failed,
    run_next,
)
from orion.models import Job


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Point ORION at a temp data dir and bootstrap a fresh database."""
    monkeypatch.setenv("ORION_DATA_DIR", str(tmp_path))
    _reset_engine()
    get_config(force_reload=True)
    init_db()
    yield
    _reset_engine()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_enqueue_then_run_next_success(db):
    calls = []

    def handler(payload):
        calls.append(payload)
        return {"ok": True}

    register_handler("echo_payload", handler)

    job = enqueue("echo_payload", {"value": 42})
    assert job.status == STATUS_QUEUED
    assert job.attempts == 0

    row = run_next()
    assert row is not None
    assert row.id == job.id
    assert row.status == STATUS_SUCCESS
    assert row.attempts == 1
    assert calls == [{"value": 42}]
    assert run_next() is None  # queue idle afterwards


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


def test_failing_handler_marks_failed_with_error(db):
    def boom(payload):
        raise RuntimeError("kaboom")

    register_handler("explodes", boom)
    enqueue("explodes", {})

    row = run_next()
    assert row.status == STATUS_FAILED
    assert row.attempts == 1
    assert "RuntimeError" in row.error
    assert row.finished_at is not None


def test_missing_handler_marks_failed(db):
    enqueue("no_such_handler_type", {})
    row = run_next()
    assert row.status == STATUS_FAILED
    assert "no handler registered" in row.error


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


def test_recover_stale_requeues_running_jobs_on_worker_start(db):
    register_handler("quick", lambda payload: payload)
    job = enqueue("quick", {})
    # Simulate a crashed worker: the row is stuck in RUNNING.
    with get_session() as s:
        row = s.get(Job, job.id)
        row.status = STATUS_RUNNING

    assert recover_stale() == 1  # exactly one stale row requeued

    with get_session() as s:
        assert s.get(Job, job.id).status == STATUS_QUEUED
    # The recovered job is picked up and completes normally.
    assert run_next().status == STATUS_SUCCESS


def test_recover_stale_counts_zero_when_nothing_stale(db):
    register_handler("idle", lambda payload: payload)
    enqueue("idle", {})
    assert recover_stale() == 0


# ---------------------------------------------------------------------------
# Attempt cap
# ---------------------------------------------------------------------------


def test_attempt_cap_stops_reruns_at_max_attempts(db):
    def doomed(payload):
        raise RuntimeError("always fails")

    register_handler("doomed", doomed)
    enqueue("doomed", {})

    last = None
    for expected in (1, 2, 3):
        last = run_next()
        assert last.status == STATUS_FAILED
        assert last.attempts == expected
        requeue_failed()  # attempts < cap (default 3) -> back to QUEUED

    # Past the cap: nothing is requeued and the queue stays idle.
    assert requeue_failed() == 0
    assert run_next() is None
    with get_session() as s:
        row = s.get(Job, last.id)
        assert row.status == STATUS_FAILED
        assert row.attempts == 3


def test_requeue_failed_respects_custom_max_attempts(db):
    def flaky(payload):
        raise ValueError("nope")

    register_handler("flaky", flaky)
    enqueue("flaky", {})

    row = run_next()  # attempts=1 -> FAILED
    assert row.attempts == 1
    # cap = 1: 1 is not < 1, so no requeue happens.
    assert requeue_failed(max_attempts=1) == 0
    assert run_next() is None
    # cap = 3: below the cap, so it is requeued and runs again.
    assert requeue_failed(max_attempts=3) == 1


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_jobs_filters_by_status(db):
    register_handler("silent", lambda payload: payload)
    enqueue("silent", {"n": 1})
    enqueue("silent", {"n": 2})

    run_next()  # runs the oldest -> SUCCESS, one remains QUEUED

    assert len(list_jobs()) == 2
    assert len(list_jobs(status=STATUS_SUCCESS)) == 1
    assert len(list_jobs(status=STATUS_QUEUED)) == 1
    assert list_jobs(status=STATUS_FAILED) == []
