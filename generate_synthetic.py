"""
generate_synthetic.py
---------------------
Generates realistic synthetic Kubernetes audit logs for training.

Run:
  python generate_synthetic.py --out synthetic_logs.xlsx --rows 7000

Then merge with your real data and retrain:
  python train.py --data merged_logs.xlsx --out models/

Design philosophy:
  - 85% normal traffic (realistic service account patterns)
  - 15% anomalous across 7 distinct attack categories
  - Each anomaly type mirrors a real K8s attack pattern
  - Timestamps span 60 days so rolling window features are meaningful
  - Output schema exactly matches real_audit_800.xlsx columns
"""

import argparse
import random
import uuid
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)

# ─────────────────────────────────────────────────────────────────────────────
# Realistic cluster inhabitants
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNTS = [
    "system:serviceaccount:ecommerce:payment-svc",
    "system:serviceaccount:ecommerce:order-svc",
    "system:serviceaccount:ecommerce:inventory-svc",
    "system:serviceaccount:ecommerce:audit-service",
    "system:serviceaccount:kube-system:deployment-controller",
    "system:serviceaccount:kube-system:replicaset-controller",
    "system:serviceaccount:kube-system:node-controller",
    "system:serviceaccount:monitoring:prometheus",
    "system:serviceaccount:monitoring:grafana",
    "system:serviceaccount:logging:fluentd",
]

HUMAN_USERS = [
    "john.doe@company.com",
    "jane.smith@company.com",
    "devops-bot@company.com",
    "admin@company.com",
    "dev-lead@company.com",
]

NAMESPACES = ["ecommerce", "kube-system", "monitoring", "logging", "prod", "staging"]

# Normal resource access patterns per service account
NORMAL_PATTERNS = {
    "system:serviceaccount:ecommerce:payment-svc":    [("get", "configmap"), ("get", "secret"), ("list", "pod")],
    "system:serviceaccount:ecommerce:order-svc":      [("get", "configmap"), ("list", "deployment"), ("get", "pod")],
    "system:serviceaccount:ecommerce:inventory-svc":  [("get", "configmap"), ("list", "pod"), ("get", "service")],
    "system:serviceaccount:ecommerce:audit-service":  [("list", "event"), ("get", "pod"), ("create", "event")],
    "system:serviceaccount:kube-system:deployment-controller": [("update", "deployment"), ("get", "replicaset"), ("create", "replicaset")],
    "system:serviceaccount:kube-system:replicaset-controller": [("update", "replicaset"), ("create", "pod"), ("list", "pod")],
    "system:serviceaccount:kube-system:node-controller":       [("get", "node"), ("update", "node"), ("list", "pod")],
    "system:serviceaccount:monitoring:prometheus":    [("get", "pod"), ("list", "pod"), ("list", "node"), ("list", "service")],
    "system:serviceaccount:monitoring:grafana":       [("get", "configmap"), ("list", "pod")],
    "system:serviceaccount:logging:fluentd":          [("list", "pod"), ("get", "pod"), ("list", "node")],
    "john.doe@company.com":    [("get", "deployment"), ("list", "pod"), ("get", "service"), ("update", "configmap")],
    "jane.smith@company.com":  [("list", "deployment"), ("get", "pod"), ("create", "configmap")],
    "devops-bot@company.com":  [("update", "deployment"), ("create", "configmap"), ("get", "secret")],
    "admin@company.com":       [("get", "clusterrole"), ("list", "namespace"), ("get", "node")],
    "dev-lead@company.com":    [("list", "deployment"), ("get", "pod"), ("list", "service")],
}

NORMAL_IPS = {
    "system:serviceaccount:ecommerce:payment-svc":   "10.244.1.11",
    "system:serviceaccount:ecommerce:order-svc":     "10.244.1.12",
    "system:serviceaccount:ecommerce:inventory-svc": "10.244.1.13",
    "system:serviceaccount:ecommerce:audit-service": "10.244.2.21",
    "system:serviceaccount:kube-system:deployment-controller": "10.96.0.10",
    "system:serviceaccount:kube-system:replicaset-controller": "10.96.0.11",
    "system:serviceaccount:kube-system:node-controller":       "10.96.0.12",
    "system:serviceaccount:monitoring:prometheus":   "10.244.3.5",
    "system:serviceaccount:monitoring:grafana":      "10.244.3.6",
    "system:serviceaccount:logging:fluentd":         "10.244.4.2",
    "john.doe@company.com":   "192.168.1.101",
    "jane.smith@company.com": "192.168.1.102",
    "devops-bot@company.com": "192.168.1.103",
    "admin@company.com":      "192.168.1.104",
    "dev-lead@company.com":   "192.168.1.105",
}

ALL_ACTORS = list(SERVICE_ACCOUNTS) + list(HUMAN_USERS)


def _rand_ts(start: datetime, end: datetime) -> datetime:
    delta = (end - start).total_seconds()
    return start + timedelta(seconds=random.uniform(0, delta))


def _business_hours_ts(start: datetime, end: datetime) -> datetime:
    """Random timestamp guaranteed to fall within 08:00–18:00 on a weekday."""
    for _ in range(100):
        ts = _rand_ts(start, end)
        if ts.weekday() < 5 and 8 <= ts.hour < 18:
            return ts
    return ts  # fallback


def _off_hours_ts(start: datetime, end: datetime) -> datetime:
    """Random timestamp guaranteed to fall outside business hours."""
    for _ in range(100):
        ts = _rand_ts(start, end)
        if ts.hour < 6 or ts.hour > 22:
            return ts
    return ts


def _make_row(ts, actor, method, object_type, namespace,
              source_ip, result="Success", event_type="audit",
              classification="normal", label="normal") -> dict:
    """Build one log row in the exact schema of real_audit_800.xlsx."""
    return {
        "Timestamp (UTC)":    ts.isoformat(),
        "Time (IST)":         (ts + timedelta(hours=5, minutes=30)).strftime("%H:%M:%S"),
        "Event Type":         event_type,
        "Classification":     classification,
        "Result":             result,
        "Status Code":        200 if result == "Success" else 403,
        "Stage":              "ResponseComplete",
        "Severity":           "info" if result == "Success" else "warning",
        "Security Relevant":  "yes" if object_type in ("secret", "clusterrole", "rolebinding", "clusterrolebinding") else "no",
        "User / Subject":     actor,
        "Roles":              "cluster-admin" if "admin" in actor else "default",
        "Privileges":         "standard",
        "Method":             method,
        "Request URL":        f"/api/v1/namespaces/{namespace}/{object_type}s",
        "Source IP":          source_ip,
        "Requesting Service": actor.split(":")[-1] if "serviceaccount" in actor else actor,
        "Namespace":          namespace,
        "Object Type":        object_type,
        "Object Name":        f"{object_type}-{uuid.uuid4().hex[:6]}",
        "Access Result":      result,
        "Changes":            "",
        "Destination":        "kube-apiserver",
        "Dest Port":          6443,
        "Encryption":         1,
        "Event ID":           uuid.uuid4().hex[:12],
        "Source URN":         f"urn:k8s:cluster:prod-cluster-01",
        "Invocation Time":    ts.isoformat(),
        "Completion Time":    (ts + timedelta(milliseconds=random.randint(2, 80))).isoformat(),
        # Ground truth label — use this to measure precision/recall
        "_label":             label,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Normal traffic generator
# ─────────────────────────────────────────────────────────────────────────────

def gen_normal(n: int, start: datetime, end: datetime) -> list:
    rows = []
    for _ in range(n):
        actor = random.choice(ALL_ACTORS)
        method, obj = random.choice(NORMAL_PATTERNS[actor])
        ns = random.choice(NAMESPACES[:3])  # normal actors stay in their namespaces
        ip = NORMAL_IPS[actor]
        ts = _business_hours_ts(start, end) if random.random() < 0.85 else _rand_ts(start, end)
        rows.append(_make_row(ts, actor, method, obj, ns, ip, label="normal"))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly generators — each mirrors a real attack pattern
# ─────────────────────────────────────────────────────────────────────────────

def gen_secret_mass_read(start: datetime, end: datetime) -> list:
    """
    Attack: Credential harvesting via bulk secret reads.
    Pattern: 1 actor, list/get secrets, 300-800 calls in a 3-minute window.
    Real example: compromised pipeline exfiltrating all secrets.
    """
    rows = []
    # Pick a compromised service account
    actor = random.choice(SERVICE_ACCOUNTS[:5])
    ip = NORMAL_IPS[actor]  # same IP — not IP-based anomaly, purely behavioral
    # Pick a time window (off hours, harder to detect)
    anchor = _off_hours_ts(start, end)
    n_calls = random.randint(300, 800)
    for i in range(n_calls):
        ts = anchor + timedelta(seconds=random.uniform(0, 180))  # 3-minute burst
        ns = random.choice(NAMESPACES)  # crosses namespaces
        rows.append(_make_row(ts, actor, "list", "secret", ns, ip,
                              classification="secret_mass_read", label="anomaly"))
    return rows


def gen_rbac_escalation(start: datetime, end: datetime) -> list:
    """
    Attack: Privilege escalation via RBAC.
    Pattern: create clusterrolebinding granting cluster-admin,
             done by a human user outside business hours.
    """
    rows = []
    actor = random.choice(HUMAN_USERS)
    ip = NORMAL_IPS[actor]
    ts = _off_hours_ts(start, end)

    # The escalation event itself
    rows.append(_make_row(
        ts, actor, "create", "clusterrolebinding", "kube-system", ip,
        classification="rbac_escalation", label="anomaly"
    ))
    # A few supporting events (checking existing roles first — recon)
    for _ in range(random.randint(3, 8)):
        t2 = ts - timedelta(minutes=random.randint(1, 15))
        rows.append(_make_row(
            t2, actor, "get", "clusterrole", "kube-system", ip,
            classification="rbac_escalation", label="anomaly"
        ))
    return rows


def gen_cross_namespace_secret_access(start: datetime, end: datetime) -> list:
    """
    Attack: Service reads secrets from a namespace it has never accessed.
    Pattern: frontend service reads DB credentials from prod namespace.
    """
    rows = []
    # frontend service accessing prod secrets — wrong namespace for it
    actor = "system:serviceaccount:ecommerce:audit-service"
    ip = NORMAL_IPS[actor]
    n = random.randint(5, 20)
    anchor = _rand_ts(start, end)
    for i in range(n):
        ts = anchor + timedelta(minutes=i * 2)
        rows.append(_make_row(
            ts, actor, "get", "secret", "prod", ip,
            classification="cross_namespace_secret", label="anomaly"
        ))
    return rows


def gen_exec_into_pod(start: datetime, end: datetime) -> list:
    """
    Attack: Interactive shell access to production pod.
    Pattern: same human user, pods/exec, 10-20 times in 2 hours.
    Red flag: no change ticket, interactive access in prod.
    """
    rows = []
    actor = random.choice(HUMAN_USERS)
    ip = NORMAL_IPS[actor]
    anchor = _rand_ts(start, end)
    n = random.randint(10, 20)
    for i in range(n):
        ts = anchor + timedelta(minutes=random.randint(0, 120))
        rows.append(_make_row(
            ts, actor, "create", "pods/exec", "prod", ip,
            classification="pod_exec_abuse", label="anomaly"
        ))
    return rows


def gen_new_ip_known_user(start: datetime, end: datetime) -> list:
    """
    Attack: Known service account connecting from an unexpected IP.
    Could be: compromised node, lateral movement, credential theft.
    """
    rows = []
    actor = random.choice(SERVICE_ACCOUNTS)
    # Use a completely different IP from the actor's normal one
    rogue_ip = f"192.168.99.{random.randint(1, 254)}"
    anchor = _rand_ts(start, end)
    n = random.randint(5, 30)
    for i in range(n):
        ts = anchor + timedelta(minutes=i)
        method, obj = random.choice(NORMAL_PATTERNS[actor])
        ns = random.choice(NAMESPACES)
        rows.append(_make_row(
            ts, actor, method, obj, ns, rogue_ip,
            classification="new_ip_known_actor", label="anomaly"
        ))
    return rows


def gen_human_modifying_workloads(start: datetime, end: datetime) -> list:
    """
    Attack/Policy violation: Human user directly modifying deployments/pods.
    These should be done by CI/CD automation, not humans.
    Your mentor explicitly called this out as a use case.
    """
    rows = []
    actor = random.choice(HUMAN_USERS)
    ip = NORMAL_IPS[actor]
    anchor = _rand_ts(start, end)
    workload_resources = ["deployment", "replicaset", "statefulset", "daemonset", "pod"]
    n = random.randint(3, 12)
    for i in range(n):
        ts = anchor + timedelta(minutes=random.randint(0, 30))
        resource = random.choice(workload_resources)
        method = random.choice(["create", "update", "patch", "delete"])
        rows.append(_make_row(
            ts, actor, method, resource, random.choice(["prod", "staging"]), ip,
            classification="human_workload_modification", label="anomaly"
        ))
    return rows


def gen_failed_access_spike(start: datetime, end: datetime) -> list:
    """
    Attack: Reconnaissance / scanning.
    Pattern: burst of 403 Forbidden from unknown IP.
    """
    rows = []
    unknown_ip = f"203.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    actor = random.choice(SERVICE_ACCOUNTS)  # spoofed identity
    anchor = _rand_ts(start, end)
    n = random.randint(30, 100)
    for i in range(n):
        ts = anchor + timedelta(seconds=random.randint(0, 300))
        resource = random.choice(["secret", "configmap", "pod", "deployment"])
        rows.append(_make_row(
            ts, actor, "get", resource, random.choice(NAMESPACES), unknown_ip,
            result="Failure",
            classification="failed_access_spike", label="anomaly"
        ))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────────────────────────────────────────

ANOMALY_GENERATORS = [
    ("secret_mass_read",             gen_secret_mass_read,             0.20),
    ("rbac_escalation",              gen_rbac_escalation,              0.15),
    ("cross_namespace_secret",       gen_cross_namespace_secret_access,0.15),
    ("pod_exec_abuse",               gen_exec_into_pod,                0.15),
    ("new_ip_known_actor",           gen_new_ip_known_user,            0.15),
    ("human_workload_modification",  gen_human_modifying_workloads,    0.10),
    ("failed_access_spike",          gen_failed_access_spike,          0.10),
]


def generate(total_rows: int = 7000, anomaly_fraction: float = 0.15,
             days: int = 60) -> pd.DataFrame:
    """
    Generate a synthetic dataset.

    Args:
      total_rows:       Total number of log events to generate
      anomaly_fraction: Fraction that should be anomalous (default 15%)
      days:             How many days of history to span (default 60)

    Returns:
      DataFrame with same columns as real_audit_800.xlsx + _label column
    """
    end   = datetime(2026, 4, 22, 23, 59, 59, tzinfo=timezone.utc)
    start = end - timedelta(days=days)

    n_anomaly = int(total_rows * anomaly_fraction)
    n_normal  = total_rows - n_anomaly

    print(f"[generate] Generating {n_normal} normal + {n_anomaly} anomalous events "
          f"spanning {days} days ({start.date()} → {end.date()})")

    rows = []

    # ── Normal traffic ────────────────────────────────────────────────────
    rows.extend(gen_normal(n_normal, start, end))
    print(f"[generate] Normal events done: {n_normal}")

    # ── Anomalous traffic ─────────────────────────────────────────────────
    anomaly_rows = []
    weights = [w for _, _, w in ANOMALY_GENERATORS]
    total_w = sum(weights)
    for name, fn, weight in ANOMALY_GENERATORS:
        n_this = int(n_anomaly * (weight / total_w))
        # Each generator produces a "burst" (one incident = many rows).
        # We call it multiple times until we hit the quota, then stop.
        # We also cap at 2× the quota so one burst-heavy generator
        # (like secret_mass_read with 800 calls) doesn't dominate.
        generated = 0
        safety = 0
        while generated < n_this and safety < 50:
            batch = fn(start, end)
            # Only take as many rows as needed to hit the quota
            remaining = n_this - generated
            anomaly_rows.extend(batch[:remaining])
            generated += min(len(batch), remaining)
            safety += 1
        print(f"[generate]   {name}: {generated} events")

    rows.extend(anomaly_rows)

    # ── Build DataFrame and sort chronologically ───────────────────────────
    df = pd.DataFrame(rows)
    df["Timestamp (UTC)"] = pd.to_datetime(df["Timestamp (UTC)"], utc=True)
    df = df.sort_values("Timestamp (UTC)").reset_index(drop=True)

    n_actual_anomaly = (df["_label"] == "anomaly").sum()
    n_actual_normal  = (df["_label"] == "normal").sum()
    print(f"\n[generate] Final dataset: {len(df)} rows")
    print(f"           Normal:   {n_actual_normal} ({n_actual_normal/len(df)*100:.1f}%)")
    print(f"           Anomaly:  {n_actual_anomaly} ({n_actual_anomaly/len(df)*100:.1f}%)")
    print(f"           Unique actors: {df['User / Subject'].nunique()}")
    print(f"           Anomaly breakdown:")
    for t in df[df["_label"] == "anomaly"]["Classification"].value_counts().items():
        print(f"             {t[0]}: {t[1]}")

    return df


def save(df: pd.DataFrame, out_path: str):
    """Save to xlsx (matching real data format) or csv."""
    # Convert timestamps back to strings for Excel compatibility
    df["Timestamp (UTC)"] = df["Timestamp (UTC)"].dt.strftime("%Y-%m-%d %H:%M:%S.%f+00:00")

    if out_path.endswith(".xlsx"):
        df.to_excel(out_path, index=False)
    else:
        df.to_csv(out_path, index=False)
    print(f"[generate] Saved to {out_path}")


def merge_with_real(synthetic_path: str, real_path: str, out_path: str):
    """
    Merge synthetic data with your real dataset for training.
    The _label column is preserved — real data gets label='real_unknown'.
    """
    if real_path.endswith(".xlsx"):
        df_real = pd.read_excel(real_path)
    else:
        df_real = pd.read_csv(real_path)

    df_real["_label"] = "real_unknown"

    if synthetic_path.endswith(".xlsx"):
        df_syn = pd.read_excel(synthetic_path)
    else:
        df_syn = pd.read_csv(synthetic_path)

    df_merged = pd.concat([df_real, df_syn], ignore_index=True)
    df_merged["Timestamp (UTC)"] = pd.to_datetime(df_merged["Timestamp (UTC)"], utc=True, errors="coerce")
    df_merged = df_merged.sort_values("Timestamp (UTC)").reset_index(drop=True)

    if out_path.endswith(".xlsx"):
        df_merged["Timestamp (UTC)"] = df_merged["Timestamp (UTC)"].dt.strftime("%Y-%m-%d %H:%M:%S.%f+00:00")
        df_merged.to_excel(out_path, index=False)
    else:
        df_merged.to_csv(out_path, index=False)

    print(f"[merge] Real: {len(df_real)} | Synthetic: {len(df_syn)} | "
          f"Merged: {len(df_merged)} → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic K8s audit logs")
    parser.add_argument("--out",      default="synthetic_logs.xlsx",
                        help="Output file path (.xlsx or .csv)")
    parser.add_argument("--rows",     type=int, default=7000,
                        help="Total rows to generate (default: 7000)")
    parser.add_argument("--anomaly",  type=float, default=0.15,
                        help="Fraction of anomalous rows (default: 0.15)")
    parser.add_argument("--days",     type=int, default=60,
                        help="Days of history to span (default: 60)")
    parser.add_argument("--merge",    default=None,
                        help="Real data file to merge with (optional)")
    parser.add_argument("--merge-out", default="merged_logs.xlsx",
                        help="Output path for merged file (default: merged_logs.xlsx)")
    args = parser.parse_args()

    df = generate(total_rows=args.rows, anomaly_fraction=args.anomaly, days=args.days)
    save(df, args.out)

    if args.merge:
        merge_with_real(args.out, args.merge, args.merge_out)
        print(f"\nNext steps:")
        print(f"  1. Delete your old feature_store.db (it has the old 800 rows)")
        print(f"  2. python train.py --data {args.merge_out} --out models/")
        print(f"  3. uvicorn main:app --reload")
    else:
        print(f"\nNext steps:")
        print(f"  1. Delete your old feature_store.db")
        print(f"  2. python train.py --data {args.out} --out models/")
        print(f"  3. Or merge first: python generate_synthetic.py --out {args.out} "
              f"--merge real_audit_800.xlsx --merge-out merged_logs.xlsx")
