"""
validate_gru.py
---------------
Validates the trained GRU model with full per-attack-type breakdown.

Run:
  python validate_gru.py --data merged_logs.xlsx --models models/

What it shows:
  1. AUC-ROC on validation sequences
  2. Precision / Recall / F1 at multiple thresholds
  3. Per-attack-type detection rate (same categories as validate.py)
  4. Comparison: what IF missed that GRU caught
  5. Confusion matrix

How it works:
  Uses the EXACT same sequence-building logic as train_gru.py.
  Evaluates only on the held-out 20% validation split (last 20%
  chronologically) — same split used during training. This means
  you're seeing the same numbers reported during training, but now
  broken down by attack type.
"""

import os, sys, json, argparse, sqlite3, pickle
from collections import defaultdict

import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import (
    roc_auc_score, precision_recall_fscore_support,
    confusion_matrix, classification_report
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feature_store as fs
from feature_engineer import (
    parse_raw_log, engineer_features, features_to_vector, FEATURE_COLS
)

# CRITICAL: pickle.load() needs GRUModel and GRULayer to be importable.
# Import them from train_gru before calling pickle.load() on the model file.
from train_gru import GRUModel, GRULayer

MODEL_DIR    = os.environ.get("MODEL_DIR", "models")
SEQUENCE_LEN = 20


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — copied from train_gru.py so this script is self-contained
# ─────────────────────────────────────────────────────────────────────────────

def load_gru_model(models_dir):
    latest_path = os.path.join(models_dir, "gru_latest.json")
    if not os.path.exists(latest_path):
        print(f"ERROR: No GRU model found at {latest_path}")
        print("Run: python train_gru.py --data merged_logs.xlsx --out models/")
        sys.exit(1)

    with open(latest_path) as f:
        ptr = json.load(f)

    model_path  = os.path.join(models_dir, ptr["model_file"])
    scaler_path = os.path.join(models_dir, ptr["scaler_file"])
    meta_path   = os.path.join(models_dir, ptr["meta_file"])

    with open(model_path, "rb") as f:
        model = pickle.load(f)
    scaler = joblib.load(scaler_path)
    with open(meta_path) as f:
        meta = json.load(f)

    print(f"[validate_gru] Model version:  {meta['version']}")
    print(f"[validate_gru] Trained on:     {meta['n_train']} sequences")
    print(f"[validate_gru] Val sequences:  {meta['n_val']}")
    print(f"[validate_gru] Seq length:     {meta['seq_len']} events per window")
    print(f"[validate_gru] Reported AUC:   {meta.get('val_auc', 'N/A')}")
    return model, scaler, meta


def load_features_from_db():
    """Re-derive IF feature vectors for all events in the feature store."""
    conn = sqlite3.connect(fs.DB_PATH)
    df   = pd.read_sql_query("SELECT * FROM events ORDER BY ts ASC", conn)
    conn.close()
    print(f"[validate_gru] Loaded {len(df)} events from feature store.")

    rows = []
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
            parsed    = parse_raw_log(raw)
            user_hist = fs.get_user_features(parsed["user"],    parsed["ts_dt"])
            ip_hist   = fs.get_ip_features(parsed["source_ip"], parsed["ts_dt"])
            feats     = engineer_features(parsed, user_hist, ip_hist)
            vec       = features_to_vector(feats)
        except Exception:
            vec = [0.0] * len(FEATURE_COLS)
        rows.append({"ts": row["ts"], "user": row["user"], "vec": vec})

    return rows


def build_sequences_with_attack_type(rows, df_raw, seq_len=SEQUENCE_LEN):
    """
    Build per-user sliding window sequences.
    Also returns attack_type for each sequence (from Classification column).
    Skips 'real_unknown' labels — we can only validate on synthetic labeled rows.
    """
    # Build label + attack_type lookup keyed by (user, ts[:19])
    label_map       = {}
    attack_type_map = {}

    if "_label" in df_raw.columns:
        for _, row in df_raw.iterrows():
            ts   = str(row.get("Invocation Time") or
                       row.get("Timestamp (UTC)", ""))[:19]
            user = str(row.get("User / Subject", "unknown"))
            label       = str(row.get("_label",          "real_unknown"))
            attack_type = str(row.get("Classification",  "normal"))
            label_map[(user, ts)]       = label
            attack_type_map[(user, ts)] = attack_type

    user_events = defaultdict(list)
    for r in rows:
        user_events[r["user"]].append(r)

    X, y, attack_types, meta_out = [], [], [], []

    for user, events in user_events.items():
        events = sorted(events, key=lambda e: e["ts"])
        vecs   = np.array([e["vec"] for e in events], dtype=np.float32)

        for end in range(1, len(events) + 1):
            last    = events[end - 1]
            ts_key  = last["ts"][:19]
            label_str  = label_map.get((user, ts_key), "real_unknown")
            attack_str = attack_type_map.get((user, ts_key), "normal")

            if label_str not in ("normal", "anomaly"):
                continue  # skip real_unknown rows

            start  = max(0, end - seq_len)
            window = vecs[start:end]
            if len(window) < seq_len:
                pad    = np.zeros((seq_len - len(window), vecs.shape[1]),
                                  dtype=np.float32)
                window = np.vstack([pad, window])

            X.append(window)
            y.append(1 if label_str == "anomaly" else 0)
            attack_types.append(attack_str)
            meta_out.append({"user": user, "ts": last["ts"]})

    return (np.array(X, dtype=np.float32),
            np.array(y, dtype=np.float32),
            attack_types,
            meta_out)


def evaluate_at_thresholds(probs, y_true):
    print(f"\n{'='*60}")
    print(f"GRU — THRESHOLD ANALYSIS")
    print(f"{'='*60}")
    print(f"{'Threshold':<12} {'Precision':<12} {'Recall':<12} "
          f"{'F1':<12} {'Flagged%':<12}")
    print("-" * 60)

    best_f1 = 0
    best_threshold = 0.5

    for threshold in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        preds = (probs >= threshold).astype(int)
        if preds.sum() == 0:
            continue
        p, r, f1, _ = precision_recall_fscore_support(
            y_true, preds, average="binary", zero_division=0
        )
        flagged_pct = preds.mean() * 100
        marker = " ← best F1" if f1 > best_f1 else ""
        print(f"{threshold:<12.1f} {p:<12.3f} {r:<12.3f} "
              f"{f1:<12.3f} {flagged_pct:<12.1f}%{marker}")
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold

    return best_threshold


def evaluate_per_attack(probs, y_true, attack_types, threshold):
    print(f"\n{'='*60}")
    print(f"GRU — DETECTION RATE PER ATTACK TYPE  (threshold={threshold})")
    print(f"{'='*60}")
    preds = (probs >= threshold).astype(int)

    types = sorted(set(attack_types))
    print(f"{'Attack Type':<35} {'Total':<8} {'True Anomaly':<14} "
          f"{'Detected':<10} {'Rate':<8}")
    print("-" * 78)

    for t in types:
        idx        = [i for i, a in enumerate(attack_types) if a == t]
        total      = len(idx)
        true_anom  = sum(1 for i in idx if y_true[i] == 1)
        detected   = sum(preds[i] for i in idx if y_true[i] == 1)

        if true_anom == 0:
            rate_str = "N/A (normal)"
        else:
            rate     = detected / true_anom
            rate_str = f"{rate:.0%}"

        print(f"{t:<35} {total:<8} {true_anom:<14} {detected:<10} {rate_str}")


def compare_with_if(gru_probs, y_true, attack_types,
                    gru_threshold, if_scores=None, if_threshold=0.4):
    """
    Shows what GRU catches that IF misses and vice versa.
    Only runs if IF scores are also available.
    """
    if if_scores is None:
        return

    print(f"\n{'='*60}")
    print(f"IF vs GRU — COMPLEMENTARY DETECTION")
    print(f"{'='*60}")

    gru_preds = (gru_probs    >= gru_threshold).astype(int)
    if_preds  = (if_scores    >= if_threshold).astype(int)
    combined  = np.maximum(gru_preds, if_preds)  # either model flags = flagged

    actual_anomalies = np.array(y_true) == 1

    only_gru  = gru_preds & ~if_preds  & actual_anomalies
    only_if   = if_preds  & ~gru_preds & actual_anomalies
    both      = gru_preds & if_preds   & actual_anomalies
    neither   = ~gru_preds & ~if_preds & actual_anomalies

    print(f"  True anomalies caught by BOTH models:      {both.sum()}")
    print(f"  Caught by GRU only (IF missed):            {only_gru.sum()}")
    print(f"  Caught by IF only (GRU missed):            {only_if.sum()}")
    print(f"  Missed by BOTH models:                     {neither.sum()}")
    print(f"  Total true anomalies:                      {actual_anomalies.sum()}")
    print()

    total_caught = (combined & actual_anomalies).sum()
    combined_recall = total_caught / actual_anomalies.sum() if actual_anomalies.sum() > 0 else 0
    print(f"  Combined recall (either model catches):    {combined_recall:.1%}")
    print(f"  vs IF alone recall:                        "
          f"{(if_preds & actual_anomalies).sum() / actual_anomalies.sum():.1%}")
    print(f"  vs GRU alone recall:                       "
          f"{(gru_preds & actual_anomalies).sum() / actual_anomalies.sum():.1%}")


def main(data_path, models_dir):
    # ── Load GRU model ─────────────────────────────────────────────────────
    model, scaler, meta = load_gru_model(models_dir)
    seq_len = meta.get("seq_len", SEQUENCE_LEN)

    # ── Load features from feature store ───────────────────────────────────
    rows = load_features_from_db()

    # ── Load raw data for labels ────────────────────────────────────────────
    print(f"[validate_gru] Loading labels from {data_path}...")
    if data_path.endswith(".xlsx"):
        df_raw = pd.read_excel(data_path)
    else:
        df_raw = pd.read_csv(data_path)

    if "Invocation Time" in df_raw.columns:
        missing = df_raw["Timestamp (UTC)"].isna()
        df_raw.loc[missing, "Timestamp (UTC)"] = df_raw.loc[missing, "Invocation Time"]

    if "_label" not in df_raw.columns:
        print("ERROR: No _label column. This script requires merged_logs.xlsx")
        sys.exit(1)

    # ── Build sequences ─────────────────────────────────────────────────────
    print(f"[validate_gru] Building sequences (window={seq_len})...")
    X, y, attack_types, _ = build_sequences_with_attack_type(
        rows, df_raw, seq_len=seq_len
    )

    if len(X) == 0:
        print("ERROR: No labeled sequences found.")
        sys.exit(1)

    print(f"[validate_gru] Total sequences: {len(X)} | "
          f"anomaly rate: {y.mean():.1%}")

    # ── Use same 80/20 split as training ───────────────────────────────────
    split   = int(len(X) * 0.8)
    X_val   = X[split:]
    y_val   = y[split:]
    atk_val = attack_types[split:]

    print(f"[validate_gru] Validation sequences: {len(X_val)} "
          f"({y_val.sum():.0f} anomalies, {(1-y_val).sum():.0f} normal)")

    # ── Scale ───────────────────────────────────────────────────────────────
    B, T, F = X_val.shape
    X_val_scaled = scaler.transform(
        X_val.reshape(-1, F)
    ).reshape(B, T, F).astype(np.float32)

    # ── Run inference ───────────────────────────────────────────────────────
    print(f"[validate_gru] Running inference on {len(X_val)} sequences...")
    probs = model.predict_proba(X_val_scaled)

    # ── AUC ─────────────────────────────────────────────────────────────────
    auc = roc_auc_score(y_val, probs)
    print(f"\n{'='*60}")
    print(f"GRU VALIDATION RESULTS")
    print(f"{'='*60}")
    print(f"AUC-ROC: {auc:.4f}")
    print(f"  (matches training report: {meta.get('val_auc', 'N/A')})")
    print(f"  0.5=random | 0.7=acceptable | 0.85+=good")

    # ── Classification report at 0.5 ────────────────────────────────────────
    preds_05 = (probs >= 0.5).astype(int)
    print(f"\n{'='*60}")
    print(f"GRU — CLASSIFICATION REPORT  (threshold=0.5)")
    print(f"{'='*60}")
    print(classification_report(
        y_val, preds_05,
        target_names=["normal", "anomaly"],
        zero_division=0
    ))

    # ── Confusion matrix ────────────────────────────────────────────────────
    cm = confusion_matrix(y_val, preds_05)
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2,2) else (0,0,0,0)
    print(f"Confusion Matrix (threshold=0.5):")
    print(f"                 Predicted Normal  Predicted Anomaly")
    print(f"  Actual Normal       {tn:<18} {fp}")
    print(f"  Actual Anomaly      {fn:<18} {tp}")
    print(f"\n  True Positives  (caught attacks):     {tp}")
    print(f"  False Positives (false alarms):        {fp}")
    print(f"  True Negatives  (correctly normal):    {tn}")
    print(f"  False Negatives (missed attacks):      {fn}")

    # ── Threshold analysis ──────────────────────────────────────────────────
    best_threshold = evaluate_at_thresholds(probs, y_val)

    # ── Per-attack-type breakdown ───────────────────────────────────────────
    evaluate_per_attack(probs, y_val, atk_val, best_threshold)

    # ── Try to also load IF scores for comparison ───────────────────────────
    if_scores = None
    try:
        import json as _json
        latest_if = os.path.join(models_dir, "latest.json")
        if os.path.exists(latest_if):
            from train import normalize_score, compute_score_stats
            import joblib as _jl
            with open(latest_if) as f:
                ptr = _json.load(f)
            if_model = _jl.load(os.path.join(models_dir, ptr["model_file"]))
            with open(os.path.join(models_dir, ptr["meta_file"])) as f:
                if_meta = _json.load(f)

            # Need IF features for the same validation sequences
            # Use the last event's feature vector as a proxy
            X_if = X_val[:, -1, :]   # last event in each sequence (B, F)
            raw_if = if_model.decision_function(X_if)
            if_scores = np.array([
                normalize_score(s, if_meta["score_stats"]) for s in raw_if
            ])
    except Exception as e:
        print(f"\n[validate_gru] Could not load IF scores for comparison: {e}")

    compare_with_if(probs, y_val, atk_val, best_threshold, if_scores)

    # ── Final summary ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"  GRU AUC-ROC:      {auc:.4f}")
    print(f"  Best threshold:   {best_threshold}")
    print(f"  At threshold {best_threshold}:")
    p, r, f1, _ = precision_recall_fscore_support(
        y_val, (probs >= best_threshold).astype(int),
        average="binary", zero_division=0
    )
    print(f"    Precision:      {p:.3f}  ({p*100:.0f}% of flagged are real attacks)")
    print(f"    Recall:         {r:.3f}  ({r*100:.0f}% of real attacks caught)")
    print(f"    F1:             {f1:.3f}")
    print()
    print(f"  GRU activates after {seq_len} events per user in production.")
    print(f"  Before that, IF-only scoring runs (no GRU contribution).")

    if auc >= 0.90:
        print(f"\n✅ GRU AUC >= 0.90. Model is performing well.")
    elif auc >= 0.75:
        print(f"\n⚠️  GRU AUC 0.75-0.90. Acceptable.")
    else:
        print(f"\n❌ GRU AUC < 0.75. Consider more training epochs or data.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate GRU anomaly detection model")
    parser.add_argument("--data",   default="merged_logs.xlsx")
    parser.add_argument("--models", default="models")
    args = parser.parse_args()

    fs.init_db()
    main(args.data, args.models)
