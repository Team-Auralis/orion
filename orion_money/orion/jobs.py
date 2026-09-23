"""Persistent job queue with crash recovery and an attempt cap.

Lifecycle (``jobs.status``): QUEUED -> RUNNING -> SUCCESS | FAILED |
CANCELLED, plus WAITING_APPROVAL (a handler paused the job on a human
decision; it is not re-picked until requeued).

Handlers are registered per job type via :func:`register_handler` and run
with the decoded payload. A job is executed at most ``jobs.max_attempts``
times (config default 3): :func:`requeue_failed` requeues FAILED jobs up to
that cap, and :func:`run_next` only ever picks QUEUED rows — a SUCCESS job is
never rerun. Crash recovery: :func:`recover_stale` requeues any RUNNING job
found at boot (the previous process died mid-run); it is called by
:func:`start_worker` so nothing is silently dropped.

SQLite note: the RUNNING state is committed BEFORE the handler runs, so a
handler's own DB writes never deadlock against the queue's open transaction.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Optional

from orion.config import get_config
from orion.db import get_session
from orion.log import get_logger
from orion.models import Job, utc_now_iso

log = get_logger("jobs")

JOB_STATUSES = (
    "QUEUED",
    "RUNNING",
    "WAITING_APPROVAL",
    "SUCCESS",
    "FAILED",
    "CANCELLED",
)

STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_WAITING_APPROVAL = "WAITING_APPROVAL"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_CANCELLED = "CANCELLED"

# Sentinel: a handler may return this to park the job on a human decision.
WAITING_APPROVAL = object()

_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
_stop_event = threading.Event()
_worker: Optional[threading.Thread] = None


def register_handler(job_type: str, fn: Callable[[dict[str, Any]], Any]) -> None:
    """Register (or replace) the handler for a job type. ``fn(payload)``."""
    if not job_type or not str(job_type).strip():
        raise ValueError("job_type must not be empty")
    _handlers[str(job_type)] = fn


def enqueue(
    job_type: str,
    payload: Optional[dict[str, Any]] = None,
    priority: int = 0,
    session=None,
) -> Job:
    """Enqueue one job (QUEUED). Returns the Job row."""
    if session is None:
        with get_session() as s:
            return enqueue(job_type, payload=payload, priority=priority, session=s)
    if not job_type or not str(job_type).strip():
        raise ValueError("job_type must not be empty")
    job = Job(
        name=str(job_type),
        job_type=str(job_type),
        payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
        status=STATUS_QUEUED,
        priority=int(priority or 0),
        attempts=0,
    )
    session.add(job)
    session.flush()
    log.info(
        "job enqueued",
        extra={"id": job.id, "job_type": job_type, "priority": job.priority},
    )
    return job


def _pick_queued(session) -> Optional[Job]:
    """Highest-priority QUEUED job, oldest first within a priority."""
    return (
        session.query(Job)
        .filter(Job.status == STATUS_QUEUED)
        .order_by(Job.priority.desc(), Job.id.asc())
        .first()
    )


def run_next(session=None) -> Optional[Job]:
    """Execute exactly one QUEUED job; returns it (or None when idle).

    The RUNNING state (with attempts increment) is committed before the
    handler runs so the handler's own DB writes never collide with the
    queue's transaction. Failures land as FAILED + error.
    """
    if session is not None:
        raise ValueError("run_next manages its own session; pass session=None")

    with get_session() as s:
        job = _pick_queued(s)
        if job is None:
            return None
        if job.status == STATUS_SUCCESS:  # idempotency guard — never rerun
            return None
        job_id = job.id
        job_type = job.job_type
        payload = _decode(job.payload_json)
        job.status = STATUS_RUNNING
        job.attempts = (job.attempts or 0) + 1
        job.started_at = utc_now_iso()
        job.error = None

    handler = _handlers.get(job_type)
    try:
        if handler is None:
            raise ValueError(f"no handler registered for job type {job_type!r}")
        result = handler(payload)
        if result is WAITING_APPROVAL:
            status = STATUS_WAITING_APPROVAL
        else:
            status = STATUS_SUCCESS
        error = None
    except Exception as exc:  # noqa: BLE001 — a failing job must not kill the worker
        status = STATUS_FAILED
        error = f"{type(exc).__name__}: {exc}"
        log.exception("job failed", extra={"id": job_id, "job_type": job_type})

    with get_session() as s:
        row = s.get(Job, job_id)
        row.status = status
        row.error = error
        row.finished_at = utc_now_iso()
    log.info(
        "job finished",
        extra={
            "id": job_id,
            "job_type": job_type,
            "status": status,
            "attempts": job.attempts,
        },
    )
    return row


def _decode(payload_json: Optional[str]) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def requeue_failed(max_attempts: Optional[int] = None, session=None) -> int:
    """Requeue FAILED jobs with attempts below the cap. Returns count."""
    if session is None:
        with get_session() as s:
            return requeue_failed(max_attempts=max_attempts, session=s)
    cap = (
        int(max_attempts)
        if max_attempts is not None
        else int(get_config().jobs.max_attempts)
    )
    requeued = 0
    for job in session.query(Job).filter(Job.status == STATUS_FAILED):
        if (job.attempts or 0) < cap:
            job.status = STATUS_QUEUED
            job.finished_at = None
            requeued += 1
    if requeued:
        session.flush()
    return requeued


def recover_stale(session=None) -> int:
    """Requeue RUNNING jobs left by a previous process (crash recovery)."""
    if session is None:
        with get_session() as s:
            return recover_stale(session=s)
    count = 0
    for job in session.query(Job).filter(Job.status == STATUS_RUNNING):
        job.status = STATUS_QUEUED
        job.finished_at = None
        count += 1
    if count:
        session.flush()
        log.warning("recovered stale RUNNING jobs", extra={"count": count})
    return count


def list_jobs(status: Optional[str] = None, limit: int = 50, session=None) -> list[Job]:
    """Jobs, newest first, optionally filtered by status."""
    if session is None:
        with get_session() as s:
            return list_jobs(status=status, limit=limit, session=s)
    q = session.query(Job)
    if status is not None:
        q = q.filter(Job.status == status)
    return q.order_by(Job.id.desc()).limit(limit).all()


def start_worker(poll_seconds: Optional[float] = None) -> threading.Thread:
    """Recover stale RUNNING jobs, then poll the queue on a background thread.

    Idempotent per call (a fresh thread per call; stop the old one first via
    :func:`stop_worker` if you need a single worker).
    """
    global _worker
    recover_stale()
    poll = (
        float(poll_seconds)
        if poll_seconds is not None
        else float(get_config().jobs.poll_seconds)
    )
    _stop_event.clear()
    worker = threading.Thread(
        target=_worker_loop,
        args=(poll,),
        name="orion-jobs-worker",
        daemon=True,
    )
    _worker = worker
    worker.start()
    log.info("job worker started", extra={"poll_seconds": poll})
    return worker


def stop_worker(timeout: float = 5.0) -> None:
    """Signal the background worker to stop and wait briefly for it."""
    global _worker
    _stop_event.set()
    if _worker is not None and _worker.is_alive():
        _worker.join(timeout=timeout)
    _worker = None


def _worker_loop(poll: float) -> None:
    while not _stop_event.is_set():
        ran = run_next()
        if ran is None:
            _stop_event.wait(poll)
