"""
feature_engineer.py
-------------------
Converts a raw log event dict into a fixed-length numeric feature vector
suitable for Isolation Forest inference.

Key design rules:
  1. NEVER uses batch statistics. Every feature is either:
       a) derived from the single event itself (hour, is_sensitive, etc.)
       b) looked up from the feature_store (historical rolling windows)
  2. Uses feature hashing for categorical columns — never LabelEncoder.
     LabelEncoder crashes on unseen values. Feature hashing never does.
  3. The feature list is the single source of truth. Training and inference
     must use IDENTICAL feature columns in IDENTICAL order.
  4. A frozen copy of feature metadata is saved alongside the model .pkl
     so you can always reconstruct what features version N used.
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional

# ── Categorical columns and their hash bucket sizes ──────────────────────────
# Larger bucket = fewer collisions but more memory.
# 10_000 is fine for user/IP counts you'll see in K8s clusters.
HASH_BUCKETS = {
    "user":        10_000,
    "source_ip":   10_000,
    "namespace":    5_000,
    "object_type":  2_000,
    "method":         100,
    "event_type":     500,
}

# ── Sensitive resource keywords ───────────────────────────────────────────────
SENSITIVE_RESOURCES = {"secret", "configmap", "clusterrole", "rolebinding", "pods/exec", "exec"}

# ── High-risk methods ─────────────────────────────────────────────────────────
HIGH_RISK_METHODS = {"create", "delete", "patch", "update"}

# RBAC resource keywords
RBAC_RESOURCES = {"role", "rolebinding", "clusterrole", "clusterrolebinding", "serviceaccount"}

# ── The canonical feature list — ORDER MATTERS ────────────────────────────────
# This must be identical at training time and inference time.
# Save this alongside your model .pkl.
FEATURE_COLS = [
    # Categorical (hashed)
    "feat_user_hash",
    "feat_ip_hash",
    "feat_namespace_hash",
    "feat_object_type_hash",
    "feat_method_hash",
    "feat_event_type_hash",

    # Temporal
    "feat_hour",
    "feat_day_of_week",
    "feat_is_off_hours",       # before 6am or after 8pm

    # Event-level flags
    "feat_is_sensitive",       # resource is secret/configmap/clusterrole/rolebinding
    "feat_is_failed",          # result != success
    "feat_is_high_risk_method",
    "feat_sensitive_offhour",  # interaction: sensitive AND off-hours

    # Historical user features (from feature_store)
    "feat_hist_req_24h",
    "feat_hist_req_7d",
    "feat_hist_req_30d",
    "feat_hist_fail_ratio_7d",
    "feat_hist_unique_namespaces",
    "feat_hist_unique_resources",
    "feat_hist_unique_ips",
    "feat_hist_sensitive_rate_7d",
    "feat_hist_user_hour_baseline",
    "feat_is_new_user",

    # Historical IP features (from feature_store)
    "feat_hist_ip_req_24h",
    "feat_hist_ip_fail_ratio_24h",
    "feat_hist_ip_unique_users",
    "feat_is_new_ip",

    # Burst and RBAC features
    "feat_fail_burst_5min",     # failed requests in last 5 min (from IP)
    "feat_is_rbac_resource",    # 1 if role/binding/clusterrole
]


def _hash_feature(value: str, buckets: int) -> int:
    """
    Map any string to an integer in [0, buckets).
    Deterministic. Never raises on unseen values.
    """
    raw = hashlib.md5(str(value).encode("utf-8")).hexdigest()
    return int(raw, 16) % buckets


def parse_raw_log(raw: dict) -> dict:
    """
    Normalize a raw log dict from Falco/K8s audit into a clean internal dict.
    Handles missing fields gracefully — never raises KeyError.

    Input keys (from your xlsx/CSV):
        Timestamp (UTC), Event Type, Classification, Result,
        User / Subject, Method, Source IP, Namespace,
        Object Type, Object Name, ...

    Returns a flat dict with clean string/numeric fields.
    """
    def safe(key, default="unknown"):
        v = raw.get(key, default)
        return str(v).strip() if v is not None else default

    ts_raw = raw.get("Timestamp (UTC)") or raw.get("ts") or raw.get("Invocation Time")
    try:
        if isinstance(ts_raw, datetime):
            ts = ts_raw.replace(tzinfo=timezone.utc) if ts_raw.tzinfo is None else ts_raw
        else:
            # Normalise both known variants before parsing:
            #   "2026-04-01T02:17:43+00:00"          (T-separator, Falco/real logs)
            #   "2026-04-01 02:17:43.123456+00:00"   (space-separator, pandas/synthetic)
            # Python < 3.11 fromisoformat() only accepts the T form, so we replace
            # the space separator and strip the trailing 'Z' in one pass.
            ts_str = (str(ts_raw)
                      .strip()
                      .replace("Z", "+00:00")
                      .replace(" ", "T", 1))   # only first space = date/time separator
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        ts = datetime.now(timezone.utc)

    result = safe("Result", "unknown").lower()
    is_failed = 0 if result == "success" else 1

    obj_type = safe("Object Type", "unknown").lower()
    is_sensitive = 1 if any(r in obj_type for r in SENSITIVE_RESOURCES) else 0

    method = safe("Method", "unknown").lower()

    return {
        "ts":           ts.isoformat(),
        "ts_dt":        ts,
        "user":         safe("User / Subject"),
        "source_ip":    safe("Source IP"),
        "namespace":    safe("Namespace"),
        "object_type":  obj_type,
        "method":       method,
        "event_type":   safe("Event Type"),
        "hour":         ts.hour,
        "day_of_week":  ts.weekday(),
        "is_failed":    is_failed,
        "is_sensitive": is_sensitive,
    }


def engineer_features(parsed: dict, user_hist: dict, ip_hist: dict) -> dict:
    """
    Build the full feature dict from:
      - parsed:     output of parse_raw_log()
      - user_hist:  output of feature_store.get_user_features()
      - ip_hist:    output of feature_store.get_ip_features()

    Returns a dict with keys matching FEATURE_COLS exactly.
    """
    hour = parsed["hour"]
    is_off_hours = 1 if (hour < 6 or hour > 20) else 0
    is_high_risk = 1 if parsed["method"] in HIGH_RISK_METHODS else 0

    feats = {
        # Hashed categoricals
        "feat_user_hash":           _hash_feature(parsed["user"],       HASH_BUCKETS["user"]),
        "feat_ip_hash":             _hash_feature(parsed["source_ip"],  HASH_BUCKETS["source_ip"]),
        "feat_namespace_hash":      _hash_feature(parsed["namespace"],  HASH_BUCKETS["namespace"]),
        "feat_object_type_hash":    _hash_feature(parsed["object_type"],HASH_BUCKETS["object_type"]),
        "feat_method_hash":         _hash_feature(parsed["method"],     HASH_BUCKETS["method"]),
        "feat_event_type_hash":     _hash_feature(parsed["event_type"], HASH_BUCKETS["event_type"]),

        # Temporal
        "feat_hour":                hour,
        "feat_day_of_week":         parsed["day_of_week"],
        "feat_is_off_hours":        is_off_hours,

        # Event flags
        "feat_is_sensitive":        parsed["is_sensitive"],
        "feat_is_failed":           parsed["is_failed"],
        "feat_is_high_risk_method": is_high_risk,
        "feat_sensitive_offhour":   parsed["is_sensitive"] * is_off_hours,

        # Historical user features
        "feat_hist_req_24h":             user_hist.get("hist_req_24h", 0),
        "feat_hist_req_7d":              user_hist.get("hist_req_7d",  0),
        "feat_hist_req_30d":             user_hist.get("hist_req_30d", 0),
        "feat_hist_fail_ratio_7d":       user_hist.get("hist_fail_ratio_7d", 0.0),
        "feat_hist_unique_namespaces":   user_hist.get("hist_unique_namespaces", 0),
        "feat_hist_unique_resources":    user_hist.get("hist_unique_resources",  0),
        "feat_hist_unique_ips":          user_hist.get("hist_unique_ips", 0),
        "feat_hist_sensitive_rate_7d":   user_hist.get("hist_sensitive_rate_7d", 0.0),
        "feat_hist_user_hour_baseline":  user_hist.get("hist_user_hour_baseline", 0),
        "feat_is_new_user":              user_hist.get("is_new_user", 1),

        # Historical IP features
        "feat_hist_ip_req_24h":          ip_hist.get("hist_ip_req_24h", 0),
        "feat_hist_ip_fail_ratio_24h":   ip_hist.get("hist_ip_fail_ratio_24h", 0.0),
        "feat_hist_ip_unique_users":     ip_hist.get("hist_ip_unique_users", 0),
        "feat_is_new_ip":                ip_hist.get("is_new_ip", 1),

        # Burst + RBAC
        "feat_fail_burst_5min":         ip_hist.get("hist_ip_fail_burst_5min", 0),
        "feat_is_rbac_resource":        1 if any(r in parsed["object_type"] for r in RBAC_RESOURCES) else 0,
    }

    # Sanity check: make sure no feature is missing
    missing = [c for c in FEATURE_COLS if c not in feats]
    if missing:
        raise RuntimeError(f"BUG: Missing features: {missing}")

    return feats


def features_to_vector(feat_dict: dict) -> list:
    """Return features as an ordered list matching FEATURE_COLS."""
    return [feat_dict[col] for col in FEATURE_COLS]


def generate_reason(parsed: dict, user_hist: dict, ip_hist: dict,
                    anomaly_score: float) -> str:
    """
    Human-readable explanation of WHY this event is suspicious.
    In a full system this is where you'd call SHAP to get the actual
    features that drove the Isolation Forest score. For now, rule-based
    over the features we computed.
    """
    reasons = []

    if parsed["is_sensitive"] and (parsed["hour"] < 6 or parsed["hour"] > 20):
        reasons.append(f"sensitive resource '{parsed['object_type']}' accessed outside business hours")

    if user_hist.get("is_new_user"):
        reasons.append("actor has NO activity history in the last 30 days")

    if ip_hist.get("is_new_ip"):
        reasons.append("source IP has never been seen before")

    req_24h = user_hist.get("hist_req_24h", 0)
    req_30d = user_hist.get("hist_req_30d", 0)
    daily_avg = req_30d / 30 if req_30d > 0 else 0
    if daily_avg > 0 and req_24h > daily_avg * 5:
        reasons.append(
            f"request burst: {req_24h} requests in 24h vs daily avg of {daily_avg:.0f}"
        )

    if user_hist.get("hist_fail_ratio_7d", 0) > 0.3:
        reasons.append(
            f"high failure rate: {user_hist['hist_fail_ratio_7d']*100:.0f}% of requests failing"
        )

    if parsed["method"] in HIGH_RISK_METHODS and parsed["is_sensitive"]:
        reasons.append(
            f"high-risk method '{parsed['method']}' on sensitive resource"
        )

    if ip_hist.get("hist_ip_unique_users", 0) > 10:
        reasons.append(
            f"source IP used by {ip_hist['hist_ip_unique_users']} different actors"
        )

    if not reasons:
        reasons.append("statistical outlier in learned behavior model")

    return "; ".join(reasons)
