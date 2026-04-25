from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.control_plane_ui_build import build_control_plane_ui_html

router = APIRouter(prefix="/control-plane", tags=["control-plane"])


def _slug_falco_rule(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return s[:96] if s else "alert"


MONITOR_DATA_SCHEMA = "urn:microservices-monitor:security:audit:schema:v1"


def _to_monitor_falco_payload(source_urn: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Falco events have no apiserver user or request stage; map workload + detection source for the UI."""
    raw = event.get("raw_event", {}) if isinstance(event.get("raw_event"), dict) else {}
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}

    ns = event.get("namespace") or fields.get("k8s.ns.name")
    pod = event.get("pod_name") or fields.get("k8s.pod.name")
    proc = fields.get("proc.name") or fields.get("proc.exepath")
    container = event.get("resource_name") or fields.get("container.name")

    if ns and pod:
        subject: Optional[str] = f"{ns}/{pod}"
    elif pod:
        subject = pod
    elif ns:
        subject = ns
    elif container:
        subject = str(container)
    elif proc:
        subject = str(proc)
    else:
        subject = raw.get("hostname") or None

    rule = event.get("event_type") or "falco_alert"
    evt_type = f"com.microservicesmonitor.falco.{_slug_falco_rule(str(rule))}"
    msg = event.get("message") or rule
    falco_src = raw.get("source")
    if isinstance(falco_src, str) and falco_src.strip():
        stage = falco_src.strip()
    else:
        stage = "runtime"

    status_code = event.get("status_code")
    call_result = "Success" if (status_code or 200) < 400 else "Failure"
    security_relevant = event.get("security_relevant") or "yes"

    return {
        "specversion": "1.0",
        "id": event.get("event_id"),
        "source": source_urn,
        "type": evt_type,
        "time": event.get("timestamp"),
        "invocationtime": event.get("invocation_time") or event.get("timestamp"),
        "completetime": event.get("completion_time") or event.get("timestamp"),
        "dataContentType": "application/json",
        "dataSchema": MONITOR_DATA_SCHEMA,
        "securityRelevant": security_relevant,
        "data": {
            "source": {
                "subject": subject,
                "user": subject,
                "requestRoles": None,
                "requestPrivileges": f"falco:{rule}",
                "requestingService": "falco",
                "requestMethod": "DETECTION",
                "requestUrl": msg[:512] if isinstance(msg, str) else str(msg)[:512],
                "requestSource": fields.get("fd.name") or fields.get("fd.sip"),
                "requestPort": None,
            },
            "destination": {
                "requestedCall": f"{rule}: {msg[:280]}" if isinstance(msg, str) else str(rule),
                "destination": "container-runtime",
                "destinationPort": None,
                "l4protocol": None,
                "protocolBinding": None,
                "encryption": None,
                "destinationService": "falco",
                "destinationUserRoles": None,
                "destinationUserPrivs": None,
                "apiGroup": None,
            },
            "network": {
                "eventLocation": "container-runtime",
                "stage": stage,
                "apiCallResult": call_result,
                "eventCount": "1",
                "statusCode": status_code,
                "classification": event.get("classification"),
                "severity": event.get("severity"),
            },
            "object": {
                "objname": pod or container or rule,
                "objtype": "falco",
                "objowner": ns,
                "objperms": f"falco:{rule}",
                "objaccessresult": call_result,
                "assertedroles": None,
                "assertedprivs": f"falco:{rule}",
                "objchanges": msg,
                "objcreatetime": event.get("invocation_time") or event.get("timestamp"),
                "objmodtime": event.get("completion_time") or None,
                "objdeletetime": None,
            },
        },
    }


def _to_monitor_payload(source_urn: str, event: Dict[str, Any]) -> Dict[str, Any]:
    if event.get("source_type") == "falco":
        return _to_monitor_falco_payload(source_urn, event)

    raw = event.get("raw_event", {})
    user_raw = raw.get("user", {}) if isinstance(raw.get("user"), dict) else {}
    groups_raw = user_raw.get("groups", []) if isinstance(user_raw.get("groups"), list) else []

    # Prefer enriched fields from normalizer; fall back to raw audit JSON
    user_name = event.get("effective_user") or event.get("user_name") or user_raw.get("username")
    user_uid = event.get("user_uid") or user_raw.get("uid")
    groups = event.get("user_groups") or groups_raw
    is_impersonated = event.get("is_impersonated", False)

    object_ref = raw.get("objectRef", {}) if isinstance(raw.get("objectRef"), dict) else {}
    source_ips = raw.get("sourceIPs", []) if isinstance(raw.get("sourceIPs"), list) else []

    req_ip = source_ips[0] if source_ips else None
    req_url = raw.get("requestURI") or event.get("resource_name") or ""
    verb = (raw.get("verb") or event.get("action") or "unknown").lower()
    resource = event.get("resource") or object_ref.get("resource") or "resource"
    subresource = event.get("subresource") or object_ref.get("subresource") or ""
    api_group = event.get("api_group") or object_ref.get("apiGroup") or ""
    stage = event.get("stage") or ""

    # CloudEvents `type` e.g. com.microservicesmonitor.k8s.audit.secrets.create
    resource_label = f"{resource}.{subresource}" if subresource else resource
    evt_type = f"com.microservicesmonitor.k8s.audit.{resource_label}.{verb}"

    # Derived privileges from normalizer
    derived_privileges = event.get("derived_privileges")
    # Roles: original user groups + impersonation note
    roles_str = ",".join(groups) if groups else None
    if is_impersonated and event.get("user_name"):
        roles_str = f"impersonating:{event.get('user_name')}" + (f",{roles_str}" if roles_str else "")

    status_code = event.get("status_code")
    call_result = "Success" if (status_code or 200) < 400 else "Failure"

    # securityRelevant from normalizer; fall back to heuristic
    security_relevant = event.get("security_relevant") or "yes"

    return {
        "specversion": "1.0",
        "id": event.get("event_id"),
        "source": source_urn,
        "type": evt_type,
        "time": event.get("timestamp"),
        "invocationtime": event.get("invocation_time") or event.get("timestamp"),
        "completetime": event.get("completion_time") or event.get("timestamp"),
        "dataContentType": "application/json",
        "dataSchema": MONITOR_DATA_SCHEMA,
        "securityRelevant": security_relevant,
        "data": {
            "source": {
                "subject": user_name,
                "user": user_uid or user_name,
                "requestRoles": roles_str,
                "requestPrivileges": derived_privileges,
                "requestingService": event.get("user_agent") or raw.get("userAgent"),
                "requestMethod": verb.upper(),
                "requestUrl": req_url,
                "requestSource": req_ip,
                "requestPort": None,
            },
            "destination": {
                "requestedCall": f"{verb.upper()} {req_url}".strip(),
                "destination": "kube-apiserver",
                "destinationPort": 6443,
                "l4protocol": "TCP",
                "protocolBinding": "TLS",
                "encryption": "TLS 1.3",
                "destinationService": "kube-apiserver",
                "destinationUserRoles": None,
                "destinationUserPrivs": None,
                "apiGroup": api_group or None,
            },
            "network": {
                "eventLocation": "k8s-control-plane",
                "stage": stage or None,
                "apiCallResult": call_result,
                "eventCount": "1",
                "statusCode": status_code,
                # Monitor UI filter helpers (non-schema)
                "classification": event.get("classification"),
                "severity": event.get("severity"),
            },
            "object": {
                "objname": event.get("resource_name"),
                "objtype": resource,
                "objowner": event.get("namespace"),
                "objperms": derived_privileges,
                "objaccessresult": call_result,
                "assertedroles": roles_str,
                "assertedprivs": derived_privileges,
                "objchanges": event.get("message"),
                "objcreatetime": event.get("invocation_time") or event.get("timestamp"),
                "objmodtime": event.get("completion_time") or None,
                "objdeletetime": event.get("completion_time") if verb == "delete" else None,
            },
        },
    }


@router.get("/pods")
def pods_by_namespace(request: Request):
    monitor = request.app.state.k8s_monitor_service
    return {"namespaces": monitor.pods_by_namespace()}


@router.get("/events")
def recent_events(request: Request, limit: int = 100):
    store = request.app.state.event_store_service
    return {"events": store.latest(limit=limit)}


@router.get("/events/monitor")
def recent_events_monitor(request: Request, limit: int = 100):
    store = request.app.state.event_store_service
    settings = request.app.state.settings
    events: List[Dict[str, Any]] = store.latest(limit=limit)
    payloads = [_to_monitor_payload(settings.cluster_source_urn, e) for e in events]
    return {"events": payloads}


@router.get("/ui")
def control_plane_ui():
    """Return the same document as ``k8s/sample-control-plane-ui.html`` (minus demo/mock script): table ``tbl-pods``, ``colgroup``, ``tbody#podsBody``."""
    return HTMLResponse(
        content=build_control_plane_ui_html(),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/architecture/data")
def architecture_data(request: Request):
    return request.app.state.k8s_monitor_service.cluster_architecture()


@router.get("/architecture/ui", response_class=HTMLResponse)
def architecture_ui_page():
    return _ARCHITECTURE_HTML


_ARCHITECTURE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cluster architecture</title>
  <style>
    :root {
      --navbar: #3C5A3E;
      --major: #FAF9F6;
      --ink: #172016;
      --muted: #4a5b49;
      --card: #ffffff;
      --border: #dbe5d7;
      --shadow: rgba(0,0,0,0.07);
      --accent-cp: #2d4a30;
      --accent-w1: #4a6b4e;
      --accent-w2: #5f7d63;
      --phase-ok: #1f6b3a;
      --phase-warn: #b8860b;
      --phase-bad: #b23c3c;
    }
    * { box-sizing: border-box; }
    body { font-family: Segoe UI, Arial, sans-serif; margin: 0; background: var(--major); color: var(--ink); min-height: 100vh; }
    .wrap { max-width: 1400px; margin: 0 auto; padding: 16px; }
    .top {
      display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap;
      margin-bottom: 16px; padding: 14px 18px; border-radius: 14px; background: var(--navbar); color: var(--major);
      box-shadow: 0 4px 20px var(--shadow);
    }
    .top h1 { margin: 0; font-size: 1.35rem; font-weight: 800; letter-spacing: 0.02em; }
    .top .sub { margin: 6px 0 0; font-size: 0.85rem; opacity: 0.92; max-width: 520px; line-height: 1.4; }
    .top a { color: rgba(250,249,246,0.95); text-decoration: underline; }
    .btn { border: 1px solid rgba(250,249,246,0.35); background: transparent; color: var(--major); border-radius: 10px; padding: 8px 14px; cursor: pointer; font-size: 0.9rem; }
    .btn:hover { background: rgba(255,255,255,0.08); }
    .legend { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 14px; font-size: 0.8rem; color: var(--muted); }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; }
    .nodes-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; margin-bottom: 22px; }
    .node-card {
      background: var(--card); border: 1px solid var(--border); border-radius: 14px; overflow: hidden;
      box-shadow: 0 2px 14px var(--shadow);
    }
    .node-head {
      padding: 12px 14px; color: #fff; font-weight: 700; font-size: 0.95rem;
      display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;
    }
    .node-head.cp { background: linear-gradient(135deg, var(--accent-cp), #3C5A3E); }
    .node-head.worker { background: linear-gradient(135deg, var(--accent-w1), var(--accent-w2)); }
    .node-head.pending { background: linear-gradient(135deg, #8a7a40, #a8944a); }
    .node-meta { font-size: 0.72rem; font-weight: 500; opacity: 0.92; margin-top: 4px; }
    .node-body { padding: 10px 12px 14px; }
    .ns-block { margin-bottom: 12px; border-left: 4px solid #8fbc8f; padding: 8px 10px 10px; background: #f7faf6; border-radius: 0 10px 10px 0; }
    .ns-title { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 700; margin-bottom: 6px; }
    .pod-row { display: flex; flex-wrap: wrap; gap: 6px; }
    .pod {
      font-size: 0.72rem; padding: 4px 8px; border-radius: 8px; border: 1px solid var(--border);
      background: #fff; max-width: 100%; word-break: break-all;
    }
    .pod .app { font-weight: 600; color: var(--ink); }
    .pod .phase { font-size: 0.65rem; margin-top: 2px; }
    .phase-Running { color: var(--phase-ok); font-weight: 600; }
    .phase-Pending, .phase-ContainerCreating { color: var(--phase-warn); }
    .phase-Failed, .phase-Unknown, .phase-CrashLoopBackOff, .phase-ErrImagePull, .phase-ImagePullBackOff { color: var(--phase-bad); }
    .svc-section { margin-top: 8px; }
    .svc-section h2 { font-size: 1rem; margin: 0 0 10px; color: var(--ink); }
    .svc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
    .svc-ns { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; }
    .svc-ns .ns { font-weight: 700; font-size: 0.85rem; margin-bottom: 8px; color: #2a3a2a; }
    .svc-line { font-size: 0.75rem; padding: 3px 0; border-bottom: 1px solid #eef4ec; display: flex; justify-content: space-between; gap: 8px; }
    .svc-line:last-child { border-bottom: none; }
    .err { padding: 14px; background: #fff3f0; border: 1px solid #e8c4bc; border-radius: 12px; color: #6b2a2a; }
    .empty { color: var(--muted); font-size: 0.9rem; padding: 20px; text-align: center; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>Cluster architecture</h1>
        <p class="sub">Live view: nodes (control plane + workers), namespaces, pods, and ClusterIP services — same palette as the control-plane monitor.</p>
        <p class="sub"><a href="/control-plane/ui">← Control-plane monitor</a></p>
      </div>
      <div><button type="button" class="btn" onclick="loadArch()">Refresh</button></div>
    </div>
    <div class="legend">
      <span><span class="dot" style="background:#2d4a30"></span> Control plane</span>
      <span><span class="dot" style="background:#5f7d63"></span> Worker</span>
      <span><span class="dot" style="background:#c9a227"></span> Unscheduled / pending</span>
    </div>
    <div id="root"></div>
  </div>
  <script>
    function phaseClass(ph) {
      const p = (ph || '').replace(/[^a-zA-Z0-9_-]/g, '');
      return 'phase-' + (p || 'Unknown');
    }
    function render(data) {
      const root = document.getElementById('root');
      if (data.error === 'not_in_cluster') {
        root.innerHTML = '<div class="err">Not running in-cluster (no K8s credentials). Deploy audit-service inside the cluster to see this map.</div>';
        return;
      }
      if (data.message && (data.error === 'kubernetes_api' || !((data.nodes || []).length))) {
        root.innerHTML = '<div class="err">' + escapeHtml(data.message) + '<br/><br/><span style="font-size:0.85rem">Fix: kubectl apply -f audit-service.yaml (ClusterRole) then kubectl rollout restart -n ecommerce deployment/audit-service</span></div>';
        return;
      }
      const nodes = data.nodes || [];
      const svcMap = data.services_by_namespace || {};
      if (!nodes.length) {
        root.innerHTML = '<div class="empty">No nodes reported.</div>';
        return;
      }
      let html = '<div class="nodes-grid">';
      for (const node of nodes) {
        const role = node.role || '';
        const headClass = role === 'control-plane' ? 'cp' : (role === 'pending' ? 'pending' : 'worker');
        const label = node.monitor_node_name || node.monitor_node_group || '';
        const sub = [label && ('Label: ' + label), 'role: ' + role].filter(Boolean).join(' · ');
        html += '<div class="node-card"><div class="node-head ' + headClass + '"><div><div>' + escapeHtml(node.name) + '</div>';
        if (sub) html += '<div class="node-meta">' + escapeHtml(sub) + '</div>';
        html += '</div></div><div class="node-body">';
        const nss = node.namespaces || [];
        if (!nss.length) {
          html += '<div class="empty" style="padding:12px;">No workloads on this node.</div>';
        } else {
          for (const block of nss) {
            html += '<div class="ns-block"><div class="ns-title">' + escapeHtml(block.name) + '</div><div class="pod-row">';
            for (const pod of (block.pods || [])) {
              const app = pod.app || pod.name;
              html += '<div class="pod"><div class="app">' + escapeHtml(app) + '</div>';
              html += '<div class="phase ' + phaseClass(pod.phase) + '">' + escapeHtml(pod.phase) + '</div>';
              html += '<div style="font-size:0.65rem;color:#888;margin-top:2px;">' + escapeHtml(pod.name) + '</div></div>';
            }
            html += '</div></div>';
          }
        }
        html += '</div></div>';
      }
      html += '</div>';
      html += '<div class="svc-section"><h2>Services by namespace</h2><div class="svc-grid">';
      const nsKeys = Object.keys(svcMap).sort();
      if (!nsKeys.length) {
        html += '<div class="empty">No services (or only default/kubernetes).</div>';
      } else {
        for (const ns of nsKeys) {
          html += '<div class="svc-ns"><div class="ns">' + escapeHtml(ns) + '</div>';
          for (const s of svcMap[ns]) {
            html += '<div class="svc-line"><span>' + escapeHtml(s.name) + '</span><span style="color:#888">' + escapeHtml(s.type) + '</span></div>';
          }
          html += '</div>';
        }
      }
      html += '</div></div>';
      root.innerHTML = html;
    }
    function escapeHtml(t) {
      if (!t) return '';
      const d = document.createElement('div');
      d.textContent = t;
      return d.innerHTML;
    }
    async function loadArch() {
      const root = document.getElementById('root');
      root.innerHTML = '<div class="empty">Loading…</div>';
      try {
        const r = await fetch('/control-plane/architecture/data');
        const data = await r.json();
        render(data);
      } catch (e) {
        root.innerHTML = '<div class="err">Failed to load: ' + escapeHtml(String(e)) + '</div>';
      }
    }
    loadArch();
  </script>
</body>
</html>
"""
