"""
train_gru.py
------------
GRU-based sequential anomaly detector for K8s audit logs.

Why GRU on top of Isolation Forest?
  Isolation Forest scores each event independently — it sees ONE row.
  GRU sees a SEQUENCE of the last N events per user and learns
  temporal patterns: "this user always reads before writing",
  "secrets are never accessed after midnight by this account", etc.

Implementation: pure numpy with full analytical BPTT.
No torch/tensorflow required. Trains in ~1-3 minutes on 7k sequences.

Usage:
  python train_gru.py --data merged_logs.xlsx --out models/

Output:
  models/gru_v<timestamp>.pkl          — trained weights + scaler
  models/gru_meta_v<timestamp>.json    — metadata
  models/gru_latest.json               — pointer to current best model
"""

import os, json, argparse, sqlite3, pickle
from datetime import datetime, timezone
from collections import defaultdict

import numpy as np
import pandas as pd
import joblib
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, classification_report

SEQUENCE_LEN  = 20
HIDDEN_SIZE   = 64
N_EPOCHS      = 30
LEARNING_RATE = 0.005
BATCH_SIZE    = 64
MODEL_DIR     = os.environ.get("MODEL_DIR", "models")


# ─────────────────────────────────────────────────────────────────────────────
# Vectorized GRU with full BPTT
# All operations are batched: shapes are (batch, dim) throughout.
# ─────────────────────────────────────────────────────────────────────────────

def sigmoid(x):
    return np.where(x >= 0,
                    1 / (1 + np.exp(-x)),
                    np.exp(x) / (1 + np.exp(x)))

def sigmoid_grad(s):   return s * (1 - s)
def tanh_grad(t):      return 1 - t ** 2


class GRULayer:
    """Single GRU layer, vectorized over batch dimension."""

    def __init__(self, input_size, hidden_size):
        self.input_size  = input_size
        self.hidden_size = H = hidden_size

        # Xavier uniform init
        lim_ih = np.sqrt(6 / (input_size + H))
        lim_hh = np.sqrt(6 / (H + H))

        # [z, r, h] gates concatenated for efficiency
        self.Wih = np.random.uniform(-lim_ih, lim_ih, (3 * H, input_size))
        self.Whh = np.random.uniform(-lim_hh, lim_hh, (3 * H, H))
        self.b   = np.zeros(3 * H)

        # Adam optimizer state
        self.m = {k: np.zeros_like(v) for k, v in self._params().items()}
        self.v = {k: np.zeros_like(v) for k, v in self._params().items()}
        self.t = 0

    def _params(self):
        return {"Wih": self.Wih, "Whh": self.Whh, "b": self.b}

    def forward(self, x_seq):
        """
        x_seq: (batch, seq_len, input_size)
        Returns:
          h_all:  (batch, seq_len, hidden_size)  — all hidden states
          cache:  list of per-step dicts for BPTT
        """
        B, T, _ = x_seq.shape
        H = self.hidden_size
        h = np.zeros((B, H))
        h_all, cache = [], []

        for t in range(T):
            x = x_seq[:, t, :]                          # (B, input_size)
            gates = x @ self.Wih.T + h @ self.Whh.T + self.b  # (B, 3H)

            z = sigmoid(gates[:, :H])           # update gate  (B, H)
            r = sigmoid(gates[:, H:2*H])        # reset gate   (B, H)
            g = np.tanh(gates[:, 2*H:] + (r * h) @ self.Whh[2*H:].T
                        - h @ self.Whh[2*H:].T)  # candidate   (B, H)
            # More explicit candidate: recompute properly
            g_in   = gates[:, 2*H:]                      # linear input part
            rh     = r * h
            g_full = np.tanh(x @ self.Wih[2*H:].T + rh @ self.Whh[2*H:].T + self.b[2*H:])

            h_new = (1 - z) * h + z * g_full
            cache.append({"x": x, "h_prev": h, "z": z, "r": r,
                          "g": g_full, "rh": rh})
            h_all.append(h_new)
            h = h_new

        return np.stack(h_all, axis=1), cache   # (B, T, H)

    def backward(self, x_seq, cache, dh_all):
        """
        dh_all: (batch, seq_len, hidden_size)  — gradient from above
        Returns dx_seq and parameter gradients.
        """
        B, T, _ = x_seq.shape
        H = self.hidden_size

        dWih = np.zeros_like(self.Wih)
        dWhh = np.zeros_like(self.Whh)
        db   = np.zeros_like(self.b)
        dx_seq = np.zeros_like(x_seq)
        dh_next = np.zeros((B, H))

        for t in reversed(range(T)):
            c  = cache[t]
            dh = dh_all[:, t, :] + dh_next       # (B, H)

            # h_new = (1-z)*h_prev + z*g
            dz  = dh * (c["g"] - c["h_prev"])    # (B, H)
            dg  = dh * c["z"]                    # (B, H)
            dh_prev_from_h = dh * (1 - c["z"])  # (B, H)

            # g = tanh(Wih_g·x + Whh_g·(r*h_prev) + b_g)
            dg_pre = dg * tanh_grad(c["g"])      # (B, H)

            dWih[2*H:] += dg_pre.T @ c["x"]
            dWhh[2*H:] += dg_pre.T @ c["rh"]
            db[2*H:]   += dg_pre.sum(0)
            dx_from_g   = dg_pre @ self.Wih[2*H:]        # (B, input_size)
            drh         = dg_pre @ self.Whh[2*H:]        # (B, H)
            dr          = drh * c["h_prev"]
            dh_prev_from_g = drh * c["r"]

            # z gate: z = sigmoid(Wih_z·x + Whh_z·h_prev + b_z)
            dz_pre = dz * sigmoid_grad(c["z"])
            dWih[:H] += dz_pre.T @ c["x"]
            dWhh[:H] += dz_pre.T @ c["h_prev"]
            db[:H]   += dz_pre.sum(0)
            dx_from_z = dz_pre @ self.Wih[:H]
            dh_prev_from_z = dz_pre @ self.Whh[:H]

            # r gate: r = sigmoid(Wih_r·x + Whh_r·h_prev + b_r)
            dr_pre = dr * sigmoid_grad(c["r"])
            dWih[H:2*H] += dr_pre.T @ c["x"]
            dWhh[H:2*H] += dr_pre.T @ c["h_prev"]
            db[H:2*H]   += dr_pre.sum(0)
            dx_from_r = dr_pre @ self.Wih[H:2*H]
            dh_prev_from_r = dr_pre @ self.Whh[H:2*H]

            dx_seq[:, t, :] = dx_from_z + dx_from_r + dx_from_g
            dh_next = (dh_prev_from_h + dh_prev_from_z +
                       dh_prev_from_r + dh_prev_from_g)

        return dx_seq, {"Wih": dWih, "Whh": dWhh, "b": db}

    def adam_update(self, grads, lr=0.001, beta1=0.9, beta2=0.999, eps=1e-8):
        self.t += 1
        for k in self._params():
            self.m[k] = beta1 * self.m[k] + (1 - beta1) * grads[k]
            self.v[k] = beta2 * self.v[k] + (1 - beta2) * grads[k] ** 2
            m_hat = self.m[k] / (1 - beta1 ** self.t)
            v_hat = self.v[k] / (1 - beta2 ** self.t)
            self._params()[k] -= lr * m_hat / (np.sqrt(v_hat) + eps)
        # Apply in-place
        self.Wih -= 0   # params already updated via dict reference above


class GRUModel:
    """
    2-layer GRU → dense output → sigmoid.
    Input:  (batch, seq_len, input_size)
    Output: (batch,) anomaly probabilities
    """

    def __init__(self, input_size, hidden_size=64):
        self.gru1 = GRULayer(input_size,   hidden_size)
        self.gru2 = GRULayer(hidden_size,  hidden_size)
        H = hidden_size
        lim = np.sqrt(6 / H)
        self.W_out = np.random.uniform(-lim, lim, (H,))
        self.b_out = 0.0
        self.m_wo  = np.zeros(H);  self.v_wo = np.zeros(H)
        self.m_bo  = 0.0;          self.v_bo = 0.0
        self.t_out = 0

    def forward(self, x):
        """x: (B, T, F) → probs (B,), caches"""
        h1, c1 = self.gru1.forward(x)             # (B, T, H)
        h2, c2 = self.gru2.forward(h1)            # (B, T, H)
        last_h  = h2[:, -1, :]                    # (B, H)
        logits  = last_h @ self.W_out + self.b_out # (B,)
        probs   = sigmoid(logits)                  # (B,)
        return probs, (x, h1, c1, h2, c2, last_h)

    def backward(self, cache, probs, y, x_orig):
        x, h1, c1, h2, c2, last_h = cache
        B = len(y)

        # BCE loss gradient
        dp = (probs - y) / B                       # (B,)

        # Output layer gradients
        dW_out = last_h.T @ dp                     # (H,)
        db_out = dp.sum()
        d_last_h = np.outer(dp, self.W_out)        # (B, H)

        # Backprop through GRU2 — only last timestep has gradient
        dh2_all = np.zeros_like(h2)
        dh2_all[:, -1, :] = d_last_h
        dx2, g2 = self.gru2.backward(h1, c2, dh2_all)

        # Backprop through GRU1
        dh1_all = dx2
        dx1, g1 = self.gru1.backward(x_orig, c1, dh1_all)

        return g1, g2, dW_out, db_out

    def adam_update(self, g1, g2, dW_out, db_out, lr):
        self.gru1.adam_update(g1, lr)
        self.gru2.adam_update(g2, lr)

        # Output layer Adam
        b1, b2, eps = 0.9, 0.999, 1e-8
        self.t_out += 1
        self.m_wo = b1 * self.m_wo + (1 - b1) * dW_out
        self.v_wo = b2 * self.v_wo + (1 - b2) * dW_out ** 2
        mh = self.m_wo / (1 - b1 ** self.t_out)
        vh = self.v_wo / (1 - b2 ** self.t_out)
        self.W_out -= lr * mh / (np.sqrt(vh) + eps)

        self.m_bo = b1 * self.m_bo + (1 - b1) * db_out
        self.v_bo = b2 * self.v_bo + (1 - b2) * db_out ** 2
        mh2 = self.m_bo / (1 - b1 ** self.t_out)
        vh2 = self.v_bo / (1 - b2 ** self.t_out)
        self.b_out -= lr * mh2 / (np.sqrt(vh2) + eps)

    def fit(self, X_train, y_train, X_val=None, y_val=None,
            n_epochs=30, lr=0.005, batch_size=64):
        n = len(X_train)
        best_auc, best_state = 0.0, None

        for epoch in range(n_epochs):
            idx = np.random.permutation(n)
            epoch_loss = 0.0

            for start in range(0, n, batch_size):
                bi  = idx[start:start + batch_size]
                bx  = X_train[bi]
                by  = y_train[bi]

                probs, cache = self.forward(bx)
                # BCE loss
                eps = 1e-7
                loss = -np.mean(by * np.log(probs + eps) +
                                (1 - by) * np.log(1 - probs + eps))
                epoch_loss += loss

                g1, g2, dwo, dbo = self.backward(cache, probs, by, bx)
                self.adam_update(g1, g2, dwo, dbo, lr)

            # Validation
            if X_val is not None and len(X_val) > 0:
                val_probs, _ = self.forward(X_val)
                try:
                    auc = roc_auc_score(y_val, val_probs)
                except Exception:
                    auc = 0.0
                if auc > best_auc:
                    best_auc   = auc
                    best_state = pickle.dumps(self.__dict__.copy())

                if (epoch + 1) % 5 == 0 or epoch == 0:
                    n_batches = max(1, n // batch_size)
                    print(f"[gru]   Epoch {epoch+1:3d}/{n_epochs} | "
                          f"loss={epoch_loss/n_batches:.4f} | "
                          f"val_auc={auc:.4f}"
                          + (" ← best" if auc == best_auc else ""))
            else:
                if (epoch + 1) % 5 == 0:
                    n_batches = max(1, n // batch_size)
                    print(f"[gru]   Epoch {epoch+1:3d}/{n_epochs} | "
                          f"loss={epoch_loss/n_batches:.4f}")

        if best_state:
            self.__dict__.update(pickle.loads(best_state))
            print(f"[gru] Best val AUC {best_auc:.4f} — weights restored.")

    def predict_proba(self, X):
        probs, _ = self.forward(X)
        return probs

    def save(self, path):
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path):
        with open(path, "rb") as f:
            return pickle.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Data loading helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_if_features_from_db():
    """Re-derive IF features for every event in the feature store."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import feature_store as fs
    from feature_engineer import (
        parse_raw_log, engineer_features, features_to_vector
    )

    conn = sqlite3.connect(fs.DB_PATH)
    df   = pd.read_sql_query("SELECT * FROM events ORDER BY ts ASC", conn)
    conn.close()
    print(f"[gru] Loaded {len(df)} events from feature store.")

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
            user_hist = fs.get_user_features(parsed["user"],     parsed["ts_dt"])
            ip_hist   = fs.get_ip_features(parsed["source_ip"],  parsed["ts_dt"])
            feats     = engineer_features(parsed, user_hist, ip_hist)
            vec       = features_to_vector(feats)
        except Exception:
            vec = [0.0] * 27
        rows.append({"ts": row["ts"], "user": row["user"], "vec": vec})

    return rows


def build_sequences(rows, df_raw, seq_len=SEQUENCE_LEN):
    """
    Per-user sliding window sequences.
    Target = label of the LAST event in the window.
    Skips 'real_unknown' targets.
    """
    # Build label lookup: (user, ts[:19]) → label
    label_map = {}
    if "_label" in df_raw.columns:
        for _, row in df_raw.iterrows():
            ts = str(row.get("Invocation Time") or
                     row.get("Timestamp (UTC)", ""))[:19]
            user  = str(row.get("User / Subject", "unknown"))
            label = str(row.get("_label", "real_unknown"))
            label_map[(user, ts)] = label

    user_events = defaultdict(list)
    for r in rows:
        user_events[r["user"]].append(r)

    X, y, meta = [], [], []
    for user, events in user_events.items():
        events = sorted(events, key=lambda e: e["ts"])
        vecs   = np.array([e["vec"] for e in events], dtype=np.float32)

        for end in range(1, len(events) + 1):
            last  = events[end - 1]
            ts_key = last["ts"][:19]
            label_str = label_map.get((user, ts_key), "real_unknown")
            if label_str not in ("normal", "anomaly"):
                continue

            start  = max(0, end - seq_len)
            window = vecs[start:end]
            if len(window) < seq_len:
                pad    = np.zeros((seq_len - len(window), vecs.shape[1]),
                                  dtype=np.float32)
                window = np.vstack([pad, window])

            X.append(window)
            y.append(1 if label_str == "anomaly" else 0)
            meta.append({"user": user, "ts": last["ts"]})

    return (np.array(X, dtype=np.float32),
            np.array(y, dtype=np.float32),
            meta)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def train_gru(data_path, out_dir=MODEL_DIR, seq_len=SEQUENCE_LEN,
              hidden_size=HIDDEN_SIZE, n_epochs=N_EPOCHS, lr=LEARNING_RATE):

    os.makedirs(out_dir, exist_ok=True)
    np.random.seed(42)

    # 1. Features from feature store
    rows = load_if_features_from_db()

    # 2. Labels from raw xlsx
    print(f"[gru] Loading labels from {data_path}...")
    df_raw = pd.read_excel(data_path) if data_path.endswith(".xlsx") \
             else pd.read_csv(data_path)
    if "Invocation Time" in df_raw.columns:
        missing = df_raw["Timestamp (UTC)"].isna()
        df_raw.loc[missing, "Timestamp (UTC)"] = df_raw.loc[missing, "Invocation Time"]

    # 3. Build sequences
    print(f"[gru] Building sequences (window={seq_len})...")
    X, y, meta = build_sequences(rows, df_raw, seq_len=seq_len)
    if len(X) == 0:
        raise ValueError("No labeled sequences found. Check _label column.")
    print(f"[gru] {len(X)} sequences | shape {X.shape} | "
          f"anomaly rate {y.mean():.2%}")

    # 4. Scale
    B, T, F  = X.shape
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X.reshape(-1, F)).reshape(B, T, F).astype(np.float32)

    # 5. Chronological 80/20 split
    split    = int(B * 0.8)
    X_tr, X_val = X_scaled[:split], X_scaled[split:]
    y_tr, y_val = y[:split],        y[split:]
    print(f"[gru] Train: {len(X_tr)} | Val: {len(X_val)}")

    # 6. Train
    import time
    model = GRUModel(input_size=F, hidden_size=hidden_size)
    t0 = time.time()
    model.fit(X_tr, y_tr, X_val=X_val, y_val=y_val,
              n_epochs=n_epochs, lr=lr, batch_size=BATCH_SIZE)
    elapsed = time.time() - t0
    print(f"[gru] Training time: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # 7. Evaluate
    val_probs = model.predict_proba(X_val)
    val_preds = (val_probs >= 0.5).astype(int)
    try:
        auc = roc_auc_score(y_val, val_probs)
        print(f"\n[gru] Final val AUC-ROC: {auc:.4f}")
    except Exception:
        auc = None
    print(classification_report(y_val, val_preds,
                                 target_names=["normal", "anomaly"],
                                 zero_division=0))

    # 8. Save
    version      = datetime.now(timezone.utc).strftime("v%Y%m%d_%H%M%S")
    model_path   = os.path.join(out_dir, f"gru_{version}.pkl")
    scaler_path  = os.path.join(out_dir, f"gru_scaler_{version}.pkl")
    meta_path    = os.path.join(out_dir, f"gru_meta_{version}.json")
    latest_path  = os.path.join(out_dir, "gru_latest.json")

    model.save(model_path)
    joblib.dump(scaler, scaler_path)

    with open(meta_path, "w") as f:
        json.dump({
            "version":      version,
            "trained_at":   datetime.now(timezone.utc).isoformat(),
            "seq_len":      seq_len,
            "hidden_size":  hidden_size,
            "input_size":   F,
            "n_train":      int(len(X_tr)),
            "n_val":        int(len(X_val)),
            "val_auc":      float(auc) if auc else None,
            "model_file":   os.path.basename(model_path),
            "scaler_file":  os.path.basename(scaler_path),
        }, f, indent=2)

    with open(latest_path, "w") as f:
        json.dump({
            "version":    version,
            "model_file": os.path.basename(model_path),
            "scaler_file":os.path.basename(scaler_path),
            "meta_file":  os.path.basename(meta_path),
        }, f, indent=2)

    print(f"\n[gru] ✅ Saved: {model_path}")
    return version


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data",    required=True)
    p.add_argument("--out",     default=MODEL_DIR)
    p.add_argument("--seq_len", type=int,   default=SEQUENCE_LEN)
    p.add_argument("--hidden",  type=int,   default=HIDDEN_SIZE)
    p.add_argument("--epochs",  type=int,   default=N_EPOCHS)
    p.add_argument("--lr",      type=float, default=LEARNING_RATE)
    args = p.parse_args()

    train_gru(args.data, args.out, args.seq_len,
              args.hidden, args.epochs, args.lr)
