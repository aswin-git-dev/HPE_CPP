from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

_INGESTED = "_ingested_monotonic"
logger = logging.getLogger("audit-service.event_store")


class EventStoreService:
    """Event store with in-memory ring buffer + optional persistent disk storage.

    When ``persistent_path`` is set (env ``PERSISTENT_STORAGE_PATH``), every
    ingested event is appended to a JSONL file on the mounted PVC so that data
    survives pod restarts.  On init, existing JSONL files are loaded back into
    the in-memory buffer (up to ``max_events`` most recent).
    """

    def __init__(
        self,
        max_events: int = 5000,
        ttl_seconds: int = 0,
        persistent_path: Optional[str] = None,
    ) -> None:
        self._lock = Lock()
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._ttl_seconds = ttl_seconds if ttl_seconds and ttl_seconds > 0 else 0
        self._persistent_path: Optional[Path] = None
        self._current_file_handle = None

        if persistent_path:
            p = Path(persistent_path)
            try:
                p.mkdir(parents=True, exist_ok=True)
                self._persistent_path = p
                self._load_from_disk()
                self._open_current_file()
                logger.info("persistent_storage_enabled", extra={"path": str(p)})
            except Exception:
                logger.exception("persistent_storage_init_failed", extra={"path": str(p)})

    # ── Disk I/O helpers ─────────────────────────────────────────────────────

    def _current_filename(self) -> str:
        """Daily rotation: one file per day."""
        return datetime.now(timezone.utc).strftime("audit-events-%Y-%m-%d.jsonl")

    def _open_current_file(self) -> None:
        if not self._persistent_path:
            return
        try:
            filepath = self._persistent_path / self._current_filename()
            self._current_file_handle = open(filepath, "a", encoding="utf-8")
        except Exception:
            logger.exception("persistent_file_open_failed")

    def _write_to_disk(self, event: Dict[str, Any]) -> None:
        if not self._persistent_path or not self._current_file_handle:
            return
        try:
            # Rotate if day changed
            expected = self._current_filename()
            if not self._current_file_handle.name.endswith(expected):
                self._current_file_handle.close()
                self._open_current_file()

            line = json.dumps(event, default=str, ensure_ascii=False)
            self._current_file_handle.write(line + "\n")
            self._current_file_handle.flush()
        except Exception:
            logger.exception("persistent_write_failed")

    def _load_from_disk(self) -> None:
        """Load existing JSONL files from disk into the in-memory buffer."""
        if not self._persistent_path:
            return
        files = sorted(self._persistent_path.glob("audit-events-*.jsonl"))
        loaded = 0
        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            event[_INGESTED] = time.monotonic()
                            self._events.append(event)
                            loaded += 1
                        except json.JSONDecodeError:
                            continue
            except Exception:
                logger.exception("persistent_load_file_failed", extra={"file": str(f)})
        if loaded:
            logger.info("persistent_storage_loaded", extra={"events": loaded, "files": len(files)})

    # ── Public API ───────────────────────────────────────────────────────────

    def index_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            row = dict(event)
            row[_INGESTED] = time.monotonic()
            self._events.append(row)
            if self._ttl_seconds:
                cutoff = time.monotonic() - self._ttl_seconds
                while self._events and self._events[0].get(_INGESTED, 0) < cutoff:
                    self._events.popleft()

        # Write outside the lock to avoid blocking reads
        clean_event = {k: v for k, v in event.items() if k != _INGESTED}
        self._write_to_disk(clean_event)

    def latest(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if limit <= 0:
            return []
        out = []
        for e in reversed(items[-limit:]):
            out.append({k: v for k, v in e.items() if k != _INGESTED})
        return out

