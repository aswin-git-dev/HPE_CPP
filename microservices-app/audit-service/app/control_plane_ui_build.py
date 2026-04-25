"""Build production HTML for GET /control-plane/ui from k8s/sample-control-plane-ui.html."""
from __future__ import annotations

import re
from pathlib import Path

# audit-service/app/control_plane_ui_build.py -> parents[1] = audit-service root
_AUDIT_ROOT = Path(__file__).resolve().parents[1]
_K8S_SAMPLE = _AUDIT_ROOT.parent / "k8s" / "sample-control-plane-ui.html"
_BUNDLED = Path(__file__).resolve().parent / "static" / "control-plane-ui.html"

# Substrings that must remain in built HTML so GET /control-plane/ui matches
# microservices-app/k8s/sample-control-plane-ui.html (Pods by Namespace table).
_PODS_TABLE_MARKERS = (
    "tbl-wrap--pods",
    "tbl-pods",
    "table-layout:fixed!important",
    'style="width:14%"',
    "word-break:break-all!important",
    "<colgroup>",
    'id="podsBody"',
    "col-status",
    "<thead>",
    "<tbody",
)


def _validate_control_plane_ui(html: str) -> None:
    missing = [m for m in _PODS_TABLE_MARKERS if m not in html]
    if missing:
        raise ValueError(
            "control-plane UI: built HTML missing Pods-by-Namespace table fragments: "
            + ", ".join(repr(m) for m in missing)
        )


def _transform_sample_to_production(html: str) -> str:
    html = re.sub(
        r'<div class="demo-banner"[^>]*>.*?</div>\s*',
        "",
        html,
        count=1,
        flags=re.DOTALL,
    )
    html = html.replace(
        '<a id="archLink" href="/control-plane/architecture/ui">',
        '<a href="/control-plane/architecture/ui">',
    )

    old_pods = """  async function refreshPods(){
    let j;
    if (DEMO) j = MOCK_PODS;
    else { const r = await fetch('/control-plane/pods'); j = await r.json(); }"""
    new_pods = """  async function refreshPods(){
    const r = await fetch('/control-plane/pods');
    const j = await r.json();"""
    if old_pods not in html:
        raise ValueError("control plane UI: refreshPods block not found")
    html = html.replace(old_pods, new_pods, 1)

    old_ev = """  async function refreshEvents(){
    const limit=Number(document.getElementById('limit').value||50);
    const fetchLimit=Math.max(limit,400);  // always fetch at least 400 for export
    let j;
    if (DEMO) { j = MOCK_EVENTS; }
    else {
      j = null;
      try {
        const r=await fetch(`/control-plane/events/monitor?limit=${fetchLimit}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        j = await r.json();
      } catch(err) {
        await new Promise(res=>setTimeout(res,1500));
        try {
          const r2=await fetch(`/control-plane/events/monitor?limit=${fetchLimit}`);
          if (r2.ok) j = await r2.json();
        } catch(_) {}
      }
      if (!j) { toast('Refresh failed — keeping existing events'); return; }
      const incoming = j.events||[];
      if (incoming.length === 0 && currentEvents.length > 0) {
        toast('Server returned 0 events — retaining last known data');
        return;
      }
    }
    currentEvents=j.events||[];
    const resourceSel=document.getElementById('resourceFilter');
    if(resourceSel){
      const cur=resourceSel.value;
      const types=Array.from(new Set(currentEvents.map(e=>e.data?.object?.objtype).filter(Boolean))).sort();
      resourceSel.innerHTML='<option value="all">All</option>'+types.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join('');
      if(cur&&types.includes(cur)) resourceSel.value=cur;
    }
    renderEvents();
  }"""
    new_ev = """  async function refreshEvents(){
    const limit=Number(document.getElementById('limit').value||50);
    const fetchLimit=Math.max(limit,400);  // always fetch at least 400 for export
    let j = null;
    try {
      const r=await fetch(`/control-plane/events/monitor?limit=${fetchLimit}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      j = await r.json();
    } catch(err) {
      await new Promise(res=>setTimeout(res,1500));
      try {
        const r2=await fetch(`/control-plane/events/monitor?limit=${fetchLimit}`);
        if (r2.ok) j = await r2.json();
      } catch(_) {}
    }
    if (!j) { toast('Refresh failed — keeping existing events'); return; }
    const incoming = j.events||[];
    if (incoming.length === 0 && currentEvents.length > 0) {
      toast('Server returned 0 events — retaining last known data');
      return;
    }
    currentEvents=j.events||[];
    const resourceSel=document.getElementById('resourceFilter');
    if(resourceSel){
      const cur=resourceSel.value;
      const types=Array.from(new Set(currentEvents.map(e=>e.data?.object?.objtype).filter(Boolean))).sort();
      resourceSel.innerHTML='<option value="all">All</option>'+types.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join('');
      if(cur&&types.includes(cur)) resourceSel.value=cur;
    }
    renderEvents();
  }"""
    if old_ev not in html:
        raise ValueError("control plane UI: refreshEvents block not found")
    html = html.replace(old_ev, new_ev, 1)

    start = html.find("  const DEMO")
    end = html.find("  let currentEvents = [];")
    if start == -1 or end == -1:
        raise ValueError("control plane UI: bad script markers (const DEMO / let currentEvents)")
    html = html[:start] + html[end:]

    html = html.replace(
        "<title>microservices-Monitor (sample)</title>",
        "<title>microservices-Monitor</title>",
    )
    html = re.sub(
        r"  <!--\n    Sample layout:.*?\n  -->\s*",
        "",
        html,
        count=1,
        flags=re.DOTALL,
    )
    return html


def build_control_plane_ui_html() -> str:
    """Production UI: transform repo k8s sample when present; else bundled copy (Docker)."""
    if _K8S_SAMPLE.is_file():
        raw = _K8S_SAMPLE.read_text(encoding="utf-8")
        html = _transform_sample_to_production(raw)
    elif _BUNDLED.is_file():
        html = _BUNDLED.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(
            f"Control-plane UI not found: tried {_K8S_SAMPLE} and {_BUNDLED}"
        )
    _validate_control_plane_ui(html)
    return html


def write_bundled_static() -> Path:
    """Write transformed HTML for Docker/minikube (build context = audit-service only)."""
    if not _K8S_SAMPLE.is_file():
        raise FileNotFoundError(f"Need k8s sample to bundle: {_K8S_SAMPLE}")
    raw = _K8S_SAMPLE.read_text(encoding="utf-8")
    html = _transform_sample_to_production(raw)
    _validate_control_plane_ui(html)
    _BUNDLED.parent.mkdir(parents=True, exist_ok=True)
    _BUNDLED.write_text(html, encoding="utf-8")
    return _BUNDLED
