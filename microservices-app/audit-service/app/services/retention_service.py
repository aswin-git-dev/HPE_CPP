from __future__ import annotations

import json
from typing import Any, Dict, Optional, Set, Tuple

from app.core.config import Settings


class RetentionService:
    def __init__(self, settings: Settings) -> None:
        self._allowed = settings.allowed_namespaces_list()
        self._ignored = set(settings.ignored_namespaces_list())
        self._store_raw = settings.store_raw_event
        self._raw_max_bytes = settings.raw_event_max_bytes
        retained = settings.retained_fields_list()
        self._retained_fields: Optional[Set[str]] = set(retained) if retained else None

    def is_namespace_allowed(self, namespace: Optional[str]) -> bool:
        if namespace and namespace in self._ignored:
            return False
        if self._allowed is None:
            return True
        return namespace in self._allowed

    @staticmethod
    def _always_keep_authz_denial(normalized: Dict[str, Any]) -> bool:
        """401/403 and unauthorized_access must not be dropped by namespace filters (e.g. probes against kube-system)."""
        if normalized.get("source_type") != "k8s_audit":
            return False
        if normalized.get("status_code") in (401, 403):
            return True
        if normalized.get("classification") == "unauthorized_access":
            return True
        return False

    def _shape_retention_fields(self, event: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(event)
        if not self._store_raw:
            out["raw_event"] = {}
        else:
            try:
                raw_json = json.dumps(out.get("raw_event", {}), separators=(",", ":"), ensure_ascii=False, default=str)
                raw_bytes = raw_json.encode("utf-8")
                if len(raw_bytes) > self._raw_max_bytes:
                    out["raw_event"] = {"_trimmed": True, "_bytes": len(raw_bytes)}
            except Exception:
                out["raw_event"] = {"_trimmed": True, "_error": "raw_event serialization failed"}

        if self._retained_fields:
            kept = {k: v for k, v in out.items() if k in self._retained_fields}
            for required in ("event_id", "timestamp", "source_type", "severity", "event_type", "message"):
                if required in out and required not in kept:
                    kept[required] = out[required]
            out = kept
        return out

    def apply(self, normalized: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """
        Returns (event, dropped). Drop only based on namespace policy.
        Apply field retention and raw_event trimming.
        """
        # Runtime (Falco) signals are cluster-wide; do not drop by K8s namespace policy.
        if normalized.get("source_type") == "falco":
            return self._shape_retention_fields(normalized), False

        namespace = normalized.get("namespace")
        if not self._always_keep_authz_denial(normalized) and not self.is_namespace_allowed(namespace):
            return normalized, True

        return self._shape_retention_fields(normalized), False

