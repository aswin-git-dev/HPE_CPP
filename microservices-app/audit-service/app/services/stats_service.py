from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Dict

from app.schemas.common import Severity, SourceType


class StatsService:
    def __init__(self) -> None:
        self._lock = Lock()
        self.total_processed = 0
        self.total_failed = 0
        self.by_source = Counter()
        self.by_severity = Counter()

    def record_processed(self, source_type: SourceType, severity: Severity) -> None:
        with self._lock:
            self.total_processed += 1
            self.by_source[source_type.value] += 1
            self.by_severity[severity.value] += 1

    def record_failed(self) -> None:
        with self._lock:
            self.total_failed += 1

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "total_processed": self.total_processed,
                "total_failed": self.total_failed,
                "by_source_type": dict(self.by_source),
                "by_severity": dict(self.by_severity),
            }

