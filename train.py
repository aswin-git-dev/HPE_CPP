"""
train.py
--------
Training pipeline for the Isolation Forest anomaly detector.

Run this:
  python train.py --data merged_logs.xlsx --out models/

What it does:
  1. Loads raw logs (xlsx or csv)
  2. Normalises timestamp column (fills from Invocation Time if Timestamp (UTC) is null)
  3. Re-engineers features WITHOUT leakage (each row uses only history before it)
  4. Trains Isolation Forest
  5. Saves model + metadata (version, training date, score stats, feature list)

Retraining (called by retrain.py):
  Same function, called with fresh data pulled from the feature store DB.
"""

import os
import json
import argparse
import hashlib
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split

from feature_store import init_db, bulk_load_history, get_user_features, get_ip_features, DB_PATH
from feature_engineer import (
    parse_raw_log, engineer_features, features_to_vector,
    FEATURE_COLS, generate_reason
)
from thresholds import THRESHOLD_HIGH, THRESHOLD_MEDIUM

MODEL_DIR = os.environ.get("MODEL_DIR", "models")


def _model_version_tag() -> str:
    """Generate a version string based on current UTC timestamp."""
    return datetime.now(timezone.utc).strftime("v%Y%m%d_%H%M%S")


def _risk_level(score: float) -> str:
    if score > THRESHOLD_HIGH:
        return "HIGH"
    elif score > THRESHOLD_MEDIUM:
        return "MEDIUM"
    return "LOW"


def build_training_matrix(df: pd.DataFrame) -> tuple:
    """
    Build X (feature matrix) and metadata from a raw log DataFrame.

    IMPORTANT: We process rows in chronological order. For each row,
    we look up features from the feature store (which only contains
    events BEFORE this row), then immediately record the event so the
    next row sees it as history. This eliminates data leakage entirely.

    The feature store must be EMPTY when this is called during training.
    Do NOT call bulk_load_history() before this function.

    Returns:
      X         - numpy array (n_samples, n_features)
      meta_rows - list of dicts with parsed event info for each row
    """
    from feature_store import record_event

    df = df.copy()

    # FIX: pandas 3.x requires format="mixed" when the column contains both
    # "2026-04-22 05:40:25+00:00" (space, real rows) and
    # "2026-02-22T00:30:32+00:00" (T-sep, synthetic rows).
    # Without it, pd.to_datetime silently coerces mismatched formats to NaT.
    df["Timestamp (UTC)"] = pd.to_datetime(
        df["Timestamp (UTC)"], utc=True, errors="coerce", format="mixed"
    )
    df = df.dropna(subset=["Timestamp (UTC)"])
    df = df.sort_values("Timestamp (UTC)").reset_index(drop=True)

    X = []
    meta_rows = []

    print(f"[train] Building feature matrix for {len(df)} rows (chronological)...")
    for i, row in df.iterrows():
        raw = row.to_dict()
        try:
            parsed    = parse_raw_log(raw)
            ts_dt     = parsed["ts_dt"]
            # Look up history BEFORE recording this event — no leakage
            user_hist = get_user_features(parsed["user"], ts_dt)
            ip_hist   = get_ip_features(parsed["source_ip"], ts_dt)
            feats     = engineer_features(parsed, user_hist, ip_hist)
            vec       = features_to_vector(feats)
            X.append(vec)
            meta_rows.append({"parsed": parsed, "user_hist": user_hist, "ip_hist": ip_hist})
            # Record AFTER feature extraction so the next row sees this as history
            record_event(parsed, anomaly_score=None, model_version=None)
        except Exception as e:
            print(f"[train] Skipping row {i}: {e}")
            continue

        if (i + 1) % 100 == 0:
            print(f"[train]   {i+1}/{len(df)} rows processed")

    return np.array(X), meta_rows


def compute_score_stats(raw_scores: np.ndarray) -> dict:
    """
    Compute training-set score statistics saved with the model.
    Used at inference time for stable normalization.
    """
    return {
        "min":  float(raw_scores.min()),
        "max":  float(raw_scores.max()),
        "mean": float(raw_scores.mean()),
        "std":  float(raw_scores.std()),
        "p90":  float(np.percentile(raw_scores, 90)),
        "p95":  float(np.percentile(raw_scores, 95)),
        "p99":  float(np.percentile(raw_scores, 99)),
    }


def normalize_score(raw_score: float, stats: dict) -> float:
    """
    Normalize a raw Isolation Forest score using TRAINING distribution stats.
    Flipped so 1.0 = most anomalous, 0.0 = most normal.
    """
    lo, hi = stats["min"], stats["max"]
    if hi == lo:
        return 0.5
    normalized = (raw_score - lo) / (hi - lo)
    return float(1.0 - normalized)


def train(data_path: str, out_dir: str = MODEL_DIR,
          contamination: float = 0.05, n_estimators: int = 200,
          test_size: float = 0.15):
    """
    Full training run. Saves model artifacts to out_dir.
    Returns the version tag of the saved model.
    """
    os.makedirs(out_dir, exist_ok=True)

    # ── 1. Verify the feature store is empty ──────────────────────────────────
    # bulk_load_history() must NOT be called here. build_training_matrix()
    # feeds rows one-by-one, recording each AFTER feature extraction.
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    if count > 0:
        print(f"[train] WARNING: feature store has {count} existing events. "
              "Delete feature_store.db and re-run for a fully clean training run.")
    else:
        print(f"[train] Feature store is empty — training from scratch (correct).")

    # ── 2. Load raw dataframe ─────────────────────────────────────────────────
    if data_path.endswith(".xlsx"):
        df = pd.read_excel(data_path)
    else:
        df = pd.read_csv(data_path)

    print(f"[train] Loaded {len(df)} raw events.")

    # ── 2a. Normalise timestamp column ────────────────────────────────────────
    # Real rows      → "Timestamp (UTC)"   (800 rows, space-separator strings)
    # Synthetic rows → "Invocation Time"   (6998 rows, T-separator strings)
    # build_training_matrix drops rows where "Timestamp (UTC)" is null,
    # so fill it from "Invocation Time" first.
    if "Invocation Time" in df.columns:
        missing_ts = df["Timestamp (UTC)"].isna()
        df.loc[missing_ts, "Timestamp (UTC)"] = df.loc[missing_ts, "Invocation Time"]
        filled = int(missing_ts.sum())
        if filled:
            print(f"[train] Filled {filled} missing 'Timestamp (UTC)' from 'Invocation Time'.")

    # ── 3. Build feature matrix ───────────────────────────────────────────────
    X, meta_rows = build_training_matrix(df)
    print(f"[train] Feature matrix shape: {X.shape}")

    if len(X) < 50:
        raise ValueError(f"Too few valid rows ({len(X)}) to train. Check your data.")

    # ── 4. Chronological train/validation split ───────────────────────────────
    split_idx = int(len(X) * (1 - test_size))
    X_train = X[:split_idx]
    X_val   = X[split_idx:]
    print(f"[train] Train: {len(X_train)} | Validation: {len(X_val)}")

    # ── 5. Train model ────────────────────────────────────────────────────────
    print(f"[train] Training IsolationForest "
          f"(n_estimators={n_estimators}, contamination={contamination})...")
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train)

    # ── 6. Score stats on TRAINING set only ──────────────────────────────────
    train_raw_scores = model.decision_function(X_train)
    score_stats = compute_score_stats(train_raw_scores)
    print(f"[train] Score stats (training set): {score_stats}")

    # ── 7. Validation metrics ─────────────────────────────────────────────────
    anomaly_rate = None
    if len(X_val) > 0:
        val_raw    = model.decision_function(X_val)
        val_scores = np.array([normalize_score(s, score_stats) for s in val_raw])
        anomaly_rate = float((val_scores > 0.5).mean())
        print(f"[train] Validation anomaly rate (score>0.5): {anomaly_rate:.2%}")
        if anomaly_rate > 0.3:
            print(f"[train] WARNING: anomaly rate {anomaly_rate:.0%} is high. "
                  "Consider increasing contamination or reviewing data quality.")

    # ── 8. Save everything ────────────────────────────────────────────────────
    version     = _model_version_tag()
    model_path  = os.path.join(out_dir, f"isolation_forest_{version}.pkl")
    meta_path   = os.path.join(out_dir, f"model_meta_{version}.json")
    latest_path = os.path.join(out_dir, "latest.json")

    joblib.dump(model, model_path)

    meta = {
        "version":          version,
        "trained_at_utc":   datetime.now(timezone.utc).isoformat(),
        "data_source":      data_path,
        "n_train":          int(len(X_train)),
        "n_val":            int(len(X_val)),
        "n_features":       int(X.shape[1]),
        "feature_cols":     FEATURE_COLS,
        "contamination":    contamination,
        "n_estimators":     n_estimators,
        "score_stats":      score_stats,
        "anomaly_rate_val": anomaly_rate,
        "model_file":       os.path.basename(model_path),
    }

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    with open(latest_path, "w") as f:
        json.dump({
            "version":    version,
            "model_file": os.path.basename(model_path),
            "meta_file":  os.path.basename(meta_path),
        }, f, indent=2)

    print(f"\n[train] ✅ Model saved:")
    print(f"         Model:   {model_path}")
    print(f"         Meta:    {meta_path}")
    print(f"         Version: {version}")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the anomaly detection model")
    parser.add_argument("--data",          required=True,  help="Path to xlsx or csv training data")
    parser.add_argument("--out",           default=MODEL_DIR, help="Output directory for model artifacts")
    parser.add_argument("--contamination", type=float, default=0.05)
    parser.add_argument("--estimators",    type=int,   default=200)
    args = parser.parse_args()

    init_db()
    train(
        data_path=args.data,
        out_dir=args.out,
        contamination=args.contamination,
        n_estimators=args.estimators,
    )
