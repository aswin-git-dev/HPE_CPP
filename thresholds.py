"""
thresholds.py
-------------
Single source of truth for anomaly score thresholds.
Import these constants everywhere instead of hardcoding numbers.

Risk levels:
  HIGH   → score > 0.9   (immediate action required)
  MEDIUM → score > 0.6   (investigate soon)
  LOW    → score <= 0.6  (monitor only)

Note: These are FALLBACK values used during SPOT warmup only.
Once SPOT warms up (after 1000 events), thresholds become dynamic.
See spot_threshold.py.
"""

THRESHOLD_HIGH   = 0.8
THRESHOLD_MEDIUM = 0.5
THRESHOLD_LOW    = 0.0