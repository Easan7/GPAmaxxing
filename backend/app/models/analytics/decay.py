"""Decay risk utilities over joined attempt rows."""

from __future__ import annotations

import math
from datetime import datetime, timezone


_HALF_LIFE_DAYS = 7.0
_LAMBDA = math.log(2.0) / _HALF_LIFE_DAYS


def _to_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def compute_decay_risk(
    last_attempt_ts: datetime | None,
    now_ts: datetime | None = None,
) -> float:
    """Compute decay risk from elapsed time since last attempt.

    Risk uses an exponential half-life model and is clamped to [0, 1].
    - No prior attempt => risk 1.0
    - Recent attempt => risk near 0.0
    """
    if last_attempt_ts is None:
        return 1.0

    now_ts = _to_aware_datetime(now_ts) or datetime.now(timezone.utc)
    last_attempt_ts = _to_aware_datetime(last_attempt_ts)

    delta_seconds = (now_ts - last_attempt_ts).total_seconds()
    days_since_last = max(0.0, delta_seconds / 86400.0)
    decay_factor = math.exp(-_LAMBDA * days_since_last)
    decay_factor = max(0.0, min(1.0, decay_factor))
    decay_risk = 1.0 - decay_factor
    return max(0.0, min(1.0, decay_risk))


def compute_decay_by_topic(
    mastery_by_topic: dict[str, dict],
    now: datetime | None = None,
) -> dict[str, dict]:
    """Compute decay signals per topic from mastery summary rows.

    Input topic values are expected to contain at least:
    - mastery: float in [0, 1]
    - last_attempted_at: datetime | None

    Returns per topic:
    {
      "days_since_last": float,
      "decay_factor": float,
      "decay_risk": float,
      "decayed_mastery": float,
    }
    """
    now_ts = _to_aware_datetime(now) or datetime.now(timezone.utc)

    result: dict[str, dict] = {}
    for topic, values in mastery_by_topic.items():
        mastery = float(values.get("mastery", 0.0))
        last_attempted_at = _to_aware_datetime(values.get("last_attempted_at"))

        if last_attempted_at is None:
            days_since_last = float("inf")
            decay_factor = 0.0
            decay_risk = 1.0
            decayed_mastery = 0.0
        else:
            delta_seconds = (now_ts - last_attempted_at).total_seconds()
            days_since_last = max(0.0, delta_seconds / 86400.0)
            decay_factor = math.exp(-_LAMBDA * days_since_last)
            decay_factor = max(0.0, min(1.0, decay_factor))
            decay_risk = 1.0 - decay_factor
            decay_risk = max(0.0, min(1.0, decay_risk))
            decayed_mastery = max(0.0, min(1.0, mastery * decay_factor))

        result[topic] = {
            "days_since_last": days_since_last,
            "decay_factor": decay_factor,
            "decay_risk": decay_risk,
            "decayed_mastery": decayed_mastery,
        }

    return result


def compute_topic_decay_risk(
    attempts: list[dict],
    now_ts: datetime | None = None,
) -> dict[str, float]:
    """Compute decay risk per topic from most recent attempt timestamps."""
    if now_ts is None:
        now_ts = datetime.now(timezone.utc)

    latest_by_topic: dict[str, datetime] = {}
    for attempt in attempts:
        topic = str(attempt.get("topic") or "Unknown")
        attempted_at = attempt.get("attempted_at")
        if attempted_at is None:
            continue

        last_ts = latest_by_topic.get(topic)
        if last_ts is None or attempted_at > last_ts:
            latest_by_topic[topic] = attempted_at

    return {
        topic: compute_decay_risk(last_attempt_ts=last_ts, now_ts=now_ts)
        for topic, last_ts in latest_by_topic.items()
    }
