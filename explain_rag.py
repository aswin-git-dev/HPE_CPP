"""
explain_rag.py
--------------
Shows exactly what is stored in the DB and what gets sent to the LLM.
Run: python explain_rag.py

This is for understanding/demo purposes — prints the full pipeline.
"""

import sqlite3, json, os, sys
from datetime import datetime, timezone, timedelta

DB_PATH = "feature_store.db"

def print_header(title):
    print(f"\n{'═'*70}")
    print(f"  {title}")
    print(f"{'═'*70}")

def print_section(title):
    print(f"\n{'─'*70}")
    print(f"  {title}")
    print(f"{'─'*70}")


def show_database_contents():
    print_header("STEP 1 — WHAT IS STORED IN feature_store.db")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Show table schema
    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
    ).fetchone()
    print(f"\n  Table: events")
    print(f"  Schema:")
    if schema:
        for line in schema[0].split('\n'):
            print(f"    {line}")
    
    # Show total count
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    high  = conn.execute("SELECT COUNT(*) FROM events WHERE anomaly_score > 0.8").fetchone()[0]
    med   = conn.execute("SELECT COUNT(*) FROM events WHERE anomaly_score BETWEEN 0.5 AND 0.8").fetchone()[0]
    low   = total - high - med
    
    print(f"\n  Total events stored : {total}")
    print(f"  HIGH risk (>0.8)    : {high}")
    print(f"  MEDIUM risk (0.5-0.8): {med}")
    print(f"  LOW risk (<0.5)     : {low}")
    
    # Show sample rows
    rows = conn.execute(
        "SELECT id, ts, user, namespace, object_type, method, "
        "anomaly_score, risk_level FROM events "
        "ORDER BY anomaly_score DESC LIMIT 5"
    ).fetchall()
    
    print(f"\n  Top 5 rows by anomaly score:")
    print(f"  {'ID':<5} {'Timestamp':<25} {'User':<25} {'Object':<20} {'Method':<8} {'Score':<8} {'Risk'}")
    print(f"  {'-'*105}")
    for r in rows:
        ts = str(r['ts'])[:19]
        user = str(r['user'])[:24]
        obj  = str(r['object_type'])[:19]
        print(f"  {r['id']:<5} {ts:<25} {user:<25} {obj:<20} {r['method']:<8} {r['anomaly_score']:.4f}   {r['risk_level']}")
    
    conn.close()


def show_rag_pipeline(question: str = "Who listed secrets after midnight"):
    print_header("STEP 2 — RAG PIPELINE WALKTHROUGH")
    print(f"\n  User question: \"{question}\"")
    
    print_section("STEP 2a — LLM extracts query intent")
    print(f"""
  Input to LLM (intent extractor):
  ┌─────────────────────────────────────────────────────────────────┐
  │ System: You extract structured query intent from a NL security  │
  │ question. Return ONLY a JSON object with these keys:            │
  │ user, namespace, object_type, method, start_iso, end_iso,      │
  │ is_failed, min_score, limit                                     │
  │                                                                 │
  │ User: "{question}"              │
  └─────────────────────────────────────────────────────────────────┘

  LLM output (intent JSON):
  {{
    "user": null,
    "namespace": null,
    "object_type": "secrets",
    "method": "list",
    "start_iso": "2026-05-31T00:00:00Z",
    "end_iso": null,
    "is_failed": null,
    "min_score": null,
    "limit": 30
  }}
""")

    print_section("STEP 2b — Intent converted to SQL query")
    print(f"""
  SQL built from intent:
  ┌─────────────────────────────────────────────────────────────────┐
  │ SELECT ts, user, source_ip, namespace, object_type, method,    │
  │        is_failed, is_sensitive, anomaly_score                  │
  │ FROM events                                                     │
  │ WHERE object_type LIKE '%secrets%'                             │
  │   AND method = 'list'                                          │
  │   AND ts >= '2026-05-31T00:00:00Z'                            │
  │ ORDER BY anomaly_score DESC, ts DESC                           │
  │ LIMIT 30                                                        │
  └─────────────────────────────────────────────────────────────────┘
""")

    print_section("STEP 2c — Database returns matching rows")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT ts, user, source_ip, namespace, object_type, method, "
        "is_failed, is_sensitive, anomaly_score "
        "FROM events WHERE object_type LIKE '%secret%' AND method = 'list' "
        "ORDER BY anomaly_score DESC LIMIT 5"
    ).fetchall()]
    conn.close()
    
    print(f"\n  Rows returned from DB ({len(rows)} rows):")
    print(f"  {json.dumps(rows, indent=4, default=str)}")

    print_section("STEP 2d — Full prompt sent to LLM (Llama 3.3 70B via OpenRouter)")
    
    prompt = f"""System: You are a Kubernetes security forensics analyst.
Answer ONLY from the provided log data. Never invent facts.
Be precise: include timestamps, usernames, namespaces, anomaly_scores.
If the answer is not in the data, say exactly: "Not found in the retrieved logs."
Use plain text. No markdown headers or bullet points.

User: Question: {question}

Retrieved log rows ({len(rows)} events):
{json.dumps(rows, indent=2, default=str)}

Answer the analyst's question using only the rows above."""

    print(f"\n  Full prompt sent to LLM:")
    print(f"  ┌{'─'*65}┐")
    for line in prompt.split('\n'):
        print(f"  │ {line[:63]:<63} │")
    print(f"  └{'─'*65}┘")

    print_section("STEP 2e — LLM Response (actual answer)")
    print(f"""
  LLM reads the rows and answers in plain English:

  "No user listed secrets after midnight in the provided logs.
   The only event related to listing secrets occurred before midnight
   on May 29, specifically at 02:14:00, performed by user john.doe
   in the prod namespace with an anomaly score of 0.8446."

  Key point: The LLM does NOT use its training data to answer.
  It ONLY reads the database rows you passed to it.
  This is called RAG — Retrieval Augmented Generation.
""")


def show_scoring_pipeline():
    print_header("STEP 3 — HOW A SCORE EVENT IS STORED")
    print(f"""
  When you call POST /score with this event:
  {{
    "user_subject": "attacker",
    "method": "delete", 
    "object_type": "clusterrolebinding",
    "namespace": "kube-system"
  }}

  Pipeline:
  1. parse_raw_log()     → extracts user, IP, namespace, object, method, timestamp
       ↓
  2. get_user_features() → SQL query: "What did this user do BEFORE now?"
     Returns: hist_req_24h=0, hist_req_30d=0, is_new_user=1, ...
       ↓
  3. engineer_features() → builds 29-number vector:
     [3304, 2106, 1195, 886, 8, 106, 2, 5, 1, 1, 0, 1, 1,
      0, 0, 0, 0.0, 0, 0, 0, 0.0, 0, 1, 0, 0.0, 0, 1, 0, 1]
       ↓
  4. IF model scores it  → raw score → normalized → 0.9534
       ↓
  5. risk_level = HIGH (>0.8)
  reason = "sensitive resource outside business hours; new user; new IP"
       ↓
  6. record_event()      → INSERT INTO events (ts, user, ..., anomaly_score=0.9534)
       ↓
  7. Return JSON to caller

  The row is now in the DB and available for:
    - /forensics queries
    - /summary/24h digest  
    - /uba/{user} behavioral analysis
    - Future GRU sequence scoring
""")


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run uvicorn first and score some events.")
        sys.exit(1)
    
    show_database_contents()
    show_rag_pipeline()
    show_scoring_pipeline()
    
    print(f"\n{'═'*70}")
    print(f"  SUMMARY")
    print(f"{'═'*70}")
    print(f"""
  DB stores    : every scored event (user, time, action, score, risk)
  LLM receives : the question + the relevant DB rows as JSON
  LLM outputs  : plain English answer based ONLY on those rows
  
  The LLM has no memory between calls.
  The database IS the memory.
  The LLM is just the intelligent reader.
""")
