"""Deterministic forgetting/decay risk utilities."""

from __future__ import annotations

import math
from datetime import datetime


def compute_decay_risk(last_attempt_ts: datetime, now_ts: datetime, lambda_: float = 0.01) -> float:
    """Compute decay risk from elapsed days using exponential growth-to-one.

    Formula:
        risk = 1 - exp(-lambda * days_since_last_attempt)
    """
    delta_seconds = max(0.0, (now_ts - last_attempt_ts).total_seconds())
    days_since_last_attempt = delta_seconds / 86400.0
    risk = 1.0 - math.exp(-lambda_ * days_since_last_attempt)
    return max(0.0, min(1.0, risk))
