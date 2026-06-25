from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib import error, request

from app.core.config import Settings

logger = logging.getLogger("audit-service.grafana_loki")

_NOISY_FALCO_CLASSIFICATIONS = frozenset({
    "falco_contact_k8s_api_server_from_container",
    "falco_contact_k8_s_api_server_from_container",
})

_ACTION_PRIORITY: Dict[str, str] = {
    "read sensitive file": "Critical",
    "searched cloud credentials": "Critical",
    "read ssh information": "Warning",
    "wrote under etc": "Warning",
    "wrote binary directory": "Warning",
    "ran package manager": "Warning",
    "spawned interactive shell": "Notice",
    "collected system information": "Notice",
    "container exec": "Notice",
    "runtime security alert": "Notice",
}


def _slug_label(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return s[:96] if s else "falco_alert"


def _parse_rfc3339_ns(ts: Optional[str]) -> int:
    if not ts:
        return time.time_ns()
    try:
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except ValueError:
        return time.time_ns()


def _priority_for_action(action: str, severity: Optional[str]) -> str:
    key = action.strip().lower()
    if key in _ACTION_PRIORITY:
        return _ACTION_PRIORITY[key]
    sev = (severity or "").strip().lower()
    if sev in ("critical", "unauthorized_access", "error", "fatal"):
        return "Critical"
    if sev in ("warning", "warn"):
        return "Warning"
    if sev in ("info", "notice", "informational", "debug"):
        return "Notice"
    return "Notice"


class GrafanaLokiService:
    """Push monitor-UI Falco rows (resource=falco) to Grafana Cloud Loki."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(settings.grafana_loki_enabled)
        self._push_url = settings.grafana_loki_push_url
        self._username = settings.grafana_loki_username
        self._password = settings.grafana_loki_password
        self._timeout_s = settings.grafana_loki_timeout_s

    @property
    def ready(self) -> bool:
        return bool(
            self._enabled
            and self._push_url
            and self._username
            and self._password,
        )

    def forward_falco_dashboard_event(self, event: Dict[str, Any], cluster_source_urn: str) -> None:
        if not self.ready:
            return

        cls = str(event.get("classification") or "")
        if cls in _NOISY_FALCO_CLASSIFICATIONS:
            return

        # Lazy import avoids circular dependency at module load.
        from app.api.routes.control_plane import _to_monitor_payload

        monitor = _to_monitor_payload(cluster_source_urn, event)
        if not monitor:
            return

        data = monitor.get("data") if isinstance(monitor.get("data"), dict) else {}
        src = data.get("source") if isinstance(data.get("source"), dict) else {}
        obj = data.get("object") if isinstance(data.get("object"), dict) else {}
        net = data.get("network") if isinstance(data.get("network"), dict) else {}

        if src.get("requestingService") != "falco":
            return

        action = str(src.get("requestMethod") or "Runtime security alert").strip()
        detail = str(src.get("requestUrl") or event.get("message") or action).strip()
        rule_name = action
        priority = _priority_for_action(action, str(net.get("severity") or event.get("severity") or ""))

        ns = obj.get("objowner") or event.get("namespace")
        pod = obj.get("objname") or event.get("resource_name")

        log_line: Dict[str, Any] = {
            "time": monitor.get("time") or event.get("timestamp"),
            "rule": rule_name,
            "priority": priority,
            "output": detail,
            "source": "falco",
            "source_type": "falco",
            "event_id": event.get("event_id"),
            "classification": net.get("classification") or cls or "falco",
        }
        if ns:
            log_line["k8s.ns.name"] = ns
        if pod:
            log_line["k8s.pod.name"] = pod

        stream_labels = {
            "source": "falco",
            "source_type": "falco",
            "rule": _slug_label(rule_name),
            "priority": priority,
        }

        payload = {
            "streams": [
                {
                    "stream": stream_labels,
                    "values": [
                        [str(_parse_rfc3339_ns(str(log_line.get("time") or ""))), json.dumps(log_line, default=str)],
                    ],
                }
            ]
        }

        try:
            body = json.dumps(payload).encode("utf-8")
            auth = base64.b64encode(f"{self._username}:{self._password}".encode()).decode("ascii")
            req = request.Request(
                self._push_url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {auth}",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=self._timeout_s) as resp:
                if resp.status >= 300:
                    logger.warning("grafana_loki_push_status", extra={"status": resp.status})
        except error.HTTPError as exc:
            logger.warning(
                "grafana_loki_push_http_error",
                extra={"code": exc.code, "event_id": event.get("event_id"), "rule": rule_name},
            )
        except Exception:
            logger.exception(
                "grafana_loki_push_failed",
                extra={"event_id": event.get("event_id"), "rule": rule_name},
            )
