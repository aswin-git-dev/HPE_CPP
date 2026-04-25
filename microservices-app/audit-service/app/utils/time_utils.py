from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from dateutil import parser as dtparser


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: Any) -> Optional[str]:
    """
    Best-effort parsing into ISO-8601 UTC timestamp string.
    Accepts epoch seconds/ms, or string timestamps.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        # Heuristic: ms if it's too large
        seconds = float(value)
        if seconds > 10_000_000_000:  # ~2286-11-20 in seconds => likely ms
            seconds = seconds / 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            dt = dtparser.parse(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return None

    return None

