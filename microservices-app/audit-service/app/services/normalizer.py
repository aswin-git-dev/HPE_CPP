from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.schemas import AppLogIn, FalcoAlertIn, K8sAuditLogIn, Severity, SourceType
from app.utils.hash_utils import event_fingerprint
from app.utils.time_utils import parse_timestamp, utc_now_iso


def _map_severity_from_level(level: Optional[str]) -> Severity:
    if not level:
        return Severity.info
    s = level.strip().lower()
    if s in ("debug", "info", "notice"):
        return Severity.info
    if s in ("warn", "warning"):
        return Severity.warning
    if s in ("error", "fatal", "critical", "panic", "alert", "emergency"):
        return Severity.critical
    return Severity.info


def _map_severity_from_status(code: Optional[int]) -> Severity:
    if code is None:
        return Severity.info
    if code in (401, 403):
        return Severity.unauthorized_access
    if 200 <= code < 400:
        return Severity.info
    if 400 <= code < 500:
        return Severity.warning
    return Severity.critical


def _map_severity_from_falco_priority(priority: Optional[str]) -> Severity:
    if not priority:
        return Severity.warning
    p = priority.strip().lower()
    if p in ("debug", "informational", "info", "notice"):
        return Severity.info
    if p in ("warning", "warn"):
        return Severity.warning
    if p in ("error", "critical", "alert", "emergency"):
        return Severity.critical
    return Severity.warning


def _classify_unauthorized(status_code: Optional[int], message: str) -> Optional[str]:
    if status_code in (401, 403):
        return "unauthorized_access"
    m = (message or "").lower()
    if "unauthorized" in m or "forbidden" in m:
        return "unauthorized_access"
    return None


class Normalizer:
    def normalize_app(self, payload: AppLogIn) -> Dict[str, Any]:
        ts = parse_timestamp(payload.timestamp) or utc_now_iso()
        severity = _map_severity_from_level(payload.log_level) if payload.log_level else _map_severity_from_status(payload.status_code)

        message = payload.message
        event_type = "http_request" if payload.request_path or payload.method else "app_log"
        classification = _classify_unauthorized(payload.status_code, message)
        if classification == "unauthorized_access":
            severity = Severity.unauthorized_access

        normalized: Dict[str, Any] = {
            "event_id": payload.event_id or "",
            "timestamp": ts,
            "source_type": SourceType.app.value,
            "service_name": payload.service_name,
            "namespace": payload.namespace,
            "pod_name": payload.pod_name,
            "user_name": None,
            "severity": severity.value,
            "event_type": event_type,
            "message": message,
            "classification": classification,
            "action": payload.method,
            "resource": "http",
            "resource_name": payload.request_path,
            "status_code": payload.status_code,
            "tags": [],
            "raw_event": payload.model_dump(),
        }
        if payload.extra:
            normalized["raw_event"]["extra"] = payload.extra

        if not normalized["event_id"]:
            normalized["event_id"] = event_fingerprint(normalized)
        return normalized

    def normalize_k8s_audit(self, payload: K8sAuditLogIn) -> Dict[str, Any]:
        ts = (
            parse_timestamp(payload.requestReceivedTimestamp)
            or parse_timestamp(payload.stageTimestamp)
            or utc_now_iso()
        )
        code = payload.responseStatus.code if payload.responseStatus else None
        severity = _map_severity_from_status(code)

        namespace = payload.objectRef.namespace if payload.objectRef else None
        resource = payload.objectRef.resource if payload.objectRef else None
        name = payload.objectRef.name if payload.objectRef else None
        user = payload.user.username if payload.user else None

        event_type = "k8s_audit"
        verb = payload.verb or "unknown"
        uri = payload.requestURI or ""
        message = f"audit {verb} {resource or ''} {name or ''}".strip()
        if uri:
            message = f"{message} uri={uri}".strip()
        classification = _classify_unauthorized(code, message)
        if classification == "unauthorized_access":
            severity = Severity.unauthorized_access

        normalized: Dict[str, Any] = {
            "event_id": payload.auditID or "",
            "timestamp": ts,
            "source_type": SourceType.k8s_audit.value,
            "service_name": None,
            "namespace": namespace,
            "pod_name": None,
            "user_name": user,
            "severity": severity.value,
            "event_type": event_type,
            "message": message,
            "classification": classification,
            "action": verb,
            "resource": resource,
            "resource_name": name,
            "status_code": code,
            "tags": [],
            "raw_event": payload.model_dump(by_alias=True),
        }

        if not normalized["event_id"]:
            normalized["event_id"] = event_fingerprint(normalized)
        return normalized

    def normalize_falco(self, payload: FalcoAlertIn) -> Dict[str, Any]:
        ts = parse_timestamp(payload.time) or utc_now_iso()
        severity = _map_severity_from_falco_priority(payload.priority)

        ns = None
        pod = None
        if payload.k8s:
            ns = payload.k8s.ns_name
            pod = payload.k8s.pod_name

        rule = payload.rule or "falco_alert"
        msg = payload.output or rule

        normalized: Dict[str, Any] = {
            "event_id": "",
            "timestamp": ts,
            "source_type": SourceType.falco.value,
            "service_name": None,
            "namespace": ns,
            "pod_name": pod,
            "user_name": None,
            "severity": severity.value,
            "event_type": rule,
            "message": msg,
            "classification": None,
            "action": None,
            "resource": "runtime",
            "resource_name": payload.container.name if payload.container else None,
            "status_code": None,
            "tags": [],
            "raw_event": payload.model_dump(by_alias=True),
        }
        if payload.fields:
            normalized["raw_event"]["fields"] = payload.fields

        normalized["event_id"] = event_fingerprint(normalized)
        return normalized

