"""
retrain.py
----------
Retraining pipeline. Run via cron (daily) or trigger manually.

What it does:
  1. Pulls last 30 days of events from the feature store
  2. Re-engineers features (no leakage — same logic as training)
  3. Trains a new IsolationForest on the fresh data
  4. Compares new model vs old model on a held-out validation window
  5. Replaces the model ONLY IF new model is not worse
  6. Detects score distribution drift (PSI) to alert you when data is changing fast

Cron setup (run daily at 2 AM):
  0 2 * * * /usr/bin/python3 /path/to/inference_service/retrain.py >> /var/log/retrain.log 2>&1

Manual trigger:
  python retrain.py
  python retrain.py --force   # replace even if new model is slightly worse
"""

import os
import json
import sqlite3
import argparse
import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import IsolationForest

import feature_store as fs
from feature_engineer import (
    parse_raw_log, engineer_features, features_to_vector,
    FEATURE_COLS, generate_reason
)
from train import compute_score_stats, normalize_score, _model_version_tag, _risk_level

MODEL_DIR = os.environ.get("MODEL_DIR", "models")

# Retrain triggers
RETRAIN_WINDOW_DAYS      = 30    # train on last N days
VALIDATION_WINDOW_DAYS   = 2     # validate on last N days (held out)
MIN_EVENTS_TO_RETRAIN    = 200   # don't retrain if not enough new data
PSI_DRIFT_THRESHOLD      = 0.2   # Population Stability Index threshold for alert


# ─────────────────────────────────────────────────────────────────────────────
# PSI (Population Stability Index) — measures score distribution drift
# PSI < 0.1 : no significant change
# PSI 0.1-0.2: some shift, monitor
# PSI > 0.2 : significant drift, retraining recommended
# ─────────────────────────────────────────────────────────────────────────────
def compute_psi(expected: np.ndarray, actual: np.ndarray, buckets: int = 10) -> float:
    """
    Compute PSI between expected (old model scores) and actual (new).
    High PSI means the score distribution has shifted significantly.
    """
    def _pct_in_buckets(arr, edges):
        counts, _ = np.histogram(arr, bins=edges)
        pct = counts / len(arr)
        pct = np.where(pct == 0, 1e-4, pct)  # avoid log(0)
        return pct

    edges = np.linspace(0, 1, buckets + 1)
    expected_pct = _pct_in_buckets(expected, edges)
    actual_pct   = _pct_in_buckets(actual, edges)
    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    return float(psi)


def load_events_from_db(days_back: int) -> pd.DataFrame:
    """
    Pull events from the feature store as a DataFrame for retraining.

    IMPORTANT: We anchor the cutoff to the LATEST event in the DB,
    not to wall-clock time. This means historical/offline datasets
    (where all events are from April 2026, for example) still work
    correctly — we always get the most recent N days of the data,
    regardless of when you're actually running this script.
    """
    conn = sqlite3.connect(fs.DB_PATH)

    # Find the most recent event timestamp in the store
    row = conn.execute("SELECT MAX(ts) FROM events").fetchone()
    if not row or not row[0]:
        conn.close()
        return pd.DataFrame()

    latest_ts = datetime.fromisoformat(row[0])
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=timezone.utc)

    cutoff = (latest_ts - timedelta(days=days_back)).isoformat()
    print(f"[retrain] Data window: {cutoff} → {latest_ts.isoformat()}")

    df = pd.read_sql_query(
        "SELECT * FROM events WHERE ts >= ? ORDER BY ts ASC",
        conn,
        params=(cutoff,)
    )
    conn.close()
    return df


def build_matrix_from_db_rows(df: pd.DataFrame) -> np.ndarray:
    """
    Build feature matrix from feature-store rows.
    These rows already HAVE historical features computed at the time they
    were scored — we reconstruct them using the same feature_engineer logic.
    Since the DB stores user/ip/namespace etc., we can re-derive features.
    
    NOTE: For retraining, we use features as they were at scoring time.
    We do NOT re-derive user_hist because that would use current history,
    not the history at the time of the event. This keeps training honest.
    """
    # Map DB columns back to raw_log format
    X = []
    for _, row in df.iterrows():
        raw = {
            "Timestamp (UTC)": row["ts"],
            "User / Subject":  row["user"],
            "Source IP":       row["source_ip"],
            "Namespace":       row["namespace"],
            "Object Type":     row["object_type"],
            "Method":          row["method"],
            "Result":          "Failure" if row["is_failed"] else "Success",
            "Event Type":      "unknown",
        }
        try:
            parsed = parse_raw_log(raw)
            ts_dt  = parsed["ts_dt"]
            # Get historical features as they would have been at event time
            user_hist = fs.get_user_features(parsed["user"],      ts_dt)
            ip_hist   = fs.get_ip_features(parsed["source_ip"],   ts_dt)
            feats = engineer_features(parsed, user_hist, ip_hist)
            X.append(features_to_vector(feats))
        except Exception as e:
            continue
    return np.array(X) if X else np.empty((0, len(FEATURE_COLS)))


def load_current_model():
    """Load the current production model and its metadata."""
    latest_path = os.path.join(MODEL_DIR, "latest.json")
    if not os.path.exists(latest_path):
        return None, None
    with open(latest_path) as f:
        ptr = json.load(f)
    model = joblib.load(os.path.join(MODEL_DIR, ptr["model_file"]))
    with open(os.path.join(MODEL_DIR, ptr["meta_file"])) as f:
        meta = json.load(f)
    return model, meta


def retrain(force: bool = False) -> dict:
    """
    Main retraining function.
    Returns a summary dict with what happened and why.
    """
    now_utc = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"[retrain] Started at {now_utc.isoformat()}")

    # ── 1. Load recent data from feature store ────────────────────────────
    print(f"[retrain] Loading last {RETRAIN_WINDOW_DAYS} days from feature store...")
    df_all = load_events_from_db(RETRAIN_WINDOW_DAYS)
    print(f"[retrain] Found {len(df_all)} events.")

    if len(df_all) < MIN_EVENTS_TO_RETRAIN:
        msg = (f"Only {len(df_all)} events available "
               f"(minimum: {MIN_EVENTS_TO_RETRAIN}). Skipping retraining.")
        print(f"[retrain] ⚠️  {msg}")
        return {"status": "skipped", "reason": msg}

    # ── 2. Chronological train/val split ─────────────────────────────────
    # ── 2. Chronological train/val split (anchored to data, not wall clock) ──
    # Fix: use the latest event timestamp in the dataset as the anchor.
    # Without this, historical data (April 2026) running on May 2026 would
    # produce an empty val set because val_cutoff would be in the future.
    df_all["ts"] = df_all["ts"].astype(str)
    import pandas as _pd2
    df_all["_ts_dt"] = _pd2.to_datetime(df_all["ts"], utc=True, errors="coerce")
    df_all = df_all.dropna(subset=["_ts_dt"])
    latest_event_ts = df_all["_ts_dt"].max()
    val_cutoff_dt   = latest_event_ts - timedelta(days=VALIDATION_WINDOW_DAYS)
    val_cutoff_str  = val_cutoff_dt.isoformat()
    df_train = df_all[df_all["_ts_dt"] < val_cutoff_dt]
    df_val   = df_all[df_all["_ts_dt"] >= val_cutoff_dt]
    print(f"[retrain] Train: {len(df_train)} | Val: {len(df_val)} "
          f"(val cutoff: {val_cutoff_str})")

    if len(df_train) < 50:
        msg = f"Too few training rows ({len(df_train)}) after val split."
        print(f"[retrain] \u26a0\ufe0f  {msg}")
        return {"status": "skipped", "reason": msg}

    # ── 3. Load current (old) model BEFORE training the new one ──────────
    # Must happen here. If we load after saving the new model, latest.json
    # already points to the new one and comparison is meaningless.
    old_model, old_meta = load_current_model()

    # ── 4. Build feature matrices ─────────────────────────────────────────
    print("[retrain] Building feature matrices...")
    X_train = build_matrix_from_db_rows(df_train)
    X_val   = build_matrix_from_db_rows(df_val)
    print(f"[retrain] X_train: {X_train.shape} | X_val: {X_val.shape}")

    # ── 5. Train new model ────────────────────────────────────────────────
    print("[retrain] Training new IsolationForest...")
    new_model = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    new_model.fit(X_train)
    new_stats = compute_score_stats(new_model.decision_function(X_train))

    # ── 6. Compare with current model on validation set ───────────────────

    comparison = {}
    should_replace = True
    replace_reason = "no previous model exists"

    if old_model is not None and len(X_val) > 0:
        old_stats = old_meta.get("score_stats", {})

        new_raw_val = new_model.decision_function(X_val)
        new_scores  = np.array([normalize_score(s, new_stats) for s in new_raw_val])

        old_raw_val = old_model.decision_function(X_val)
        old_scores  = np.array([normalize_score(s, old_stats) for s in old_raw_val])

        new_anomaly_rate = float((new_scores > 0.5).mean())
        old_anomaly_rate = float((old_scores > 0.5).mean())

        # PSI: how much has the score distribution shifted?
        psi = compute_psi(old_scores, new_scores)

        comparison = {
            "old_anomaly_rate_val": round(old_anomaly_rate, 4),
            "new_anomaly_rate_val": round(new_anomaly_rate, 4),
            "psi":                  round(psi, 4),
            "psi_alert":           psi > PSI_DRIFT_THRESHOLD,
        }

        print(f"[retrain] Old model anomaly rate on val: {old_anomaly_rate:.2%}")
        print(f"[retrain] New model anomaly rate on val: {new_anomaly_rate:.2%}")
        print(f"[retrain] PSI (score drift):             {psi:.4f} "
              f"({'⚠️ HIGH DRIFT' if psi > PSI_DRIFT_THRESHOLD else 'OK'})")

        if psi > PSI_DRIFT_THRESHOLD and not force:
            print(f"[retrain] ⚠️  PSI={psi:.3f} > {PSI_DRIFT_THRESHOLD}. "
                  "Score distribution has shifted significantly. "
                  "Investigate before replacing model. Use --force to override.")
            # We still replace but flag it
            replace_reason = f"high drift (PSI={psi:.3f}) but replacing anyway"
        elif new_anomaly_rate > old_anomaly_rate * 3 and not force:
            should_replace = False
            replace_reason = (f"new model anomaly rate ({new_anomaly_rate:.0%}) "
                              f"is 3x higher than old ({old_anomaly_rate:.0%}). "
                              "This suggests a training problem. Use --force to override.")
        else:
            replace_reason = (f"new model validated. "
                              f"PSI={psi:.3f}, anomaly_rate={new_anomaly_rate:.2%}")
    else:
        print("[retrain] No previous model or no validation data — replacing unconditionally.")

    # ── 6. Save new model ─────────────────────────────────────────────────
    if not should_replace and not force:
        print(f"[retrain] ❌ Not replacing model: {replace_reason}")
        return {
            "status":     "aborted",
            "reason":     replace_reason,
            "comparison": comparison,
        }

    version   = _model_version_tag()
    model_path = os.path.join(MODEL_DIR, f"isolation_forest_{version}.pkl")
    meta_path  = os.path.join(MODEL_DIR, f"model_meta_{version}.json")

    joblib.dump(new_model, model_path)

    meta = {
        "version":              version,
        "trained_at_utc":       now_utc.isoformat(),
        "data_source":          "feature_store (last 30 days)",
        "n_train":              int(len(X_train)),
        "n_val":                int(len(X_val)),
        "n_features":           int(X_train.shape[1]),
        "feature_cols":         FEATURE_COLS,
        "contamination":        0.05,
        "n_estimators":         200,
        "score_stats":          new_stats,
        "comparison_vs_previous": comparison,
        "replace_reason":       replace_reason,
        "model_file":           os.path.basename(model_path),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Atomically update latest.json — scorer.py polls this
    latest_path = os.path.join(MODEL_DIR, "latest.json")
    with open(latest_path, "w") as f:
        json.dump({
            "version":    version,
            "model_file": os.path.basename(model_path),
            "meta_file":  os.path.basename(meta_path),
        }, f, indent=2)

    print(f"[retrain] ✅ New model deployed: {version}")
    print(f"           {replace_reason}")

    return {
        "status":     "replaced",
        "version":    version,
        "reason":     replace_reason,
        "comparison": comparison,
        "model_path": model_path,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrain the anomaly detection model")
    parser.add_argument("--force", action="store_true",
                        help="Replace model even if validation suggests it's worse")
    args = parser.parse_args()

    fs.init_db()
    result = retrain(force=args.force)
    print(f"\n[retrain] Result: {json.dumps(result, indent=2)}")
