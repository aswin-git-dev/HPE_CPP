from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List

_INGESTED = "_ingested_monotonic"


class EventStoreService:
    """In-memory event store for control-plane monitoring."""

    def __init__(self, max_events: int = 5000, ttl_seconds: int = 0) -> None:
        self._lock = Lock()
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._ttl_seconds = ttl_seconds if ttl_seconds and ttl_seconds > 0 else 0

    def index_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            row = dict(event)
            row[_INGESTED] = time.monotonic()
            self._events.append(row)
            if self._ttl_seconds:
                cutoff = time.monotonic() - self._ttl_seconds
                while self._events and self._events[0].get(_INGESTED, 0) < cutoff:
                    self._events.popleft()

    def latest(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if limit <= 0:
            return []
        out = []
        for e in reversed(items[-limit:]):
            out.append({k: v for k, v in e.items() if k != _INGESTED})
        return out
