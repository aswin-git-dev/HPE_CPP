from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


router = APIRouter(prefix="/control-plane", tags=["control-plane"])


def _to_hpe_payload(source_urn: str, event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("raw_event", {})
    user = raw.get("user", {}) if isinstance(raw.get("user"), dict) else {}
    groups = user.get("groups", []) if isinstance(user.get("groups"), list) else []
    object_ref = raw.get("objectRef", {}) if isinstance(raw.get("objectRef"), dict) else {}
    source_ips = raw.get("sourceIPs", []) if isinstance(raw.get("sourceIPs"), list) else []

    req_ip = source_ips[0] if source_ips else None
    req_url = raw.get("requestURI") or ""
    verb = (raw.get("verb") or event.get("action") or "unknown").lower()
    resource = object_ref.get("resource") or event.get("resource") or "resource"
    evt_type = f"com.hpe.k8s.audit.{resource}.{verb}"

    return {
        "specversion": "1.0",
        "id": event.get("event_id"),
        "source": source_urn,
        "type": evt_type,
        "time": event.get("timestamp"),
        "dataContentType": "application/json",
        "dataSchema": "urn:hpe:security:audit:schema:v1",
        "securityRelevant": "yes",
        "data": {
            "source": {
                "subject": user.get("username"),
                "user": user.get("username"),
                "requestRoles": ",".join(groups) if groups else None,
                "requestPrivileges": None,
                "requestingService": raw.get("userAgent"),
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
                "encryption": "TLS",
                "destinationService": "kube-apiserver",
                "destinationuSerroles": None,
                "destinationuSerprivs": None,
            },
            "network": {
                "eventLocation": "k8s-control-plane",
                "apiCallResult": "Success" if (event.get("status_code") or 200) < 400 else "Failure",
                "eventCount": "1",
                # Extra fields used by the monitor UI filters (not required by CloudEvents).
                "classification": event.get("classification"),
                "severity": event.get("severity"),
                "statusCode": event.get("status_code"),
            },
            "object": {
                "name": event.get("resource_name"),
                "type": event.get("resource"),
                "owner": event.get("namespace"),
                "permissions": None,
                "accessResult": "Success" if (event.get("status_code") or 200) < 400 else "Failure",
                "assertedRoles": ",".join(groups) if groups else None,
                "assertedPrivs": None,
                "changes": event.get("message"),
                "createTime": event.get("timestamp"),
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


@router.get("/events/hpe")
def recent_events_hpe(request: Request, limit: int = 100):
    store = request.app.state.event_store_service
    settings = request.app.state.settings
    events: List[Dict[str, Any]] = store.latest(limit=limit)
    payloads = [_to_hpe_payload(settings.cluster_source_urn, e) for e in events]
    return {"events": payloads}


@router.get("/ui", response_class=HTMLResponse)
def control_plane_ui():
    return """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Control-Plane Monitor</title>
    <style>
      :root {
        --navbar: #3C5A3E;
        --major: #FAF9F6;
        --ink: #172016;
        --muted: #4a5b49;
        --card: #ffffff;
        --border: #dbe5d7;
        --shadow: rgba(0,0,0,0.06);
      }
      body { font-family: Arial, sans-serif; margin: 0; background: var(--major); color: var(--ink); }
      .wrap { max-width: 1200px; margin: 0 auto; padding: 16px; }
      .top { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; padding: 14px 16px; border-radius: 12px; background: var(--navbar); color: var(--major); }
      .title { font-size: 20px; font-weight: 800; letter-spacing: 0.1px; }
      .controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
      .btn, input, select { border: 1px solid var(--border); background: var(--card); color: var(--ink); border-radius: 10px; padding: 8px 10px; }
      .btn { cursor: pointer; }
      .btn-primary { background: var(--ink); color: #fff; border-color: var(--ink); }
      .btn-ghost { background: transparent; color: var(--major); border-color: rgba(250,249,246,0.35); }
      .muted { color: var(--muted); font-size: 12px; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px; box-shadow: 0 2px 12px var(--shadow); }
      .card h3 { margin: 0 0 10px; font-size: 15px; color: #2a3a2a; }
      .kv { display: grid; grid-template-columns: 1fr auto; gap: 6px; font-size: 13px; }
      .mono { font-family: Consolas, monospace; font-size: 12px; }
      .list { max-height: 420px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { padding: 8px; border-bottom: 1px solid #e7efe4; text-align: left; font-size: 12px; }
      th { position: sticky; top: 0; background: var(--major); }
      .pill { padding: 2px 8px; border-radius: 999px; border: 1px solid #cfe0cc; font-size: 11px; background: #f3f8f1; }
      .ok { color: #1f6b3a; border-color: #1f6b3a; background: #eaf8ef; }
      .warn { color: #7a4a00; border-color: #7a4a00; background: #fff3e2; }
      pre { white-space: pre-wrap; word-wrap: break-word; margin: 0; }
      .filterbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
      .filterbar .group { display: flex; flex-direction: column; gap: 4px; }
      .filterbar label { font-size: 12px; color: var(--muted); }
      .payload-actions { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
      .toast { position: fixed; right: 18px; bottom: 18px; background: var(--ink); color: #fff; padding: 10px 12px; border-radius: 12px; opacity: 0; transition: opacity 150ms ease; font-size: 12px; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="top">
        <div>
          <div class="title">Kubernetes Control-Plane Monitor</div>
          <div class="muted">Live pods by namespace + HPE audit payload stream</div>
        </div>
        <div class="controls">
          <label class="muted" style="color: rgba(250,249,246,0.9);">Limit</label>
          <input id="limit" type="number" min="1" max="500" value="50" />
          <button class="btn btn-ghost" onclick="refreshAll()">Refresh</button>
        </div>
      </div>

      <div class="filterbar">
        <div class="group" style="min-width: 180px;">
          <label>Namespace</label>
          <select id="nsFilter">
            <option value="all">All</option>
          </select>
        </div>
        <div class="group" style="min-width: 180px;">
          <label>Resource Type</label>
          <select id="resourceFilter">
            <option value="all">All</option>
          </select>
        </div>
        <div class="group" style="min-width: 160px;">
          <label>Result</label>
          <select id="resultFilter">
            <option value="all">All</option>
            <option value="Success">Success</option>
            <option value="Failure">Failure</option>
          </select>
        </div>
        <div class="group" style="min-width: 180px;">
          <label>Classification</label>
          <select id="classFilter">
            <option value="all">All</option>
            <option value="unauthorized_access">unauthorized_access</option>
          </select>
        </div>
        <div class="group" style="flex: 1; min-width: 240px;">
          <label>Search</label>
          <input id="qFilter" type="text" placeholder="user / method / uri / type..." style="width: 100%;" />
        </div>
        <div class="group" style="min-width: 160px;">
          <label>&nbsp;</label>
          <button class="btn btn-primary" onclick="renderEvents()">Apply</button>
        </div>
      </div>

      <div class="grid">
        <div class="card">
          <h3>Pods By Namespace</h3>
          <div id="podsSummary" class="kv"></div>
          <div class="list">
            <table>
              <thead><tr><th>Namespace</th><th>Pod</th><th>Status</th><th>Node</th><th>IP</th></tr></thead>
              <tbody id="podsBody"></tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <h3>Recent Audit Events</h3>
          <div class="list">
            <table>
              <thead><tr><th>Time</th><th>Type</th><th>User</th><th>Method</th><th>Result</th></tr></thead>
              <tbody id="eventsBody"></tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="card" style="margin-top:12px;">
        <h3>Selected Event Payload</h3>
        <div class="payload-actions">
          <button class="btn" onclick="copyPath()"> <span class=\"mono\">⧉</span> Copy Path</button>
          <button class="btn" onclick="copyJson()"> <span class=\"mono\">⧉</span> Copy JSON</button>
          <div style="margin-left:auto; min-width: 220px;">
            <div class="muted" style="margin-bottom:4px;">requestUrl</div>
            <div id="pathText" class="mono" style="padding: 10px; border: 1px solid var(--border); border-radius: 10px; background: #fbfcfb;">-</div>
          </div>
        </div>
        <pre id="payload" class="mono" style="padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: #fbfcfb;">Click any event row to inspect payload.</pre>
      </div>
    </div>
    <div id="toast" class="toast"></div>
    <script>
      let currentEvents = [];
      let visibleEvents = [];

      function toast(msg){
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.style.opacity = 1;
        setTimeout(()=>{ t.style.opacity = 0; }, 1400);
      }
      function esc(v){ return (v ?? "").toString().replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
      function formatIst(ts){
        if(!ts) return "";
        const d = new Date(ts);
        if (Number.isNaN(d.getTime())) return ts;
        return new Intl.DateTimeFormat("en-IN", {
          timeZone: "Asia/Kolkata",
          year: "numeric",
          month: "short",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: true
        }).format(d) + " IST";
      }
      function getFilters(){
        const pick = (id) => {
          const v = document.getElementById(id)?.value;
          return (v && v !== '') ? v : 'all';
        };
        return {
          ns: pick('nsFilter'),
          resource: pick('resourceFilter'),
          result: pick('resultFilter'),
          classification: pick('classFilter'),
          q: (document.getElementById('qFilter')?.value ?? '').trim().toLowerCase(),
        };
      }

      function applyFilters(events){
        const f = getFilters();
        return (events || []).filter(e=>{
          const src = e.data?.source || {};
          const net = e.data?.network || {};
          const obj = e.data?.object || {};

          const ownerNs = obj.owner || '';
          const resourceType = obj.type || '';
          const apiCallResult = net.apiCallResult || '';
          const classification = net.classification || '';

          if(f.ns !== 'all' && ownerNs !== f.ns) return false;
          if(f.resource !== 'all' && resourceType !== f.resource) return false;
          if(f.result !== 'all' && apiCallResult !== f.result) return false;
          if(f.classification !== 'all' && classification !== f.classification) return false;

          if(f.q){
            const hay = [
              e.type,
              src.subject, src.user, src.requestMethod, src.requestUrl,
              obj.owner, obj.type, obj.name,
              obj.changes
            ].join(' ').toLowerCase();
            if(!hay.includes(f.q)) return false;
          }
          return true;
        });
      }

      async function copyText(text){
        if(text == null) text = '';
        try {
          await navigator.clipboard.writeText(text);
          toast('Copied');
        } catch {
          const ta = document.createElement('textarea');
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          toast('Copied');
        }
      }
      function copyPath(){
        const e = document.getElementById('pathText')?.textContent ?? '';
        copyText(e === '-' ? '' : e);
      }
      function copyJson(){
        const text = document.getElementById('payload')?.textContent ?? '';
        copyText(text);
      }

      async function refreshPods(){
        const r = await fetch('/control-plane/pods');
        const j = await r.json();
        const ns = j.namespaces || {};
        const body = document.getElementById('podsBody');
        const summary = document.getElementById('podsSummary');
        body.innerHTML = '';
        let total = 0;
        Object.entries(ns).sort((a,b)=>a[0].localeCompare(b[0])).forEach(([name,pods])=>{
          (pods || []).forEach(p=>{
            total++;
            const phase = (p.phase || '').toLowerCase();
            const cls = phase === 'running' ? 'ok' : 'warn';
            body.innerHTML += `<tr><td>${esc(name)}</td><td>${esc(p.name)}</td><td><span class="pill ${cls}">${esc(p.phase)}</span></td><td>${esc(p.node)}</td><td>${esc(p.pod_ip)}</td></tr>`;
          });
        });
        summary.innerHTML = `<div>Namespaces</div><div>${Object.keys(ns).length}</div><div>Total Pods</div><div>${total}</div>`;

        // Populate namespace filter from the live pod list.
        const nsSel = document.getElementById('nsFilter');
        if(nsSel){
          const existing = nsSel.value;
          const keys = Object.keys(ns).sort((a,b)=>a.localeCompare(b));
          nsSel.innerHTML = `<option value="all">All</option>` + keys.map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join('');
          if(existing && keys.includes(existing)) nsSel.value = existing;
        }
      }
      async function refreshEvents(){
        const limit = Number(document.getElementById('limit').value || 50);
        const fetchLimit = Math.min(400, Math.max(limit, 200));
        const r = await fetch(`/control-plane/events/hpe?limit=${fetchLimit}`);
        const j = await r.json();
        currentEvents = j.events || [];
        // Populate resource filter from the events we fetched.
        const resourceSel = document.getElementById('resourceFilter');
        if(resourceSel){
          const existing = resourceSel.value;
          const types = Array.from(new Set(currentEvents.map(e=>e.data?.object?.type).filter(Boolean))).sort((a,b)=>String(a).localeCompare(String(b)));
          resourceSel.innerHTML = `<option value="all">All</option>` + types.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join('');
          if(existing && types.includes(existing)) resourceSel.value = existing;
        }

        renderEvents();
      }
      function renderEvents(){
        const limit = Number(document.getElementById('limit').value || 50);
        visibleEvents = applyFilters(currentEvents).slice(0, limit);
        const body = document.getElementById('eventsBody');
        body.innerHTML = '';
        visibleEvents.forEach((e, i)=>{
          const src = e.data?.source || {};
          const net = e.data?.network || {};
          const cls = (net.apiCallResult || '').toLowerCase() === 'success' ? 'ok' : 'warn';
          body.innerHTML += `<tr onclick="showEvent(${i})" style="cursor:pointer"><td title="${esc(e.time)}">${esc(formatIst(e.time))}</td><td>${esc(e.type)}</td><td>${esc(src.subject || src.user)}</td><td>${esc(src.requestMethod)}</td><td><span class="pill ${cls}">${esc(net.apiCallResult)}</span></td></tr>`;
        });
      }
      function showEvent(i){
        const e = visibleEvents[i] || {};
        const pre = document.getElementById('payload');
        pre.textContent = JSON.stringify(e, null, 2);
        const src = e.data?.source || {};
        document.getElementById('pathText').textContent = src.requestUrl || '-';
      }
      async function refreshAll(){
        await Promise.all([refreshPods(), refreshEvents()]);
      }
      refreshAll();
    </script>
  </body>
</html>
"""
