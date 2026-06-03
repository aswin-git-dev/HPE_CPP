"""
validate.py
-----------
Validates the Isolation Forest model against synthetic ground truth labels.

Run:
  python validate.py --data merged_logs.xlsx --models models/

What it produces:
  1. AUC-ROC score for IF model
  2. Precision / Recall / F1 at multiple thresholds
  3. Per-attack-type detection rate
  4. Recommended contamination value
  5. Comparison: IF-only vs IF+GRU combined (if GRU model exists)

Why this matters:
  The IF model is unsupervised — it was never told which rows are anomalies.
  But our synthetic data HAS ground truth labels (_label column).
  We use those labels as the test set to measure how well the model
  actually detects each attack type.
"""

import os
import sys
import json
import argparse
import sqlite3

import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import (
    roc_auc_score, precision_recall_fscore_support,
    confusion_matrix, classification_report
)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from feature_store import init_db, DB_PATH, get_user_features, get_ip_features
from feature_engineer import parse_raw_log, engineer_features, features_to_vector, FEATURE_COLS
from train import normalize_score, compute_score_stats

MODEL_DIR = os.environ.get("MODEL_DIR", "models")


def load_if_model():
    latest_path = os.path.join(MODEL_DIR, "latest.json")
    with open(latest_path) as f:
        ptr = json.load(f)
    model = joblib.load(os.path.join(MODEL_DIR, ptr["model_file"]))
    with open(os.path.join(MODEL_DIR, ptr["meta_file"])) as f:
        meta = json.load(f)
    return model, meta


def build_feature_matrix_with_labels(df: pd.DataFrame):
    """
    Build feature matrix only for rows with known labels (normal/anomaly).
    Uses the feature store for historical context — same as training.
    Returns X, y_true, attack_types.
    """
    df = df.copy()
    df["Timestamp (UTC)"] = pd.to_datetime(
        df["Timestamp (UTC)"], utc=True, errors="coerce", format="mixed"
    )
    df = df.dropna(subset=["Timestamp (UTC)"])
    df = df.sort_values("Timestamp (UTC)").reset_index(drop=True)

    # Only evaluate on rows with known ground truth
    df_labeled = df[df["_label"].isin(["normal", "anomaly"])].copy()
    print(f"[validate] Evaluating on {len(df_labeled)} labeled rows "
          f"({(df_labeled['_label']=='anomaly').sum()} anomalies, "
          f"{(df_labeled['_label']=='normal').sum()} normal)")

    X = []
    y_true = []
    attack_types = []
    skipped = 0

    for i, row in df_labeled.iterrows():
        raw = row.to_dict()
        try:
            parsed    = parse_raw_log(raw)
            ts_dt     = parsed["ts_dt"]
            user_hist = get_user_features(parsed["user"],     ts_dt)
            ip_hist   = get_ip_features(parsed["source_ip"],  ts_dt)
            feats     = engineer_features(parsed, user_hist, ip_hist)
            vec       = features_to_vector(feats)
            X.append(vec)
            y_true.append(1 if row["_label"] == "anomaly" else 0)
            attack_types.append(str(row.get("Classification", "normal")))
        except Exception as e:
            skipped += 1
            continue

    if skipped:
        print(f"[validate] Skipped {skipped} rows due to parse errors.")

    return np.array(X), np.array(y_true), attack_types


def evaluate_if(model, meta, X, y_true):
    """Evaluate Isolation Forest at multiple thresholds."""
    score_stats = meta["score_stats"]

    raw_scores = model.decision_function(X)
    scores = np.array([normalize_score(s, score_stats) for s in raw_scores])

    auc = roc_auc_score(y_true, scores)
    print(f"\n{'='*60}")
    print(f"ISOLATION FOREST EVALUATION")
    print(f"{'='*60}")
    print(f"AUC-ROC: {auc:.4f}")
    print(f"  (0.5 = random, 0.7 = acceptable, 0.85+ = good)")
    print()

    # Evaluate at multiple thresholds
    print(f"{'Threshold':<12} {'Precision':<12} {'Recall':<12} {'F1':<12} {'Flagged%':<12}")
    print("-" * 60)
    best_f1 = 0
    best_threshold = 0.5
    for threshold in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        preds = (scores >= threshold).astype(int)
        if preds.sum() == 0:
            continue
        p, r, f1, _ = precision_recall_fscore_support(
            y_true, preds, average="binary", zero_division=0
        )
        flagged_pct = preds.mean() * 100
        marker = " ← best F1" if f1 > best_f1 else ""
        print(f"{threshold:<12.1f} {p:<12.3f} {r:<12.3f} {f1:<12.3f} {flagged_pct:<12.1f}%{marker}")
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold

    return scores, best_threshold, auc


def evaluate_per_attack_type(scores, y_true, attack_types, threshold):
    """Show detection rate per attack category."""
    print(f"\n{'='*60}")
    print(f"DETECTION RATE PER ATTACK TYPE  (threshold={threshold})")
    print(f"{'='*60}")
    preds = (scores >= threshold).astype(int)

    types = sorted(set(attack_types))
    print(f"{'Attack Type':<35} {'Count':<8} {'Detected':<10} {'Rate':<8}")
    print("-" * 65)
    for t in types:
        idx = [i for i, a in enumerate(attack_types) if a == t]
        count    = len(idx)
        detected = sum(preds[i] for i in idx if y_true[i] == 1)
        true_pos = sum(1 for i in idx if y_true[i] == 1)
        if true_pos == 0:
            rate_str = "N/A (normal class)"
        else:
            rate = detected / true_pos
            rate_str = f"{rate:.0%}"
        print(f"{t:<35} {count:<8} {detected:<10} {rate_str}")


def recommend_contamination(scores, y_true):
    """
    Recommend a better contamination value based on the actual anomaly rate
    in the training data vs what the model currently uses.
    """
    actual_anomaly_rate = y_true.mean()
    # Contamination should approximately match the true anomaly rate
    # but we set it slightly lower since IF is conservative
    recommended = round(actual_anomaly_rate * 0.8, 2)
    print(f"\n{'='*60}")
    print(f"CONTAMINATION RECOMMENDATION")
    print(f"{'='*60}")
    print(f"  Actual anomaly rate in labeled data: {actual_anomaly_rate:.1%}")
    print(f"  Your current contamination:          0.05 (5%)")
    print(f"  Recommended contamination:           {recommended} ({recommended*100:.0f}%)")
    print()
    if actual_anomaly_rate > 0.08:
        print(f"  ACTION: Retrain with --contamination {recommended}")
        print(f"  Command: python train.py --data merged_logs.xlsx "
              f"--out models/ --contamination {recommended}")
    else:
        print("  Your contamination=0.05 is close to the actual rate. No change needed.")
    return recommended


def check_gru_model():
    """Check if GRU model exists and return its metrics."""
    gru_path = os.path.join(MODEL_DIR, "gru_latest.json")
    if not os.path.exists(gru_path):
        return None
    with open(gru_path) as f:
        ptr = json.load(f)
    meta_path = os.path.join(MODEL_DIR, ptr["meta_file"])
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as f:
        meta = json.load(f)
    return meta


def main(data_path: str, models_dir: str):
    global MODEL_DIR
    MODEL_DIR = models_dir

    # ── Load model ────────────────────────────────────────────────────────
    print(f"[validate] Loading IF model from {models_dir}...")
    model, meta = load_if_model()
    print(f"[validate] Model version: {meta['version']}")
    print(f"[validate] Trained on:    {meta['n_train']} events")
    print(f"[validate] Contamination: {meta['contamination']}")

    # ── Load data ─────────────────────────────────────────────────────────
    print(f"[validate] Loading data from {data_path}...")
    if data_path.endswith(".xlsx"):
        df = pd.read_excel(data_path)
    else:
        df = pd.read_csv(data_path)

    if "_label" not in df.columns:
        print("ERROR: No '_label' column found. "
              "This script requires synthetic data with ground truth labels.")
        print("Run: python generate_synthetic.py --merge real_audit_800.xlsx")
        sys.exit(1)

    # Fill timestamp from Invocation Time if missing (same as train.py)
    if "Invocation Time" in df.columns:
        missing = df["Timestamp (UTC)"].isna()
        df.loc[missing, "Timestamp (UTC)"] = df.loc[missing, "Invocation Time"]

    # ── Build feature matrix ──────────────────────────────────────────────
    X, y_true, attack_types = build_feature_matrix_with_labels(df)

    if len(X) == 0:
        print("ERROR: No labeled rows could be processed.")
        sys.exit(1)

    # ── Evaluate IF ───────────────────────────────────────────────────────
    if_scores, best_threshold, if_auc = evaluate_if(model, meta, X, y_true)

    # ── Per-attack breakdown ──────────────────────────────────────────────
    evaluate_per_attack_type(if_scores, y_true, attack_types, best_threshold)

    # ── Contamination recommendation ─────────────────────────────────────
    recommended_contamination = recommend_contamination(if_scores, y_true)

    # ── GRU summary ───────────────────────────────────────────────────────
    gru_meta = check_gru_model()
    print(f"\n{'='*60}")
    print(f"GRU MODEL STATUS")
    print(f"{'='*60}")
    if gru_meta:
        print(f"  Version:     {gru_meta.get('version')}")
        print(f"  Val AUC-ROC: {gru_meta.get('val_auc', 'N/A'):.4f}")
        print(f"  Seq length:  {gru_meta.get('seq_len')} events per window")
        print(f"  Note: GRU activates after {gru_meta.get('seq_len')} events per user")
    else:
        print("  GRU model not found. Run: python train_gru.py --data merged_logs.xlsx")

    # ── Combined score summary ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  IF AUC-ROC:              {if_auc:.4f}")
    if gru_meta:
        print(f"  GRU AUC-ROC:             {gru_meta.get('val_auc', 0):.4f}")
        combined_auc_estimate = 0.6 * if_auc + 0.4 * gru_meta.get("val_auc", if_auc)
        print(f"  Combined estimate:       {combined_auc_estimate:.4f}  (IF×0.6 + GRU×0.4)")
    print(f"  Best threshold:          {best_threshold}")
    print(f"  Recommended contamination: {recommended_contamination}")
    print()

    if if_auc < 0.65:
        print("⚠️  IF AUC < 0.65. The model is barely better than random.")
        print("   Actions: increase contamination, add more synthetic anomaly diversity,")
        print("   or review whether feature store had enough history during training.")
    elif if_auc < 0.75:
        print("⚠️  IF AUC 0.65-0.75. Acceptable but room for improvement.")
        print(f"   Try: python train.py --data merged_logs.xlsx "
              f"--contamination {recommended_contamination}")
    else:
        print("✅ IF AUC > 0.75. Model is performing well.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate anomaly detection models")
    parser.add_argument("--data",   default="merged_logs.xlsx",
                        help="Path to labeled data (must have _label column)")
    parser.add_argument("--models", default="models",
                        help="Path to models directory")
    args = parser.parse_args()

    init_db()
    main(args.data, args.models)
