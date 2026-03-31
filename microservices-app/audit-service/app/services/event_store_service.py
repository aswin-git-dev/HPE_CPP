from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List


class EventStoreService:
    """In-memory event store for control-plane monitoring."""

    def __init__(self, max_events: int = 5000) -> None:
        self._lock = Lock()
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)

    def index_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            # Store newest first semantics via append; readers reverse.
            self._events.append(event)

    def latest(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if limit <= 0:
            return []
        return list(reversed(items[-limit:]))
