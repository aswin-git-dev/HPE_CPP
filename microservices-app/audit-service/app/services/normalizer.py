from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.schemas import AppLogIn, FalcoAlertIn, K8sAuditLogIn, Severity, SourceType
from app.utils.hash_utils import event_fingerprint
from app.utils.time_utils import parse_timestamp, utc_now_iso


# ── Severity helpers ──────────────────────────────────────────────────────────

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


# ── Classification helpers ────────────────────────────────────────────────────

# Resources whose mutation always gets rbac_change classification.
_RBAC_RESOURCES = frozenset({
    "roles", "rolebindings", "clusterroles", "clusterrolebindings",
})

# Resources whose read or mutation always gets secret_access classification.
_SECRET_RESOURCES = frozenset({"secrets"})

# Subresources that mean interactive runtime access.
_EXEC_SUBRESOURCES = frozenset({"exec", "attach", "portforward"})

# Resources that carry privilege delegation semantics.
_PRIVILEGE_RESOURCES = frozenset({
    "serviceaccounts", "serviceaccounts/token",
    "clusterrolebindings", "clusterroles",
})

# Destructive verbs on workloads worth tagging as elevated-impact.
_DESTRUCTIVE_VERBS = frozenset({"delete"})
_WORKLOAD_RESOURCES = frozenset({
    "deployments", "statefulsets", "daemonsets", "replicasets",
    "pods", "namespaces",
})


def _classify(
    status_code: Optional[int],
    verb: Optional[str],
    resource: Optional[str],
    subresource: Optional[str],
    message: str,
) -> Optional[str]:
    v = (verb or "").lower()
    r = (resource or "").lower()
    sr = (subresource or "").lower()
    m = (message or "").lower()

    # Unauthorized / forbidden — highest priority check
    if status_code in (401, 403):
        return "unauthorized_access"
    if "unauthorized" in m or "forbidden" in m:
        return "unauthorized_access"

    # Pod exec / attach / portforward — interactive runtime access
    if sr in _EXEC_SUBRESOURCES or v == "exec":
        return "exec_access"

    # RBAC mutations
    if r in _RBAC_RESOURCES and v in ("create", "update", "patch", "delete"):
        return "rbac_change"

    # Secret access (any verb)
    if r in _SECRET_RESOURCES:
        return "secret_access"

    # Privilege escalation candidate: service account token creation or identity provisioning
    if r in _PRIVILEGE_RESOURCES and v in ("create", "delete"):
        return "privilege_escalation_candidate"

    # Destructive change on workloads
    if v in _DESTRUCTIVE_VERBS and r in _WORKLOAD_RESOURCES:
        return "destructive_change"

    # ConfigMap / generic config mutations
    if r in ("configmaps",) and v in ("create", "update", "patch", "delete"):
        return "config_change"

    # Admission webhook changes (can bypass security controls)
    if r in ("mutatingwebhookconfigurations", "validatingwebhookconfigurations"):
        return "admission_webhook_change"

    return None


def _is_security_relevant(
    classification: Optional[str],
    verb: Optional[str],
    resource: Optional[str],
    subresource: Optional[str],
    status_code: Optional[int],
) -> str:
    """Return 'yes' for security-relevant events, 'no' for noise."""
    if classification:
        return "yes"
    v = (verb or "").lower()
    r = (resource or "").lower()
    sr = (subresource or "").lower()

    if v in ("create", "update", "patch", "delete"):
        return "yes"
    if sr in _EXEC_SUBRESOURCES:
        return "yes"
    if status_code in (401, 403):
        return "yes"
    if r in _SECRET_RESOURCES or r in _RBAC_RESOURCES:
        return "yes"
    return "no"


def _derive_privileges(verb: Optional[str], resource: Optional[str], subresource: Optional[str]) -> Optional[str]:
    """Best-effort privilege string from verb + resource."""
    v = (verb or "").lower()
    r = (resource or "").lower()
    sr = (subresource or "").lower()

    parts = []
    if v:
        parts.append(v)
    target = f"{r}/{sr}" if sr else r
    if target:
        parts.append(target)
    return ",".join(parts) if parts else None


# ── Normalizer ────────────────────────────────────────────────────────────────

class Normalizer:
    def normalize_app(self, payload: AppLogIn) -> Dict[str, Any]:
        ts = parse_timestamp(payload.timestamp) or utc_now_iso()
        severity = _map_severity_from_level(payload.log_level) if payload.log_level else _map_severity_from_status(payload.status_code)

        message = payload.message
        event_type = "http_request" if payload.request_path or payload.method else "app_log"
        classification = _classify(payload.status_code, payload.method, "http", None, message)
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
            "security_relevant": _is_security_relevant(classification, payload.method, "http", None, payload.status_code),
            "tags": [],
            "raw_event": payload.model_dump(),
        }
        if payload.extra:
            normalized["raw_event"]["extra"] = payload.extra

        if not normalized["event_id"]:
            normalized["event_id"] = event_fingerprint(normalized)
        return normalized

    def normalize_k8s_audit(self, payload: K8sAuditLogIn) -> Dict[str, Any]:
        # Invocation = when request was received; completion = stage timestamp
        invocation_ts = parse_timestamp(payload.requestReceivedTimestamp) or utc_now_iso()
        completion_ts = parse_timestamp(payload.stageTimestamp) or invocation_ts
        # Canonical event timestamp = invocation time (earliest)
        ts = invocation_ts

        code = payload.responseStatus.code if payload.responseStatus else None
        status_reason = payload.responseStatus.reason if payload.responseStatus else None
        severity = _map_severity_from_status(code)

        namespace = payload.objectRef.namespace if payload.objectRef else None
        resource = payload.objectRef.resource if payload.objectRef else None
        subresource = payload.objectRef.subresource if payload.objectRef else None
        name = payload.objectRef.name if payload.objectRef else None
        api_group = payload.objectRef.apiGroup if payload.objectRef else None
        api_version = payload.objectRef.apiVersion if payload.objectRef else None

        user = payload.user.username if payload.user else None
        user_uid = payload.user.uid if payload.user else None
        groups = payload.user.groups if payload.user else []

        # If the request was impersonated, prefer effective (impersonated) identity for classification
        effective_user = user
        if payload.impersonatedUser and payload.impersonatedUser.username:
            effective_user = payload.impersonatedUser.username

        verb = payload.verb or "unknown"
        uri = payload.requestURI or ""
        stage = payload.stage or ""

        # Build human-readable message
        sr_label = f"/{subresource}" if subresource else ""
        message = f"[{stage}] {verb} {resource or ''}{sr_label} {name or ''}".strip()
        if uri:
            message = f"{message} uri={uri}".strip()

        classification = _classify(code, verb, resource, subresource, message)
        if classification == "unauthorized_access":
            severity = Severity.unauthorized_access

        security_relevant = _is_security_relevant(classification, verb, resource, subresource, code)

        normalized: Dict[str, Any] = {
            "event_id": payload.auditID or "",
            "timestamp": ts,
            "invocation_time": invocation_ts,
            "completion_time": completion_ts,
            "stage": stage,
            "source_type": SourceType.k8s_audit.value,
            "service_name": None,
            "namespace": namespace,
            "pod_name": None,
            "user_name": user,
            "user_uid": user_uid,
            "user_groups": groups or [],
            "effective_user": effective_user,
            "is_impersonated": bool(payload.impersonatedUser and payload.impersonatedUser.username),
            "user_agent": payload.userAgent,
            "severity": severity.value,
            "event_type": "k8s_audit",
            "message": message,
            "classification": classification,
            "security_relevant": security_relevant,
            "action": verb,
            "resource": resource,
            "subresource": subresource,
            "resource_name": name,
            "api_group": api_group,
            "api_version": api_version,
            "status_code": code,
            "status_reason": status_reason,
            "derived_privileges": _derive_privileges(verb, resource, subresource),
            "tags": [],
            "annotations": payload.annotations,
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
            "invocation_time": ts,
            "completion_time": ts,
            "stage": None,
            "source_type": SourceType.falco.value,
            "service_name": None,
            "namespace": ns,
            "pod_name": pod,
            "user_name": None,
            "user_uid": None,
            "user_groups": [],
            "effective_user": None,
            "is_impersonated": False,
            "user_agent": None,
            "severity": severity.value,
            "event_type": rule,
            "message": msg,
            "classification": None,
            "security_relevant": "yes",
            "action": None,
            "resource": "runtime",
            "subresource": None,
            "resource_name": payload.container.name if payload.container else None,
            "api_group": None,
            "api_version": None,
            "status_code": None,
            "status_reason": None,
            "derived_privileges": None,
            "tags": [],
            "annotations": {},
            "raw_event": payload.model_dump(by_alias=True),
        }
        if payload.fields:
            normalized["raw_event"]["fields"] = payload.fields

        normalized["event_id"] = event_fingerprint(normalized)
        return normalized
