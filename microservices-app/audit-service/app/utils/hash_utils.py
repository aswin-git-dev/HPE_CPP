from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def stable_json_dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def event_fingerprint(payload: Dict[str, Any]) -> str:
    """
    Produce a stable fingerprint for deduplication.
    Avoid including fields that are expected to vary (e.g., raw_event huge blobs).
    """
    minimal = {
        "timestamp": payload.get("timestamp"),
        "source_type": payload.get("source_type"),
        "service_name": payload.get("service_name"),
        "namespace": payload.get("namespace"),
        "pod_name": payload.get("pod_name"),
        "user_name": payload.get("user_name"),
        "severity": payload.get("severity"),
        "event_type": payload.get("event_type"),
        "message": payload.get("message"),
        "action": payload.get("action"),
        "resource": payload.get("resource"),
        "resource_name": payload.get("resource_name"),
        "status_code": payload.get("status_code"),
        "tags": payload.get("tags") or [],
    }
    return sha256_hex(stable_json_dumps(minimal))

