"""
scorer.py
---------
Unified scorer: runs IF + GRU and combines scores.

IF score:  0-1, statistical outlier in feature space
GRU score: 0-1, behavioral sequence anomaly

Combined:  weighted average (IF 60%, GRU 40%)
           GRU is skipped if not enough history for a sequence window.

Hot-reloads both models when latest.json / gru_latest.json change.
"""

import os
import json
import pickle
import numpy as np
import joblib
from datetime import datetime, timezone
from collections import defaultdict, deque
from thresholds import THRESHOLD_HIGH, THRESHOLD_MEDIUM
from spot_threshold import update_spot, get_risk_level, get_spot_status

import feature_store as fs
from feature_engineer import (
    parse_raw_log, engineer_features, features_to_vector,
    FEATURE_COLS, generate_reason
)
from train import normalize_score
from train_gru import GRUModel, GRULayer  # required for pickle to deserialize the GRU model

# ── Safe GRU unpickler ────────────────────────────────────────────────────────
# When train_gru.py is run as __main__, pickle saves class paths as
# __main__.GRUModel / __main__.GRULayer. This unpickler remaps them to
# train_gru.GRUModel / train_gru.GRULayer so loading works from any context.
import io

class _GRUUnpickler(pickle.Unpickler):
    _remap = {
        ("__main__", "GRUModel"):  GRUModel,
        ("__main__", "GRULayer"):  GRULayer,
        ("train_gru", "GRUModel"): GRUModel,
        ("train_gru", "GRULayer"): GRULayer,
    }
    def find_class(self, module, name):
        cls = self._remap.get((module, name))
        if cls is not None:
            return cls
        return super().find_class(module, name)

def _safe_gru_load(file_obj):
    """Load a GRU pickle regardless of which module it was saved from."""
    return _GRUUnpickler(file_obj).load()

MODEL_DIR = os.environ.get("MODEL_DIR", "models")

# Per-user in-memory sequence buffer (last 20 feature vectors)
# This lets GRU score without hitting the DB for every event
_user_seq_buffer: dict = defaultdict(lambda: deque(maxlen=20))

IF_WEIGHT  = 0.6
GRU_WEIGHT = 0.4
GRU_SEQ_LEN = 20


class IFRegistry:
    """Isolation Forest model registry with hot-reload."""
    def __init__(self):
        self.model = None; self.meta = None
        self.version = None; self.score_stats = None
        self._loaded_file = None

    def load(self):
        path = os.path.join(MODEL_DIR, "latest.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No IF model at {path}. Run train.py first.")
        with open(path) as f: ptr = json.load(f)
        mf = os.path.join(MODEL_DIR, ptr["model_file"])
        if mf == self._loaded_file: return
        print(f"[scorer] Loading IF model: {mf}")
        self.model = joblib.load(mf)
        with open(os.path.join(MODEL_DIR, ptr["meta_file"])) as f:
            self.meta = json.load(f)
        self.version = self.meta["version"]
        self.score_stats = self.meta["score_stats"]
        self._loaded_file = mf
        saved = self.meta.get("feature_cols", [])
        if saved != FEATURE_COLS:
            raise RuntimeError(f"Feature mismatch. Retrain model.\n  Saved: {saved}\n  Current: {FEATURE_COLS}")
        print(f"[scorer] ✅ IF model {self.version} ready (trained on {self.meta['n_train']} events).")

    def reload_if_updated(self):
        path = os.path.join(MODEL_DIR, "latest.json")
        if not os.path.exists(path): return
        with open(path) as f: ptr = json.load(f)
        mf = os.path.join(MODEL_DIR, ptr["model_file"])
        if mf != self._loaded_file:
            print(f"[scorer] IF model updated → reloading {ptr['version']}")
            self.load()


class GRURegistry:
    """GRU model registry with hot-reload. Gracefully absent if not trained."""
    def __init__(self):
        self.model = None; self.scaler = None; self.meta = None
        self._loaded_file = None

    def load(self):
        path = os.path.join(MODEL_DIR, "gru_latest.json")
        if not os.path.exists(path):
            return  # GRU not trained yet — fine, IF-only mode
        with open(path) as f: ptr = json.load(f)
        mf = os.path.join(MODEL_DIR, ptr["model_file"])
        if mf == self._loaded_file: return
        print(f"[scorer] Loading GRU model: {mf}")
        with open(mf, "rb") as f:
            self.model = _safe_gru_load(f)
        self.scaler = joblib.load(os.path.join(MODEL_DIR, ptr["scaler_file"]))
        with open(os.path.join(MODEL_DIR, ptr["meta_file"])) as f:
            self.meta = json.load(f)
        self._loaded_file = mf
        print(f"[scorer] ✅ GRU model {self.meta['version']} ready.")

    def reload_if_updated(self):
        path = os.path.join(MODEL_DIR, "gru_latest.json")
        if not os.path.exists(path): return
        with open(path) as f: ptr = json.load(f)
        mf = os.path.join(MODEL_DIR, ptr["model_file"])
        if mf != self._loaded_file:
            print(f"[scorer] GRU model updated → reloading")
            self.load()

    @property
    def ready(self):
        return self.model is not None


_if_reg  = IFRegistry()
_gru_reg = GRURegistry()

def score_event(raw_log: dict) -> dict:
    """
    Score a single raw log event using IF + GRU (if available).
    Returns combined anomaly_score, risk_level, reason, per-model scores.
    """
    # ── Reload check ──────────────────────────────────────────────────────
    _if_reg.reload_if_updated()
    _gru_reg.reload_if_updated()
    if _if_reg.model is None:
        _if_reg.load()
    if not _gru_reg.ready:
        _gru_reg.load()

    # ── Parse & feature extraction ────────────────────────────────────────
    parsed    = parse_raw_log(raw_log)
    ts_dt     = parsed["ts_dt"]
    user_hist = fs.get_user_features(parsed["user"],     ts_dt)
    ip_hist   = fs.get_ip_features(parsed["source_ip"],  ts_dt)
    feats     = engineer_features(parsed, user_hist, ip_hist)
    vec       = features_to_vector(feats)

    # ── IF score ──────────────────────────────────────────────────────────
    X_if      = np.array([vec])
    raw_score = float(_if_reg.model.decision_function(X_if)[0])
    if_score  = normalize_score(raw_score, _if_reg.score_stats)

    # ── GRU score ─────────────────────────────────────────────────────────
    gru_score    = None
    gru_active   = False
    user          = parsed["user"]
    _user_seq_buffer[user].append(vec)

    if _gru_reg.ready and len(_user_seq_buffer[user]) >= GRU_SEQ_LEN:
        try:
            seq = np.array(list(_user_seq_buffer[user]), dtype=np.float32)  # (20, 27)
            # Scale using training scaler
            seq_scaled = _gru_reg.scaler.transform(seq)
            X_gru = seq_scaled[np.newaxis, :, :]   # (1, 20, 27)
            gru_score  = float(_gru_reg.model.predict_proba(X_gru)[0])
            gru_active = True
        except Exception as e:
            print(f"[scorer] GRU inference error: {e}")

    # ── Combine ───────────────────────────────────────────────────────────
    if gru_active and gru_score is not None:
        combined = IF_WEIGHT * if_score + GRU_WEIGHT * gru_score
    else:
        combined = if_score   # fall back to IF-only until enough history

    update_spot(combined)
    risk        = get_risk_level(combined)
    spot_status = get_spot_status()
    reason      = generate_reason(parsed, user_hist, ip_hist, combined)

    # Console log — shows SPOT threshold status on every scored event
    if spot_status["warmed_up"]:
        print(
            f"[scorer] {parsed['ts']} | "
            f"user={parsed['user'][:30]:<30} | "
            f"score={combined:.4f} | "
            f"risk={risk:<6} | "
            f"SPOT HIGH={spot_status['threshold_high']:.4f} "
            f"MEDIUM={spot_status['threshold_medium']:.4f} "
            f"[dynamic | n={spot_status['n_total']}]"
        )
    else:
        print(
            f"[scorer] {parsed['ts']} | "
            f"user={parsed['user'][:30]:<30} | "
            f"score={combined:.4f} | "
            f"risk={risk:<6} | "
            f"SPOT warming up {spot_status['n_total']}/1000 "
            f"[fallback HIGH={THRESHOLD_HIGH} MEDIUM={THRESHOLD_MEDIUM}]"
        )

    # ── Record (AFTER scoring) ────────────────────────────────────────────
    fs.record_event(parsed, anomaly_score=combined,
                    model_version=_if_reg.version)

    # REPLACE WITH
    return {
        "ts":                    parsed["ts"],
        "user":                  parsed["user"],
        "source_ip":             parsed["source_ip"],
        "namespace":             parsed["namespace"],
        "object_type":           parsed["object_type"],
        "method":                parsed["method"],
        "anomaly_score":         round(combined, 4),
        "if_score":              round(if_score, 4),
        "gru_score":             round(gru_score, 4) if gru_score is not None else None,
        "gru_active":            gru_active,
        "risk_level":            risk,
        "reason":                reason,
        "model_version":         _if_reg.version,
        "spot_threshold_high":   round(spot_status["threshold_high"],   4),
        "spot_threshold_medium": round(spot_status["threshold_medium"], 4),
        "spot_mode":             spot_status["mode"],
        "features":              {k: round(v, 4) if isinstance(v, float) else v
                                  for k, v in feats.items()},
    }

def score_batch(raw_logs: list) -> list:
    """Score a list in chronological order — no leakage."""
    results = []
    for raw in sorted(raw_logs,
                      key=lambda r: r.get("Timestamp (UTC)") or r.get("ts") or ""):
        try:
            results.append(score_event(raw))
        except Exception as e:
            results.append({"error": str(e), "raw": str(raw)[:200]})
    return results


def get_model_info() -> dict:
    if _if_reg.meta is None:
        return {"status": "no model loaded"}
    info = {
        "if_model": {
            "version":     _if_reg.version,
            "trained_at":  _if_reg.meta.get("trained_at_utc"),
            "n_train":     _if_reg.meta.get("n_train"),
        },
        "gru_model": None,
        "scoring_mode": "IF+GRU" if _gru_reg.ready else "IF-only",
        "feature_count": len(FEATURE_COLS),
    }
    if _gru_reg.ready and _gru_reg.meta:
        info["gru_model"] = {
            "version":  _gru_reg.meta.get("version"),
            "val_auc":  _gru_reg.meta.get("val_auc"),
            "seq_len":  _gru_reg.meta.get("seq_len"),
        }
    return info