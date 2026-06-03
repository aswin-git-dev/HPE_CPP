# Smart Security Logging Framework for Kubernetes Microservices

> **ML-powered anomaly detection for Kubernetes audit logs — learns normal behaviour, detects attacks automatically, explains them in plain English.**

---

## What This Project Does

Traditional Kubernetes security systems rely on predefined rules — if an action matches a rule, it gets flagged. This system takes a different approach: it learns what **normal behaviour** looks like from historical audit logs, then flags anything that deviates from that pattern, even if no rule was written for it.

The system:
- Collects Kubernetes audit events (via Falco/eBPF — handled by the K8s team)
- Applies two complementary ML models to score each event for anomalousness
- Stores all events in a SQLite feature store with rolling behavioral history
- Exposes a FastAPI backend with endpoints for real-time scoring, forensics, and LLM-powered explanations
- Retrains itself automatically every night so it keeps up with evolving cluster behaviour

---

## Architecture Overview

```
K8s Cluster (Falco/eBPF)
        │
        │  JSON audit events (real-time)
        ▼
┌─────────────────────────────────────┐
│         FastAPI Backend             │
│         main.py  :8000              │
│                                     │
│  POST /score         ← single event │
│  POST /score/batch   ← bulk events  │
│  GET  /summary/24h   ← digest       │
│  GET  /forensics     ← NL queries   │
│  POST /alert/explain ← LLM explain  │
│  POST /alert/rbac    ← RBAC alerts  │
│  POST /alert/gitops  ← GitOps check │
│  POST /retrain       ← trigger      │
└────────────┬────────────────────────┘
             │
    ┌────────▼────────┐
    │  scorer.py      │  ← hot-reloads models on retrain
    │                 │
    │  feature_       │  ← parse_raw_log()
    │  engineer.py    │  ← engineer_features() → 29 features
    │                 │
    │  feature_       │  ← get_user_features() rolling windows
    │  store.py       │  ← get_ip_features()
    │  (SQLite DB)    │  ← record_event() after scoring
    └────────┬────────┘
             │
    ┌────────▼────────────────────┐
    │  Isolation Forest           │  AUC-ROC: 0.9239
    │  isolation_forest_v*.pkl    │  Scores single events
    │                             │
    │  GRU Neural Network         │  AUC-ROC: 0.9529
    │  gru_v*.pkl                 │  Scores 20-event sequences
    └────────┬────────────────────┘
             │
    combined = 0.6 × IF + 0.4 × GRU
             │
    ┌────────▼────────┐
    │  LLM Engine     │  ← OpenRouter / LLaMA 3.3 70B
    │  llm_engine.py  │  ← Alert explanations
    │                 │  ← RAG forensics (NL → SQL → answer)
    │                 │  ← 24h security digest
    └─────────────────┘

    [Daily Cron at 2 AM]
    retrain.py → pulls 30d from SQLite → trains new IF →
    PSI drift check → updates latest.json → scorer hot-reloads
```

---

## Dataset

Training data (`merged_logs.xlsx`) combines three sources:

| Source | Rows | Label |
|---|---|---|
| `real_audit_800.xlsx` — real Minikube cluster logs | 800 | `real_unknown` |
| Synthetic normal events | 5,950 | `normal` |
| Synthetic attack events | 1,048 | `anomaly` |
| **Total** | **7,798** | |

Attack types in the labeled data: `secret_mass_read`, `rbac_escalation`, `pod_exec_abuse`, `cross_namespace_secret`, `new_ip_known_actor`, `human_workload_modification`, `failed_access_spike`.

---

## Feature Engineering — 29 Features

Each raw audit event is transformed into 29 numerical features:

**Categorical (hashed)** — user, source IP, namespace, object type, method, event type. Feature hashing via MD5 — never crashes on unseen values unlike LabelEncoder.

**Temporal** — hour of day, day of week, `is_off_hours` (before 6 AM or after 8 PM).

**Event flags** — `is_sensitive` (secrets/configmap/clusterrole), `is_failed`, `is_high_risk_method` (create/delete/patch/update), `sensitive_offhour` (compound signal).

**User behavioral history** (from SQLite rolling windows) — request counts in 24h/7d/30d, failure ratio, unique namespaces/resources/IPs touched, sensitive access rate, hourly baseline, `is_new_user`.

**IP behavioral history** — request count 24h, failure ratio, unique users from this IP, `is_new_ip`, 5-minute failure burst.

**RBAC flag** — `is_rbac_resource` (role/rolebinding/clusterrole/serviceaccount).

**Critical design rule:** `record_event()` is called **after** feature extraction, never before. This prevents the current event from contaminating its own historical features — no data leakage.

---

## ML Models

### Isolation Forest

- **Type:** Unsupervised — no labels needed during training
- **Training:** 6,628 events, 200 trees, `contamination=0.12`
- **AUC-ROC:** 0.9239
- **Best at:** Point anomalies — one structurally weird event
- **Detection highlights:** `failed_access_spike` 100%, `rbac_escalation` 100%, `secret_mass_read` 99%
- **How it works:** Randomly isolates data points by drawing splits. Normal events cluster together and need many splits to isolate. Anomalies stand alone and are isolated with very few splits. Score = how easy it was to isolate.

### GRU Neural Network

- **Type:** Supervised sequence model — uses `_label` column
- **Architecture:** 2-layer GRU, 64 hidden units, trained from scratch in pure NumPy (no PyTorch/TensorFlow)
- **Input:** Last 20 events per user as a sequence (shape: 20 × 29)
- **Training:** 5,598 sequences, 30 epochs, Adam optimiser, 197 seconds
- **AUC-ROC:** 0.9529
- **Best at:** Sequence anomalies — attack patterns that unfold over multiple events
- **Detection highlights:** `pod_exec_abuse` 97%, `rbac_escalation` 95%
- **How it works:** Processes each event in order, carrying a hidden state forward. The update gate controls what to remember; the reset gate controls what to forget. After 20 events, the final hidden state encodes the full behavioural story of the user.

### Combined Score

```
combined = 0.6 × if_score + 0.4 × gru_score
```

GRU only activates after 20 events per user accumulate in the per-user buffer. Before that, the system runs in IF-only mode.

| | Recall |
|---|---|
| IF alone | 31.6% |
| GRU alone | 62.6% |
| Combined | 65.2% |

52 attacks caught by GRU that IF missed + 4 caught by IF that GRU missed = the two models are genuinely complementary.

**Risk levels:** score > 0.8 → HIGH, score > 0.5 → MEDIUM, else LOW.

---

## FastAPI Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/score` | Score a single event. Returns anomaly_score, risk_level, reason, all 29 features. |
| POST | `/score/batch` | Score up to 1000 events in chronological order. No leakage. |
| GET | `/summary/24h` | Security digest: event counts, top anomalies, UBA flags, LLM narrative. |
| GET | `/forensics?q=` | Natural language log query → SQL → LLM answer from retrieved logs (RAG). |
| POST | `/alert/explain` | Plain-English explanation of a suspicious event for SOC analysts. |
| POST | `/alert/rbac` | RBAC privilege escalation narrative (cluster-admin grants, binding creation). |
| POST | `/alert/gitops` | Detects humans modifying workload resources — should be CI/CD only. |
| GET | `/logs` | Recent events with optional `risk_level` filter. |
| POST | `/logs/{id}/label` | Analyst marks event as confirmed anomaly (1) or false positive (0). |
| POST | `/retrain` | Trigger IF retraining in background. `?force=true` skips validation. |
| POST | `/retrain/gru` | Trigger GRU retraining. |

---

## LLM Intelligence Layer

Provider: **OpenRouter (LLaMA 3.3 70B)** — API key loaded from `.env`, never hardcoded.

**Alert Explanation (`/alert/explain`):** Scores the event, sends all 29 features + risk reason to the LLM, receives a paragraph explaining why it's suspicious, what the risk is, and what action to take — written for a SOC analyst, not a data scientist.

**RAG Forensics (`/forensics?q=`):** A natural language question like *"Who deleted clusterrolebinding in kube-system?"* is parsed by the LLM to extract intent (user, namespace, method, time range, min_score), a targeted SQL query is built and run against the SQLite feature store, and the retrieved rows are passed back to the LLM to answer from the actual data. The LLM never guesses — it only answers from retrieved evidence.

**24h Security Digest (`/summary/24h`):** Aggregates 2,000 recent events → computes high/medium/low counts → identifies UBA flags (users with both off-hours and high-risk events) → LLM generates an executive-level risk briefing.

---

## Retraining Pipeline & Cron

### Why Retraining Matters

The model was trained on April–May 2026 data. Over time, normal cluster behaviour changes — new users, new services, new access patterns. Without retraining, the model starts flagging normal new behaviour as anomalies.

### Cron Setup (Daily at 2 AM)

```bash
0 2 * * * /usr/bin/python3 /path/to/retrain.py >> /var/log/retrain.log 2>&1
```

### What Happens Each Night

1. Pull last 30 days of events from `feature_store.db`
2. Skip if fewer than 200 events (not enough data to retrain meaningfully)
3. Split: last 2 days = validation, 28 days before = training
4. Train a new Isolation Forest
5. Compare new vs old model using **PSI (Population Stability Index)**
   - PSI < 0.1 → no change, safe to replace
   - PSI 0.1–0.2 → some drift, replace with warning
   - PSI > 0.2 → significant drift, flag for investigation
6. Safety check: if new model flags 3× more events than old → abort (something is wrong with the training data)
7. If OK → write new `.pkl` + update `latest.json`
8. `scorer.py` detects the changed `latest.json` on the next request and **hot-reloads** the new model without any server restart

### Hot Reload

```python
# In scorer.py — checked on every score() call
current_mtime = os.path.getmtime("models/latest.json")
if current_mtime != _last_loaded_mtime:
    _model = load_model_from_latest_json()
    _last_loaded_mtime = current_mtime
```

Zero downtime. The running server switches to the new model in milliseconds.

---

## Model Performance Summary

| Metric | Isolation Forest | GRU |
|---|---|---|
| AUC-ROC | 0.9239 | 0.9529 |
| Best threshold | 0.4 | 0.3 |
| F1 at best threshold | 0.641 | 0.735 |
| Training time | ~30s | ~197s |

**Why not LogBERT or SecBERT?** LogBERT is trained on HDFS/BGL logs — wrong format entirely. SecBERT is trained on CVE text — wrong domain. Without fine-tuning, estimated AUC ~0.65–0.75. Both require GPU + hours of fine-tuning and have 110M+ parameters vs our GRU's ~50K parameters.

**Why GRU not LSTM?** GRU achieves the same or better AUC with 33% fewer parameters and faster training (~197s vs ~280s). GRU strictly dominates LSTM for this use case.

---

## Setup & Usage

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Initial training (run once)

```bash
# Deletes any existing feature_store.db, trains from scratch
del feature_store.db   # Windows
# rm feature_store.db  # Linux/Mac

python train.py --data merged_logs.xlsx --out models/ --contamination 0.12
python train_gru.py --data merged_logs.xlsx --out models/
```

### 3. Start the API server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Score a single event

```bash
curl -X POST http://localhost:8000/score \
  -H "Content-Type: application/json" \
  -d '{
    "user_subject": "john.doe",
    "method": "list",
    "namespace": "prod",
    "object_type": "secrets",
    "source_ip": "unknown",
    "result": "Success",
    "timestamp_utc": "2026-05-29T02:14:00Z"
  }'
```

### 5. Forensic query (requires LLM key)

```bash
export OPENROUTER_API_KEY=sk-or-...
curl "http://localhost:8000/forensics?q=Who+deleted+clusterrolebinding+in+kube-system"
```

### 6. Retrain manually

```bash
python retrain.py
python retrain.py --force   # override validation checks
# or via API:
curl -X POST http://localhost:8000/retrain
```

### 7. Validate model performance

```bash
python validate.py --data merged_logs.xlsx --models models/
python validate_gru.py --data merged_logs.xlsx --models models/
```

---

## Key Design Decisions

**Why SQLite instead of Redis?** SQLite is sufficient for a single-node prototype. The `get_user_features` / `get_ip_features` / `record_event` interface is identical — swap `_get_conn()` for a Redis client when scaling to multi-node.

**Why feature hashing instead of LabelEncoder?** `LabelEncoder` crashes with `ValueError: y contains previously unseen labels` when a new user or IP appears. Feature hashing maps any string to an integer via MD5 — deterministic, never crashes, handles new actors at inference time.

**Why record_event() after scoring?** If we recorded first, the user's own current request would appear in their 24-hour history when we query it. The score would be inflated by data the model shouldn't have known at the time.

**Why save score_stats with the model?** Normalization must be anchored to the training distribution. If we re-computed stats from the current batch, scores would shift across batches and thresholds would become meaningless.

**Why chronological train/val split?** Random splits allow future events to appear in training data. K8s audit logs are time-series. Always validate on data that chronologically follows the training window.

---

## File Reference

| File | Purpose |
|---|---|
| `feature_store.py` | SQLite database — stores all events, provides rolling-window behavioral queries |
| `feature_engineer.py` | Converts raw log dicts into 29-feature vectors |
| `train.py` | One-time Isolation Forest training — processes rows chronologically, no leakage |
| `train_gru.py` | GRU training — builds per-user sequences, trains pure-NumPy 2-layer GRU |
| `scorer.py` | Live scoring — IF + GRU combined, per-user sequence buffer, hot-reload |
| `retrain.py` | Nightly retraining — PSI drift detection, safety guards, atomic model swap |
| `main.py` | FastAPI app — all HTTP endpoints |
| `llm_engine.py` | LLM integration — RAG forensics, alert explanations, 24h digest |
| `explain_rag.py` | RAG query engine — NL → intent extraction → SQL → LLM answer |
| `validate.py` | Offline IF evaluation — AUC-ROC, threshold analysis, per-attack-type detection rates |
| `validate_gru.py` | Offline GRU evaluation — confusion matrix, threshold analysis, IF vs GRU comparison |
| `generate_synthetic.py` | Generates labeled synthetic attack and normal events for training |
| `show_model_results.py` | Prints a formatted model performance summary to the console |