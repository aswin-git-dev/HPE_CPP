"""
feature_store.py
----------------
Stateful per-user/IP behavioral profiles using rolling time windows.

Why this exists:
  Your original code computed user_request_count on the ENTIRE batch being
  scored. That means row 1 already "knows" about row 800. In production you
  never have future rows, so those counts were meaningless. This module
  maintains a persistent historical state so every feature is computed only
  from events that happened BEFORE the current one.

Storage backend: SQLite (swap for Redis in production with minimal changes).
"""

import sqlite3
import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional
from thresholds import THRESHOLD_HIGH, THRESHOLD_MEDIUM, THRESHOLD_LOW

DB_PATH = os.environ.get("FEATURE_STORE_PATH", "feature_store.db")

# How far back to look when computing rolling features
WINDOW_24H = timedelta(hours=24)
WINDOW_7D  = timedelta(days=7)
WINDOW_30D = timedelta(days=30)


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Call once on startup."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL,          -- ISO8601 UTC
            user            TEXT NOT NULL,
            source_ip       TEXT NOT NULL,
            namespace       TEXT NOT NULL,
            object_type     TEXT NOT NULL,
            method          TEXT NOT NULL,
            is_failed       INTEGER NOT NULL,       -- 0 or 1
            is_sensitive    INTEGER NOT NULL,       -- 0 or 1
            hour            INTEGER NOT NULL,
            anomaly_score   REAL,                   -- filled after inference
            analyst_label   INTEGER,                -- NULL=unreviewed, 0=normal, 1=anomaly
            model_version   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_user_ts ON events(user, ts);
        CREATE INDEX IF NOT EXISTS idx_events_ip_ts   ON events(source_ip, ts);
        CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(ts);
    """)
    conn.commit()
    conn.close()


def record_event(event: dict, anomaly_score: Optional[float] = None,
                 model_version: Optional[str] = None):
    """
    Persist a raw log event into the feature store AFTER scoring.
    Call this after inference so the current event does not contaminate
    its own features (we look up features BEFORE inserting).
    """
    conn = _get_conn()
    conn.execute("""
        INSERT INTO events
            (ts, user, source_ip, namespace, object_type, method,
             is_failed, is_sensitive, hour, anomaly_score, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event["ts"],
        event["user"],
        event["source_ip"],
        event["namespace"],
        event["object_type"],
        event["method"],
        event["is_failed"],
        event["is_sensitive"],
        event["hour"],
        anomaly_score,
        model_version,
    ))
    conn.commit()
    conn.close()


def get_user_features(user: str, now: datetime) -> dict:
    """
    Return rolling-window behavioral statistics for a user,
    computed from events BEFORE `now`. 
    Returns zero-valued defaults for unseen users (never crashes).
    """
    conn = _get_conn()

    cutoff_24h = (now - WINDOW_24H).isoformat()
    cutoff_7d  = (now - WINDOW_7D).isoformat()
    cutoff_30d = (now - WINDOW_30D).isoformat()
    now_str    = now.isoformat()

    # Total requests in each window
    def count_in_window(cutoff):
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE user=? AND ts>=? AND ts<?",
            (user, cutoff, now_str)
        ).fetchone()
        return row[0] if row else 0

    req_24h = count_in_window(cutoff_24h)
    req_7d  = count_in_window(cutoff_7d)
    req_30d = count_in_window(cutoff_30d)

    # Failure rate over 7 days
    fail_row = conn.execute("""
        SELECT AVG(is_failed) FROM events
        WHERE user=? AND ts>=? AND ts<?
    """, (user, cutoff_7d, now_str)).fetchone()
    fail_ratio_7d = fail_row[0] if fail_row and fail_row[0] is not None else 0.0

    # Unique namespaces, object types, IPs over 30 days
    def distinct_in_window(col, cutoff):
        row = conn.execute(
            f"SELECT COUNT(DISTINCT {col}) FROM events WHERE user=? AND ts>=? AND ts<?",
            (user, cutoff, now_str)
        ).fetchone()
        return row[0] if row else 0

    unique_namespaces  = distinct_in_window("namespace",    cutoff_30d)
    unique_resources   = distinct_in_window("object_type",  cutoff_30d)
    unique_ips         = distinct_in_window("source_ip",    cutoff_30d)

    # Sensitive access rate over 7 days
    sens_row = conn.execute("""
        SELECT AVG(is_sensitive) FROM events
        WHERE user=? AND ts>=? AND ts<?
    """, (user, cutoff_7d, now_str)).fetchone()
    sensitive_rate_7d = sens_row[0] if sens_row and sens_row[0] is not None else 0.0

    # Requests in same hour bucket over 30 days (baseline hourly rate)
    # This tells us: how often does this user normally act at THIS hour?
    # Helps detect off-hours anomalies per-user, not just globally.
    now_hour = now.hour
    hour_row = conn.execute("""
        SELECT COUNT(*) FROM events
        WHERE user=? AND hour=? AND ts>=? AND ts<?
    """, (user, now_hour, cutoff_30d, now_str)).fetchone()
    user_hour_baseline = hour_row[0] if hour_row else 0

    conn.close()

    return {
        "hist_req_24h":          req_24h,
        "hist_req_7d":           req_7d,
        "hist_req_30d":          req_30d,
        "hist_fail_ratio_7d":    round(fail_ratio_7d, 4),
        "hist_unique_namespaces": unique_namespaces,
        "hist_unique_resources":  unique_resources,
        "hist_unique_ips":        unique_ips,
        "hist_sensitive_rate_7d": round(sensitive_rate_7d, 4),
        "hist_user_hour_baseline": user_hour_baseline,
        # Is this user completely new? Critical flag.
        "is_new_user":           1 if req_30d == 0 else 0,
    }


def get_ip_features(source_ip: str, now: datetime) -> dict:
    """Rolling stats for a source IP address."""
    conn = _get_conn()
    cutoff_24h = (now - WINDOW_24H).isoformat()
    now_str    = now.isoformat()

    row = conn.execute("""
        SELECT COUNT(*), AVG(is_failed), COUNT(DISTINCT user)
        FROM events WHERE source_ip=? AND ts>=? AND ts<?
    """, (source_ip, cutoff_24h, now_str)).fetchone()

    # 5-minute failure burst — query BEFORE closing connection
    cutoff_5min = (now - timedelta(minutes=5)).isoformat()
    burst_row = conn.execute(
        "SELECT COUNT(*) FROM events WHERE source_ip=? AND ts>=? AND ts<? AND is_failed=1",
        (source_ip, cutoff_5min, now_str)
    ).fetchone()
    fail_burst_5min = burst_row[0] if burst_row else 0

    conn.close()  # single close at end, after ALL queries

    if not row or row[0] == 0:
        return {
            "hist_ip_req_24h":          0,
            "hist_ip_fail_ratio_24h":   0.0,
            "hist_ip_unique_users":     0,
            "is_new_ip":                1,
            "hist_ip_fail_burst_5min":  fail_burst_5min,
        }

    return {
        "hist_ip_req_24h":          row[0],
        "hist_ip_fail_ratio_24h":   round(row[1] or 0.0, 4),
        "hist_ip_unique_users":     row[2],
        "is_new_ip":                0,
        "hist_ip_fail_burst_5min":  fail_burst_5min,
    }


def bulk_load_history(df_path: str):
    """
    One-time import of historical CSV/XLSX into the feature store.
    Run this ONCE when bootstrapping from your existing scored_logs.csv.
    After that, record_event() maintains the store in real time.
    
    Usage:
        python -c "from feature_store import init_db, bulk_load_history; init_db(); bulk_load_history('scored_logs.csv')"
    """
    import pandas as pd

    if df_path.endswith(".xlsx"):
        df = pd.read_excel(df_path)
    else:
        df = pd.read_csv(df_path)

    df["Timestamp (UTC)"] = pd.to_datetime(df["Timestamp (UTC)"], utc=True, errors="coerce")
    df = df.dropna(subset=["Timestamp (UTC)"])
    df = df.sort_values("Timestamp (UTC)")

    sensitive_resources = {"secret", "configmap", "clusterrole", "rolebinding"}

    conn = _get_conn()
    rows = []
    for _, row in df.iterrows():
        obj = str(row.get("Object Type", "unknown")).lower()
        is_sensitive = 1 if any(r in obj for r in sensitive_resources) else 0
        is_failed = 1 if str(row.get("Result", "")).lower() != "success" else 0
        ts = row["Timestamp (UTC)"].isoformat()
        hour = row["Timestamp (UTC)"].hour

        rows.append((
            ts,
            str(row.get("User / Subject", "unknown")),
            str(row.get("Source IP", "unknown")),
            str(row.get("Namespace", "unknown")),
            str(row.get("Object Type", "unknown")),
            str(row.get("Method", "unknown")),
            is_failed,
            is_sensitive,
            hour,
            row.get("anomaly_score", None),
            row.get("model_version", None),
        ))

    conn.executemany("""
        INSERT INTO events
            (ts, user, source_ip, namespace, object_type, method,
             is_failed, is_sensitive, hour, anomaly_score, model_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    conn.close()
    print(f"[feature_store] Loaded {len(rows)} historical events into {DB_PATH}")


def get_recent_logs(limit: int = 200, risk_level: str = None) -> list:
    """Fetch recent logs for the dashboard / digest."""
    conn = _get_conn()
    if risk_level:
        # We store anomaly_score; compute risk_level on the fly
        score_threshold = {"HIGH": THRESHOLD_HIGH, "MEDIUM": THRESHOLD_MEDIUM, "LOW": THRESHOLD_LOW}.get(risk_level.upper(), 0.0)
        rows = conn.execute("""
            SELECT * FROM events
            WHERE anomaly_score >= ?
            ORDER BY ts DESC LIMIT ?
        """, (score_threshold, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_analyst_label(event_id: int, label: int):
    """
    Analyst marks an event as 0=normal or 1=confirmed anomaly.
    These labeled events are used to validate model performance
    and trigger retraining when enough labels accumulate.
    """
    conn = _get_conn()
    conn.execute(
        "UPDATE events SET analyst_label=? WHERE id=?", (label, event_id)
    )
    conn.commit()
    conn.close()


def get_label_counts():
    """How many events have been analyst-labeled? Used to trigger retraining."""
    conn = _get_conn()
    row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN analyst_label IS NOT NULL THEN 1 ELSE 0 END) as labeled,
            SUM(CASE WHEN analyst_label=1 THEN 1 ELSE 0 END) as confirmed_anomalies
        FROM events
    """).fetchone()
    conn.close()
    return dict(row)