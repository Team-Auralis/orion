"""In-process event bus — the single publish point for ORION events.

The bus keeps a bounded in-memory history (``deque(maxlen=500)``) and fans
each :func:`publish` out to every live subscriber queue. SSE consumers
subscribe with :func:`subscribe` and drain their queue; the Activity UI can
also read the recent history without waiting on the stream via
:func:`recent`.

Events use STRING keys (e.g. ``opportunity_discovered``,
``opportunity_scored``, ``approval_requested``, ``approval_approved``,
``ledger_write``, ``job_success``, ``strategy_run``, ``experiment_started``,
``error``). Existing subsystems do not publish themselves; the API layer
publishes on their behalf when it orchestrates a call.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from orion.models import utc_now_iso

MAX_HISTORY = 500


@dataclass(frozen=True)
class EventRecord:
    """One bus event: event key + timestamp + attribution + optional payload."""

    event: str
    timestamp: str  # ISO UTC
    agent: str
    entity_id: Optional[Any] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot for SSE / recent() consumers."""
        return {
            "event": self.event,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "entity_id": self.entity_id,
            "metadata": self.metadata or {},
            "correlation_id": self.correlation_id,
        }


_history: deque[EventRecord] = deque(maxlen=MAX_HISTORY)
_subscribers: set[queue.Queue] = set()
_lock = threading.Lock()


def publish(
    event_type: str,
    agent: str = "system",
    entity_id: Any = None,
    metadata: Optional[dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> EventRecord:
    """Append one event to the bounded history and fan it out to subscribers."""
    record = EventRecord(
        event=str(event_type),
        timestamp=utc_now_iso(),
        agent=str(agent),
        entity_id=entity_id,
        metadata=metadata or {},
        correlation_id=correlation_id,
    )
    with _lock:
        _history.append(record)
        for subscriber in list(_subscribers):
            try:
                subscriber.put_nowait(record)
            except queue.Full:  # slow consumer — skip rather than drop the bus
                pass
    return record


def subscribe() -> queue.Queue:
    """Return a live queue that receives every future event (SSE consumers)."""
    subscriber: queue.Queue = queue.Queue()
    with _lock:
        _subscribers.add(subscriber)
    return subscriber


def unsubscribe(subscriber: queue.Queue) -> None:
    """Remove a subscriber queue (call when the SSE connection closes)."""
    with _lock:
        _subscribers.discard(subscriber)


def recent(limit: int = 50) -> list[EventRecord]:
    """Latest stored records, newest first (bounded by MAX_HISTORY)."""
    with _lock:
        return list(_history)[-limit:][::-1]
