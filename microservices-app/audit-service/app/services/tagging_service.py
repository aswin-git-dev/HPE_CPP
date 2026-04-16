from __future__ import annotations

import re
from typing import Any, Dict, List


class TaggingService:
    """
    Simple, viva-friendly tagging heuristics based on message/event fields.
    """

    _re_priv_escalation = re.compile(r"(privilege|sudo|setuid|cap_sys_admin|root)", re.IGNORECASE)
    _re_auth_failure = re.compile(r"(unauthorized|forbidden|authentication failed|denied)", re.IGNORECASE)
    _re_file_access = re.compile(r"(open\(|chmod|chown|/etc/|/var/|/root/)", re.IGNORECASE)
    _re_config_change = re.compile(r"(create|update|patch|delete).*(configmap|secret|role|clusterrole|rbac)", re.IGNORECASE)
    _re_suspicious_runtime = re.compile(r"(exec|spawn|shell|bash|sh -c|nc |curl |wget )", re.IGNORECASE)

    def build_tags(self, event: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        cls = event.get("classification")
        if isinstance(cls, str) and cls.strip():
            tags.append(f"classification:{cls.strip()}")
        if event.get("source_type") == "falco":
            tags.append("runtime-falco")
        msg = (event.get("message") or "") + " " + (event.get("event_type") or "")

        if self._re_priv_escalation.search(msg):
            tags.append("privilege-escalation")
        if self._re_auth_failure.search(msg) or (event.get("status_code") in (401, 403)):
            tags.append("auth-failure")
        if self._re_file_access.search(msg):
            tags.append("file-access")
        if self._re_suspicious_runtime.search(msg):
            tags.append("suspicious-runtime")

        # K8s specific heuristics
        action = (event.get("action") or "").lower()
        resource = (event.get("resource") or "").lower()
        if action in ("create", "update", "patch", "delete") and resource in ("configmaps", "secrets", "roles", "clusterroles", "rolebindings", "clusterrolebindings"):
            tags.append("config-change")

        # Cross-namespace: if raw contains both a user and namespace and it's not the service's own namespace
        raw = event.get("raw_event") or {}
        if isinstance(raw, dict):
            src_ns = raw.get("sourceNamespace") or raw.get("src_namespace") or raw.get("srcNamespace")
            dst_ns = event.get("namespace")
            if src_ns and dst_ns and src_ns != dst_ns:
                tags.append("cross-namespace")

        # De-dup while preserving order
        seen = set()
        out: List[str] = []
        for t in tags + (event.get("tags") or []):
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out

