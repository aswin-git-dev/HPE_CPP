"""
main.py  —  FastAPI service for K8s Security Anomaly Detection
--------------------------------------------------------------
Endpoints:
  POST /score              — score a single event (IF + GRU)
  POST /score/batch        — score up to 1000 events
  GET  /logs               — recent scored logs
  POST /logs/{id}/label    — analyst labels an event
  POST /retrain            — trigger IF retraining
  POST /retrain/gru        — trigger GRU retraining
  GET  /model              — current model info (IF + GRU)
  GET  /health             — liveness check
  GET  /summary/24h        — security digest (+ LLM if API key set)
  GET  /forensics?q=       — natural language query (needs API key)

Start:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import os, json
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import feature_store as fs
from scorer import score_event, score_batch, get_model_info
from retrain import retrain
import llm_engine as llm

app = FastAPI(
    title="K8s Security Anomaly Detection",
    description="Isolation Forest + GRU sequential anomaly detection for K8s audit logs",
    version="2.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    fs.init_db()
    try:
        from scorer import _if_reg, _gru_reg
        _if_reg.load()
        _gru_reg.load()   # silent no-op if GRU not trained yet
    except FileNotFoundError:
        print("[startup] ⚠️  No IF model found. Run train.py first.")


# ── Request / Response models ─────────────────────────────────────────────────

class LogEvent(BaseModel):
    timestamp_utc:      Optional[str]  = None
    event_type:         Optional[str]  = None
    classification:     Optional[str]  = None
    result:             Optional[str]  = "Success"
    user_subject:       Optional[str]  = "unknown"
    method:             Optional[str]  = "unknown"
    source_ip:          Optional[str]  = "unknown"
    namespace:          Optional[str]  = "unknown"
    object_type:        Optional[str]  = "unknown"
    object_name:        Optional[str]  = None
    requesting_service: Optional[str]  = None
    raw:                Optional[dict] = None

    def to_raw_dict(self) -> dict:
        if self.raw:
            return self.raw
        return {
            "Timestamp (UTC)": self.timestamp_utc or datetime.now(timezone.utc).isoformat(),
            "Event Type":      self.event_type    or "unknown",
            "Classification":  self.classification or "unknown",
            "Result":          self.result         or "Success",
            "User / Subject":  self.user_subject   or "unknown",
            "Method":          self.method         or "unknown",
            "Source IP":       self.source_ip      or "unknown",
            "Namespace":       self.namespace      or "unknown",
            "Object Type":     self.object_type    or "unknown",
            "Object Name":     self.object_name    or "unknown",
        }


class ScoreResponse(BaseModel):
    ts:            str
    user:          str
    source_ip:     str
    namespace:     str
    object_type:   str
    method:        str
    anomaly_score: float
    if_score:      float
    gru_score:     Optional[float]
    gru_active:    bool
    risk_level:    str
    reason:        str
    model_version: str
    features:      dict


class LabelRequest(BaseModel):
    label: int   # 0=normal, 1=anomaly


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":    "ok",
        "model":     get_model_info(),
        "llm":       llm.get_llm_provider_status(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/model")
def model_info():
    info = get_model_info()
    if "status" in info and info["status"] == "no model loaded":
        raise HTTPException(503, "No model loaded. Run train.py first.")
    return info


@app.post("/score", response_model=ScoreResponse)
def score_single(event: LogEvent):
    try:
        return score_event(event.to_raw_dict())
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"Scoring error: {e}")


@app.post("/score/batch")
def score_batch_endpoint(events: List[LogEvent]):
    if len(events) > 1000:
        raise HTTPException(400, "Max 1000 events per call.")
    try:
        results = score_batch([e.to_raw_dict() for e in events])
        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(500, f"Batch error: {e}")


@app.get("/logs")
def get_logs(
    limit: int = Query(50, ge=1, le=500),
    risk_level: Optional[str] = Query(None, description="HIGH / MEDIUM / LOW"),
):
    logs = fs.get_recent_logs(limit=limit, risk_level=risk_level)
    return {"count": len(logs), "logs": logs}


@app.post("/logs/{event_id}/label")
def label_event(event_id: int, req: LabelRequest):
    if req.label not in (0, 1):
        raise HTTPException(400, "label must be 0 or 1")
    fs.update_analyst_label(event_id, req.label)
    return {"event_id": event_id, "label": req.label,
            "label_counts": fs.get_label_counts()}


@app.post("/retrain")
def trigger_retrain(background_tasks: BackgroundTasks, force: bool = False):
    """Retrain the Isolation Forest model."""
    background_tasks.add_task(_run_retrain, force)
    return {"status": "IF retraining started", "force": force,
            "message": "Check /model in ~30s."}


@app.post("/retrain/gru")
def trigger_gru_retrain(background_tasks: BackgroundTasks,
                         data: str = Query("merged_logs.xlsx")):
    """Retrain the GRU model."""
    background_tasks.add_task(_run_gru_retrain, data)
    return {"status": "GRU retraining started",
            "message": "Check /model in ~2min."}


def _run_retrain(force: bool):
    try:
        result = retrain(force=force)
        print(f"[retrain bg] IF done: {result['status']}")
    except Exception as e:
        print(f"[retrain bg] IF error: {e}")


def _run_gru_retrain(data_path: str):
    try:
        from train_gru import train_gru
        version = train_gru(data_path=data_path)
        # Hot-reload GRU
        from scorer import _gru_reg
        _gru_reg.load()
        print(f"[retrain bg] GRU done: {version}")
    except Exception as e:
        print(f"[retrain bg] GRU error: {e}")


@app.get("/summary/24h")
def summary_24h():
    logs  = fs.get_recent_logs(limit=2000)
    total = len(logs)
    high  = sum(1 for l in logs if (l.get("anomaly_score") or 0) > 0.9)
    med   = sum(1 for l in logs if 0.6 < (l.get("anomaly_score") or 0) <= 0.9)
    low   = total - high - med
    users = {l["user"] for l in logs if l.get("user")}
    top_anomalies = sorted(
        [l for l in logs if (l.get("anomaly_score") or 0) > 0.5],
        key=lambda x: x.get("anomaly_score", 0), reverse=True
    )[:10]

    digest = {
        "period": "last 24 hours", "total_events": total,
        "unique_actors": len(users), "high_risk": high,
        "medium_risk": med, "low_risk": low,
        "top_anomalies": top_anomalies,
        "model_info": get_model_info(),
    }

    # Add UBA flags (users with off-hours + high risk events)
    uba_flags = []
    user_events = {}
    for l in logs:
        u = l.get("user", "unknown")
        user_events.setdefault(u, []).append(l)
    for u, evs in user_events.items():
        off_h = sum(1 for e in evs if e.get("hour", 12) < 6 or e.get("hour", 12) > 20)
        high_r = sum(1 for e in evs if (e.get("anomaly_score") or 0) > 0.8)
        if off_h > 0 and high_r > 0:
            uba_flags.append({"user": u, "off_hours_events": off_h, "high_risk_events": high_r})
    digest["uba_flags"] = sorted(uba_flags, key=lambda x: x["high_risk_events"], reverse=True)[:5]

    # LLM digest via Gemini
    if top_anomalies:
        try:
            digest["llm_digest"] = llm.llm_summary_24h(digest)
        except Exception as e:
            digest["llm_digest_error"] = str(e)

    return digest


@app.get("/forensics")
def forensics(q: str = Query(..., description="Natural language security question")):
    """
    RAG-powered forensic investigation using Gemini.
    Extracts query intent, builds targeted SQL, fetches matching rows,
    then asks Gemini to answer from that specific data.
    Examples:
      ?q=Who listed secrets after midnight
      ?q=Show all pod exec calls in namespace prod
      ?q=Which user created clusterrolebindings in the last 7 days
    """
    try:
        return llm.smart_forensics(q)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"Forensics error: {e}")


@app.post("/alert/explain")
def alert_explain(event: LogEvent):
    """Plain-English explanation of why an event is suspicious."""
    try:
        scored = score_event(event.to_raw_dict())
        explanation = llm.explain_alert(scored)
        return {"event": scored, "explanation": explanation}
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/alert/rbac")
def rbac_alert(event: LogEvent):
    """RBAC privilege escalation narrative."""
    try:
        scored = score_event(event.to_raw_dict())
        explanation = llm.rbac_explain(scored)
        return {"event": scored, "rbac_explanation": explanation}
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/alert/gitops")
def gitops_check(event: LogEvent):
    """Detect and explain GitOps violations (human modifying workload resources)."""
    scored = event.to_raw_dict()
    try:
        scored = score_event(scored)
    except Exception:
        pass

    if not llm.is_human_workload_modification(scored):
        return {"violation": False, "event": scored,
                "message": "No GitOps violation detected."}
    try:
        explanation = llm.human_workload_alert(scored)
        return {"violation": True, "event": scored, "explanation": explanation}
    except RuntimeError as e:
        return {"violation": True, "event": scored,
                "message": f"GitOps violation detected. LLM error: {e}"}


@app.get("/uba/{user}")
def uba_report(user: str, days: int = Query(30, ge=1, le=90)):
    """
    Full User Behavior Analytics report for one actor.
    Pulls 30-day behavioral stats + Gemini risk assessment.
    """
    try:
        return llm.uba_report(user, days=days)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))