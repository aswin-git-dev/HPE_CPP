"""
llm_engine.py  —  OpenRouter-powered LLM engine for K8s Security Framework
============================================================================
Provider: OpenRouter (FREE — $1 credit on signup, no card needed)
  Model:  meta-llama/llama-3.3-70b-instruct
  Key:    starts with sk-or-v1-...
  Get key at: https://openrouter.ai → Keys → Create Key

Setup:
  Add to your .env file:
      OPENROUTER_API_KEY=sk-or-v1-your-key-here

  OR set environment variable (Windows):
      set OPENROUTER_API_KEY=sk-or-v1-your-key-here

LLM Functions:
  smart_forensics(question)         RAG-based natural language log investigation
  llm_summary_24h(digest)           Daily security briefing prose
  explain_alert(event)              Plain-English explanation of one alert
  rbac_explain(event, history)      RBAC privilege escalation narrative
  uba_report(user, days)            Full UBA profile + LLM risk assessment
  human_workload_alert(event)       GitOps violation explanation
  is_human_workload_modification()  Check if human is touching workload resource
  extract_query_intent(question)    Parse NL query → SQL parameters dict
  get_llm_provider_status()         Check provider configuration
"""

import os
import json
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — .env loader
# ═══════════════════════════════════════════════════════════════════════════════

def _load_env(path: str = ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ.
    Always overwrites — .env file is the source of truth.
    """
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ[key.strip()] = val.strip()  # always overwrite

_load_env()   # runs once on import


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — OpenRouter API caller
# ═══════════════════════════════════════════════════════════════════════════════

# OpenRouter models — free tier, keys never auto-revoked
# Get key at: https://openrouter.ai → Keys → Create Key (sk-or-v1-...)
_OR_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",   # primary — best quality
    "meta-llama/llama-3.1-8b-instruct",    # fallback 1
    "google/gemma-2-9b-it",                # fallback 2
]

_OR_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _call_or_model(api_key: str, model: str,
                   system: str, user_msg: str, max_tokens: int) -> str:
    """Call one OpenRouter model (OpenAI-compatible API)."""
    payload = json.dumps({
        "model":       model,
        "max_tokens":  max_tokens,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
    }).encode()

    req = urllib.request.Request(
        _OR_API_URL,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  "http://localhost:8000",
            "X-Title":       "K8s Security Framework",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())

    # Check for error in response body (OpenRouter returns 200 with error sometimes)
    if "error" in data:
        raise ValueError(f"OpenRouter error: {data['error'].get('message', data['error'])}")

    return data["choices"][0]["message"]["content"]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Main dispatcher with model-level fallback
# ═══════════════════════════════════════════════════════════════════════════════

def _call_llm(system: str, user_msg: str, max_tokens: int = 1200) -> str:
    """
    Try OpenRouter models in fallback order.
    OpenRouter key: sk-or-v1-... (never auto-revoked)
    Get free key at: https://openrouter.ai → Keys → Create Key
    """
    _load_env()  # always re-read .env
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set.\n"
            "Steps to fix:\n"
            "  1. Go to https://openrouter.ai\n"
            "  2. Sign up with Google/GitHub (free, no card needed)\n"
            "  3. Click Keys → Create Key\n"
            "  4. Add to .env:  OPENROUTER_API_KEY=sk-or-v1-...\n"
            "  5. Restart uvicorn"
        )

    errors = []

    for model in _OR_MODELS:
        try:
            result = _call_or_model(api_key, model, system, user_msg, max_tokens)
            if model != _OR_MODELS[0]:
                print(f"[llm_engine] ℹ️  Served by fallback model: {model}")
            return result

        except urllib.error.HTTPError as e:
            try:
                body_bytes = e.read()
                try:
                    body   = json.loads(body_bytes)
                    detail = (body.get("error", {}).get("message")
                              or body.get("message")
                              or body_bytes.decode("utf-8", errors="replace"))
                except Exception:
                    detail = body_bytes.decode("utf-8", errors="replace")
            except Exception:
                detail = e.reason
            msg = f"{model}: HTTP {e.code} — {detail}"
            print(f"[llm_engine] ⚠️  {msg} → trying next model")
            errors.append(msg)
            continue

        except ValueError as e:
            msg = f"{model}: {e}"
            print(f"[llm_engine] ⚠️  {msg} → trying next model")
            errors.append(msg)
            continue

        except Exception as e:
            msg = f"{model}: unexpected error — {e}"
            errors.append(msg)
            continue

    raise RuntimeError(
        "All OpenRouter models failed. Errors:\n"
        + "\n".join(f"  • {e}" for e in errors)
        + "\n\nGet a free key at https://openrouter.ai → Keys → Create Key"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Database helpers
# ═══════════════════════════════════════════════════════════════════════════════

DB_PATH = os.environ.get("FEATURE_STORE_PATH", "feature_store.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Smart Forensics (RAG pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

_FORENSICS_SYSTEM = """You are a Kubernetes security forensics analyst.
You receive a question from a security analyst and a set of raw audit log rows as JSON.
Rules:
  - Answer ONLY from the provided log data. Never invent facts.
  - Be precise: include timestamps, usernames, namespaces, methods, anomaly_scores.
  - If the answer is not in the data, say exactly: "Not found in the retrieved logs."
  - Use plain text. No markdown headers or bullet points.
  - If multiple events match, describe all of them in order of severity."""

_INTENT_SYSTEM = (
    "You extract structured query intent from a natural language security question.\n"
    "Return ONLY a JSON object with these exact keys (use null if not applicable):\n"
    "{\n"
    '  "user": "username or null",\n'
    '  "namespace": "namespace or null",\n'
    '  "object_type": "pods|secrets|configmaps|rolebindings|clusterroles|deployments|namespaces or null",\n'
    '  "method": "create|delete|get|list|update|patch|exec or null",\n'
    '  "start_iso": "ISO8601 UTC datetime or null",\n'
    '  "end_iso": "ISO8601 UTC datetime or null",\n'
    '  "is_failed": "0 or 1 or null",\n'
    '  "min_score": "0.0 to 1.0 or null",\n'
    '  "limit": "integer, default 30"\n'
    "}\n"
    "Return nothing else. No explanation. No markdown fences. Just the JSON object.\n"
    f"Today UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
)


def extract_query_intent(question: str) -> dict:
    """Parse a natural language forensic question into SQL-ready parameters."""
    raw = _call_llm(_INTENT_SYSTEM, question, max_tokens=300)
    raw = raw.strip()
    for fence in ("```json", "```"):
        raw = raw.lstrip(fence).rstrip(fence)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"[llm_engine] ⚠️  Intent parse failed. Raw: {raw[:100]}")
        return {}


def _build_forensics_sql(intent: dict) -> tuple:
    """Convert intent dict → (sql_string, params_list)."""
    clauses, params = [], []

    if intent.get("user"):
        clauses.append("user LIKE ?")
        params.append(f"%{intent['user']}%")
    if intent.get("namespace"):
        clauses.append("namespace LIKE ?")
        params.append(f"%{intent['namespace']}%")
    if intent.get("object_type"):
        clauses.append("object_type LIKE ?")
        params.append(f"%{intent['object_type']}%")
    if intent.get("method"):
        clauses.append("method = ?")
        params.append(str(intent["method"]).lower())
    if intent.get("start_iso"):
        clauses.append("ts >= ?")
        params.append(intent["start_iso"])
    if intent.get("end_iso"):
        clauses.append("ts <= ?")
        params.append(intent["end_iso"])
    if intent.get("is_failed") is not None:
        clauses.append("is_failed = ?")
        params.append(int(intent["is_failed"]))
    if intent.get("min_score") is not None:
        clauses.append("anomaly_score >= ?")
        params.append(float(intent["min_score"]))

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    limit  = int(intent.get("limit") or 30)
    sql = (
        "SELECT ts, user, source_ip, namespace, object_type, method, "
        "is_failed, is_sensitive, anomaly_score "
        f"FROM events {where} "
        "ORDER BY anomaly_score DESC, ts DESC "
        f"LIMIT {limit}"
    )
    return sql, params


def smart_forensics(question: str) -> dict:
    """
    Full RAG forensics pipeline:
      Step 1 — LLM extracts query intent (user/namespace/time/method filters)
      Step 2 — Build targeted SQL from those filters
      Step 3 — Fetch matching rows from feature_store.db
      Step 4 — LLM reads the rows and answers the question

    Example questions:
      "Who deleted the prod-db namespace and when?"
      "List all API calls by jane.smith between 2AM-4AM yesterday"
      "Which pods were exec'd into in the last 30 days?"
      "Show all failed secret reads in namespace prod"
      "Which service account listed secrets 800 times?"
    """
    intent = extract_query_intent(question)
    sql, params = _build_forensics_sql(intent)

    conn = _get_conn()
    rows = _rows_to_list(conn.execute(sql, params).fetchall())
    conn.close()

    fallback_used = False
    if not rows:
        conn = _get_conn()
        rows = _rows_to_list(conn.execute(
            "SELECT ts, user, source_ip, namespace, object_type, method, "
            "is_failed, is_sensitive, anomaly_score "
            "FROM events WHERE anomaly_score >= 0.8 "
            "ORDER BY ts DESC LIMIT 50"
        ).fetchall())
        conn.close()
        fallback_used = True

    user_msg = (
        f"Question: {question}\n\n"
        f"Retrieved log rows ({len(rows)} events):\n"
        f"{json.dumps(rows, indent=2, default=str)}\n\n"
        "Answer the analyst's question using only the rows above."
    )
    answer = _call_llm(_FORENSICS_SYSTEM, user_msg, max_tokens=800)

    return {
        "question":      question,
        "answer":        answer,
        "logs_searched": len(rows),
        "query_intent":  intent,
        "sql_used":      sql,
        "fallback_used": fallback_used,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — 24-Hour Security Digest
# ═══════════════════════════════════════════════════════════════════════════════

_DIGEST_SYSTEM = """You are a senior Kubernetes security engineer writing a daily security digest.
Write a professional briefing in plain paragraphs. No markdown headers. No bullet points.
Structure:
  Paragraph 1: Overall risk posture and key metrics.
  Paragraph 2: Most critical incident(s) — name the actor, action, resource, time, and why it matters.
  Paragraph 3: Secondary anomalies worth monitoring.
  Paragraph 4: Recommended immediate actions — specific and actionable.
Be specific: use actor names, namespaces, timestamps, and anomaly scores from the data.
Never invent data not present in the input. Maximum 5 paragraphs."""


def llm_summary_24h(digest: dict) -> str:
    """Generate a prose security digest from the pre-computed stats dict."""
    user_msg = (
        "24-hour security data for our Kubernetes cluster:\n\n"
        f"{json.dumps(digest, indent=2, default=str)}\n\n"
        "Write the security briefing now."
    )
    return _call_llm(_DIGEST_SYSTEM, user_msg, max_tokens=1200)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Single Alert Explanation
# ═══════════════════════════════════════════════════════════════════════════════

_ALERT_SYSTEM = """You are a Kubernetes security analyst explaining a single security alert
to a non-technical stakeholder. Use plain English. Write exactly 4 sentences:
  Sentence 1: What happened — name the actor, what they did, which resource, which namespace.
  Sentence 2: Why it is suspicious — compare to the baseline behavior shown in the event data.
  Sentence 3: What damage an attacker could do with this access if the action was malicious.
  Sentence 4: One concrete recommended action the team should take right now.
No jargon without explanation. No bullet points."""


def explain_alert(event: dict) -> str:
    """Plain-English explanation of why one scored event is suspicious."""
    user_msg = (
        f"Explain this security event:\n"
        f"{json.dumps(event, indent=2, default=str)}"
    )
    return _call_llm(_ALERT_SYSTEM, user_msg, max_tokens=400)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — RBAC Privilege Escalation Narrative
# ═══════════════════════════════════════════════════════════════════════════════

_RBAC_SYSTEM = """You are a Kubernetes RBAC security specialist.
Given a privilege escalation event and optionally the actor's recent RBAC history, explain:
  1. What new permissions were granted and to which identity.
  2. Why this is dangerous — what can the new role or binding actually do?
  3. Context: first such change? Outside business hours?
  4. Recommended remediation — revoke? Escalate? Open incident?
Maximum 4 sentences. Be specific about role names, namespaces, and permission verbs."""


def rbac_explain(event: dict, user_history: list = None) -> str:
    """Detailed RBAC privilege escalation narrative."""
    history_ctx = ""
    if user_history:
        recent      = user_history[-5:]
        history_ctx = (
            f"\n\nThis actor's recent RBAC history ({len(recent)} events):\n"
            f"{json.dumps(recent, indent=2, default=str)}"
        )
    user_msg = (
        f"RBAC escalation event:\n"
        f"{json.dumps(event, indent=2, default=str)}"
        f"{history_ctx}"
    )
    return _call_llm(_RBAC_SYSTEM, user_msg, max_tokens=400)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — User Behavior Analytics (UBA) Report
# ═══════════════════════════════════════════════════════════════════════════════

_UBA_SYSTEM = """You are a User Behavior Analytics (UBA) specialist for Kubernetes security.
You receive a behavioral profile for a single user or service account.
Write a risk assessment covering:
  1. Normal behavior pattern: working hours, typical actions, namespaces and resources accessed.
  2. Anomalies observed: off-hours access, request spikes, unusual resources, high failure rate.
  3. Risk category — choose exactly one: NORMAL | WATCH | HIGH-RISK
  4. Most likely explanation: insider threat, compromised credential, runaway automation, or normal.
Maximum 5 sentences. Be specific about numbers and timestamps.
Start your first line exactly like: RISK: HIGH-RISK"""


def uba_report(user: str, days: int = 30) -> dict:
    """
    Pull behavioral stats for a user and generate a full UBA profile
    with an LLM risk assessment.
    """
    conn   = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = _rows_to_list(conn.execute(
        "SELECT ts, user, source_ip, namespace, object_type, method, "
        "hour, is_failed, is_sensitive, anomaly_score "
        "FROM events WHERE user = ? AND ts >= ? ORDER BY ts ASC",
        (user, cutoff)
    ).fetchall())
    conn.close()

    if not rows:
        return {
            "user":  user,
            "error": f"No events found for '{user}' in the last {days} days.",
        }

    hours         = [r["hour"] for r in rows if r.get("hour") is not None]
    methods: dict = {}
    namespaces    = set()
    object_types  = set()
    source_ips    = set()
    failed        = sum(1 for r in rows if r.get("is_failed"))
    sensitive     = sum(1 for r in rows if r.get("is_sensitive"))
    high_scores   = [r for r in rows if (r.get("anomaly_score") or 0) > 0.8]
    medium_scores = [r for r in rows if 0.5 < (r.get("anomaly_score") or 0) <= 0.8]

    for r in rows:
        m = r.get("method", "unknown")
        methods[m] = methods.get(m, 0) + 1
        if r.get("namespace"):   namespaces.add(r["namespace"])
        if r.get("object_type"): object_types.add(r["object_type"])
        if r.get("source_ip"):   source_ips.add(r["source_ip"])

    off_hours_events = [
        r for r in rows
        if r.get("hour") is not None and (r["hour"] < 6 or r["hour"] > 20)
    ]
    hourly_counts: dict = {}
    for h in hours:
        hourly_counts[str(h)] = hourly_counts.get(str(h), 0) + 1

    profile = {
        "user":                 user,
        "analysis_period_days": days,
        "total_events":         len(rows),
        "first_seen":           rows[0]["ts"],
        "last_seen":            rows[-1]["ts"],
        "unique_namespaces":    sorted(namespaces),
        "unique_object_types":  sorted(object_types),
        "unique_source_ips":    sorted(source_ips),
        "method_distribution":  methods,
        "failed_requests":      failed,
        "failure_rate_pct":     round(failed / len(rows) * 100, 1),
        "sensitive_accesses":   sensitive,
        "sensitive_rate_pct":   round(sensitive / len(rows) * 100, 1),
        "most_active_hour":     (max(set(hours), key=hours.count) if hours else None),
        "hourly_activity":      hourly_counts,
        "off_hours_events":     len(off_hours_events),
        "off_hours_examples":   off_hours_events[:3],
        "high_risk_events":     len(high_scores),
        "medium_risk_events":   len(medium_scores),
        "top_high_risk_events": high_scores[-5:],
    }

    user_msg = (
        f"UBA profile for actor '{user}':\n"
        f"{json.dumps(profile, indent=2, default=str)}\n\n"
        "Write the risk assessment now."
    )
    profile["llm_risk_assessment"] = _call_llm(_UBA_SYSTEM, user_msg, max_tokens=500)
    return profile


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — Human Workload Modification (GitOps Violation)
# ═══════════════════════════════════════════════════════════════════════════════

_HUMAN_MOD_SYSTEM = """You are a GitOps compliance analyst for a Kubernetes platform team.
In a properly governed cluster, Deployments, ReplicaSets, StatefulSets, DaemonSets, and Pods
must ONLY be modified by CI/CD pipelines or automation (service accounts), never by human users.
Given the event where a human user modified a workload resource, explain in exactly 4 sentences:
  1. What was changed: resource type, name, namespace, and the operation.
  2. Why this violates GitOps policy and what specific risk it creates.
  3. What an attacker could do if this was a compromised human account.
  4. Immediate action: who to notify, what to audit, what to revert."""

HUMAN_WORKLOAD_RESOURCES = {
    "deployments", "replicasets", "statefulsets",
    "daemonsets", "pods", "jobs", "cronjobs",
}
_NON_HUMAN_IDENTIFIERS = {
    "serviceaccount", "system:", "bot", "ci", "pipeline",
    "argo", "flux", "jenkins", "github-actions", "automation",
}


def is_human_workload_modification(event: dict) -> bool:
    """Returns True if a human user is directly modifying a workload resource."""
    user   = str(event.get("user", "")).lower()
    obj    = str(event.get("object_type", "")).lower()
    method = str(event.get("method", "")).lower()
    is_human    = not any(ident in user for ident in _NON_HUMAN_IDENTIFIERS)
    is_workload = any(r in obj for r in HUMAN_WORKLOAD_RESOURCES)
    is_write    = method in {"create", "update", "patch", "delete"}
    return is_human and is_workload and is_write


def human_workload_alert(event: dict) -> str:
    """Generate a GitOps violation explanation."""
    return _call_llm(
        _HUMAN_MOD_SYSTEM,
        f"GitOps violation event:\n{json.dumps(event, indent=2, default=str)}",
        max_tokens=400,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — Provider status (for /health endpoint)
# ═══════════════════════════════════════════════════════════════════════════════

def get_llm_provider_status() -> dict:
    """Check LLM provider configuration. No API calls — just reads env vars."""
    _load_env()  # always re-read .env so health shows current key
    _load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    return {
        "provider":               "openrouter",
        "models":                 _OR_MODELS,
        "openrouter_configured":  bool(api_key),
        "key_prefix":             (api_key[:12] + "...") if api_key else "NOT SET",
        "llm_available":          bool(api_key),
        "get_key_at":             "https://openrouter.ai",
        "free_tier":              "$1 free credit on signup",
    }