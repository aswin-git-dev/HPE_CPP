"""
spot_threshold.py
-----------------
SPOT (Streaming Peaks-Over-Threshold) dynamic threshold for anomaly scores.

Theory:
  Extreme Value Theory (EVT) tells us that the tail of any distribution,
  regardless of its shape, converges to a Generalised Pareto Distribution (GPD).
  SPOT uses this property to find where the "normal" score distribution ends
  and the anomalous tail begins — automatically, from your own data.

How it works:
  1. Collect an initial batch of scores (warmup period).
  2. Set an initial tail threshold t = 97th percentile of warmup scores.
  3. Extract "exceedances" — scores that exceeded t (the tail).
  4. Fit a GPD to those exceedances using Maximum Likelihood Estimation.
  5. Compute the final threshold z such that P(score > z) = target_probability.
  6. As new scores arrive, update incrementally.

Why better than fixed thresholds:
  - Fixed HIGH=0.9 was chosen on training data. Your real cluster may produce
    scores that cluster differently — especially after retraining or adding
    new microservices.
  - SPOT adapts to whatever score distribution your models actually produce.
  - If your cluster gets busier and scores drift upward, SPOT raises the
    threshold automatically rather than flooding you with false positives.

Reference: Siffer et al., "Anomaly Detection in Streams with Extreme Value Theory"
           KDD 2017. https://dl.acm.org/doi/10.1145/3097983.3098144
"""

import os
import json
import numpy as np
from collections import deque
from datetime import datetime, timezone
from typing import Optional
from thresholds import THRESHOLD_HIGH, THRESHOLD_MEDIUM

# Path where SPOT state is persisted across restarts
SPOT_STATE_PATH = os.environ.get("SPOT_STATE_PATH", "models/spot_state.json")

# ── SPOT hyperparameters ──────────────────────────────────────────────────────
# WARMUP_SIZE: how many scores to collect before SPOT computes its first
#   threshold. Needs enough scores to see the full normal distribution.
#   With ~100-200 events/min in your cluster, 1000 = ~5-10 minutes.
WARMUP_SIZE = 1000

# TAIL_QUANTILE: the initial split between "normal body" and "tail" of the
#   score distribution. 0.97 means the bottom 97% of scores form the normal
#   body; the top 3% are the tail that SPOT fits a GPD to.
#   Lower = more sensitive (more alerts). Higher = less sensitive (fewer alerts).
TAIL_QUANTILE = 0.97

# TARGET_PROBABILITY: the false positive rate SPOT targets.
#   1e-4 means: "flag an event only if the probability of seeing a score
#   this high by chance (given normal behaviour) is less than 0.01%."
#   For a cluster generating 150,000 events/day, this means ~15 alerts/day.
#   Increase to 1e-3 for more alerts, decrease to 1e-5 for fewer.
TARGET_PROBABILITY = 1e-4

# MEDIUM_QUANTILE: MEDIUM risk threshold — less extreme than HIGH.
#   Set at the 90th percentile of the score distribution.
MEDIUM_QUANTILE = 0.90

# UPDATE_EVERY: recompute GPD fit every N new scores to avoid doing expensive
#   MLE on every single event. 100 = recompute ~once per minute.
UPDATE_EVERY = 100

# HISTORY_WINDOW: how many recent scores to keep for incremental updates.
#   Older scores become less relevant as cluster behaviour evolves.
HISTORY_WINDOW = 10_000


class SPOTThreshold:
    """
    Online SPOT algorithm for dynamic anomaly score thresholding.

    Usage:
        spot = SPOTThreshold()
        spot.update(score)           # feed each new score in
        threshold = spot.high        # current HIGH threshold
        risk = spot.classify(score)  # "HIGH" / "MEDIUM" / "LOW"
    """

    def __init__(self,
                 warmup_size: int = WARMUP_SIZE,
                 tail_quantile: float = TAIL_QUANTILE,
                 target_prob: float = TARGET_PROBABILITY,
                 medium_quantile: float = MEDIUM_QUANTILE,
                 update_every: int = UPDATE_EVERY):

        self.warmup_size     = warmup_size
        self.tail_quantile   = tail_quantile
        self.target_prob     = target_prob
        self.medium_quantile = medium_quantile
        self.update_every    = update_every

        # Circular buffer of recent scores
        self._history = deque(maxlen=HISTORY_WINDOW)

        # Current computed thresholds (fallback to fixed until SPOT warms up)
        self._threshold_high   = THRESHOLD_HIGH    # fallback: your original fixed value
        self._threshold_medium = THRESHOLD_MEDIUM   # fallback: your original fixed value
        self._t                = None  # tail split point (97th percentile)

        # State tracking
        self._n_total      = 0   # total scores seen ever
        self._n_since_fit  = 0   # scores seen since last GPD fit
        self._warmed_up    = False
        self._last_fit_at  = None

    # ── Public interface ──────────────────────────────────────────────────

    @property
    def high(self) -> float:
        """Current HIGH risk threshold."""
        return self._threshold_high

    @property
    def medium(self) -> float:
        """Current MEDIUM risk threshold."""
        return self._threshold_medium

    @property
    def warmed_up(self) -> bool:
        return self._warmed_up

    @property
    def n_total(self) -> int:
        return self._n_total

    def update(self, score: float):
        """
        Feed a new anomaly score into SPOT.
        Call this for EVERY scored event, including normal ones.
        SPOT needs the full distribution, not just the anomalies.
        """
        self._history.append(float(score))
        self._n_total     += 1
        self._n_since_fit += 1

        # Warmup phase: collect initial scores, then fit for the first time
        if not self._warmed_up:
            if self._n_total >= self.warmup_size:
                self._fit_gpd()
                self._warmed_up = True
                print(f"[SPOT] Warmed up after {self._n_total} scores. "
                      f"HIGH={self._threshold_high:.4f}, "
                      f"MEDIUM={self._threshold_medium:.4f}")
            return  # don't fit during warmup

        # Incremental update: refit every UPDATE_EVERY new scores
        if self._n_since_fit >= self.update_every:
            self._fit_gpd()

    def classify(self, score: float) -> str:
        """
        Classify a score as HIGH / MEDIUM / LOW using current SPOT thresholds.
        Falls back to fixed thresholds during warmup.
        """
        if score > self._threshold_high:
            return "HIGH"
        if score > self._threshold_medium:
            return "MEDIUM"
        return "LOW"

    def status(self) -> dict:
        """Return current SPOT state — useful for /health and /model endpoints."""
        return {
            "warmed_up":        self._warmed_up,
            "n_total":          self._n_total,
            "threshold_high":   round(self._threshold_high, 4),
            "threshold_medium": round(self._threshold_medium, 4),
            "tail_split_t":     round(self._t, 4) if self._t else None,
            "last_fit_at":      self._last_fit_at,
            "history_size":     len(self._history),
            "mode":             "SPOT (dynamic)" if self._warmed_up
                                else f"fixed (warming up: "
                                     f"{self._n_total}/{self.warmup_size})",
        }

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self, path: str = SPOT_STATE_PATH):
        """Persist SPOT state so thresholds survive a server restart."""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        state = {
            "n_total":          self._n_total,
            "threshold_high":   self._threshold_high,
            "threshold_medium": self._threshold_medium,
            "t":                self._t,
            "warmed_up":        self._warmed_up,
            "last_fit_at":      self._last_fit_at,
            # Save recent history so the next startup doesn't start cold
            "history":          list(self._history)[-5000:],
        }
        with open(path, "w") as f:
            json.dump(state, f, indent=2)

    def load(self, path: str = SPOT_STATE_PATH) -> bool:
        """Load persisted SPOT state. Returns True if loaded successfully."""
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                state = json.load(f)
            self._n_total          = state["n_total"]
            self._threshold_high   = state["threshold_high"]
            self._threshold_medium = state["threshold_medium"]
            self._t                = state["t"]
            self._warmed_up        = state["warmed_up"]
            self._last_fit_at      = state.get("last_fit_at")
            for s in state.get("history", []):
                self._history.append(s)
            print(f"[SPOT] Loaded state: HIGH={self._threshold_high:.4f}, "
                  f"MEDIUM={self._threshold_medium:.4f}, "
                  f"n_total={self._n_total}")
            return True
        except Exception as e:
            print(f"[SPOT] Failed to load state: {e}. Starting fresh.")
            return False

    # ── Core GPD fitting ──────────────────────────────────────────────────

    def _fit_gpd(self):
        """
        Fit a Generalised Pareto Distribution to the tail of the score
        distribution and compute the HIGH threshold.

        Steps:
          1. Set tail split t = TAIL_QUANTILE percentile of history
          2. Extract exceedances: scores above t
          3. Fit GPD to exceedances using MLE
          4. Compute z such that P(score > z) = target_prob
          5. Update thresholds
        """
        scores = np.array(self._history)
        n      = len(scores)

        if n < 50:
            return  # not enough data yet

        # Step 1: tail split
        t = float(np.quantile(scores, self.tail_quantile))
        self._t = t

        # Step 2: exceedances (scores above t, shifted to zero)
        exceedances = scores[scores > t] - t
        Nt = len(exceedances)

        if Nt < 10:
            # Too few tail points — tighten the tail quantile temporarily
            t = float(np.quantile(scores, 0.90))
            exceedances = scores[scores > t] - t
            Nt = len(exceedances)
            if Nt < 5:
                return  # genuinely not enough tail data

        # Step 3: fit GPD via MLE
        gamma, sigma = self._fit_gpd_mle(exceedances)

        # Step 4: compute HIGH threshold
        # P(X > z) = (Nt/n) * (1 + gamma*(z-t)/sigma)^(-1/gamma)
        # Solve for z given P = target_prob:
        #   z = t + (sigma/gamma) * ((n/Nt * target_prob)^(-gamma) - 1)
        # For gamma ≈ 0 (exponential case):
        #   z = t - sigma * log(n/Nt * target_prob)
        try:
            ratio = (n / Nt) * self.target_prob
            if abs(gamma) < 1e-4:
                # Exponential tail (gamma → 0)
                z_high = t - sigma * np.log(ratio)
            else:
                z_high = t + (sigma / gamma) * (ratio ** (-gamma) - 1)

            # Clip to valid range — GPD can occasionally produce extreme values
            # on small datasets
            z_high = float(np.clip(z_high, 0.5, 0.999))

            # Step 5: MEDIUM threshold = 90th percentile of the full distribution
            # This is simpler — no GPD needed, just a quantile
            z_medium = float(np.quantile(scores, self.medium_quantile))
            z_medium = float(np.clip(z_medium, 0.3, z_high - 0.05))

            # Sanity check: HIGH must be above MEDIUM
            if z_high <= z_medium:
                z_high = z_medium + 0.1

            self._threshold_high   = z_high
            self._threshold_medium = z_medium
            self._n_since_fit      = 0
            self._last_fit_at      = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            print(f"[SPOT] GPD threshold computation failed: {e}. "
                  f"Keeping current thresholds.")

    def _fit_gpd_mle(self, exceedances: np.ndarray) -> tuple:
        """
        Fit Generalised Pareto Distribution parameters (gamma, sigma) to
        exceedances using Maximum Likelihood Estimation.

        GPD PDF: f(x) = (1/sigma) * (1 + gamma*x/sigma)^(-(1/gamma + 1))
        For gamma=0: f(x) = (1/sigma) * exp(-x/sigma)  [exponential]

        We use the method of moments as a fast closed-form estimator,
        which is near-MLE for the sample sizes we have (10-300 exceedances).

        Returns (gamma, sigma) — shape and scale parameters.
        """
        if len(exceedances) < 2:
            return 0.0, float(np.mean(exceedances)) if len(exceedances) > 0 else 0.1

        m1 = float(np.mean(exceedances))
        m2 = float(np.mean(exceedances ** 2))

        if m1 <= 0 or m2 <= 0:
            return 0.0, 0.1

        # Method of moments estimators for GPD
        # gamma = 0.5 * (1 - m1^2 / (m2/2 - m1^2))  — simplified
        variance = m2 - m1 ** 2
        if variance <= 0:
            return 0.0, m1

        gamma = 0.5 * (m1 ** 2 / variance - 1)
        sigma = 0.5 * m1 * (m1 ** 2 / variance + 1)

        # Clip gamma to stable range — extreme values cause numerical issues
        gamma = float(np.clip(gamma, -0.5, 1.0))
        sigma = float(max(sigma, 1e-6))

        return gamma, sigma


# ── Module-level singleton ────────────────────────────────────────────────────
# One SPOT instance shared across all scorer.py calls.
# Loaded from disk on import so thresholds survive restarts.

_spot = SPOTThreshold()
_spot.load()   # no-op if no saved state yet


def update_spot(score: float):
    """Feed a score into SPOT. Call after every score_event()."""
    _spot.update(score)
    # Persist every 100 updates to survive restarts without too much I/O
    if _spot.n_total % 100 == 0:
        _spot.save()


def get_risk_level(score: float) -> str:
    """Get risk level using current SPOT thresholds."""
    return _spot.classify(score)


def get_spot_status() -> dict:
    """Expose SPOT state to /health and /model endpoints."""
    return _spot.status()