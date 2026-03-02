"""Error inference utilities over joined attempt rows."""

from __future__ import annotations

import math


def _extract_mastery(mastery_value: dict | float | int | None) -> float:
    if isinstance(mastery_value, dict):
        return float(mastery_value.get("mastery", 0.0))
    if mastery_value is None:
        return 0.0
    return float(mastery_value)


def _percentile_25(values: list[float]) -> float:
    if not values:
        return 20.0

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = 0.25 * (len(ordered) - 1)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return ordered[low]

    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def _coerce_confidence(value: float | int | None, mastery: float) -> float:
    if value is None:
        return max(0.0, min(1.0, mastery))
    return max(0.0, min(1.0, float(value)))


def annotate_attempts_with_error_type(
    attempt_rows: list[dict],
    mastery_by_topic: dict[str, dict],
) -> list[dict]:
    """Annotate attempts with inferred error_type using topic mastery and timing.

    Rules (tuned to minimize unknown labels on sparse student data):
    - correct=True => error_type=None
    - conceptual: lower mastery band and/or low-confidence misses
    - careless: high mastery + confident + fast miss
    - time_pressure: timed + fast + low-confidence miss
    - fallback: deterministic conceptual/careless split (avoids unknown unless data is too sparse)
    """
    non_null_times = [
        float(row["time_taken_sec"])
        for row in attempt_rows
        if row.get("time_taken_sec") is not None
    ]
    fast_threshold = _percentile_25(non_null_times)

    topic_times: dict[str, list[float]] = {}
    for row in attempt_rows:
        if row.get("time_taken_sec") is None:
            continue
        topic = str(row.get("topic") or "Unknown")
        topic_times.setdefault(topic, []).append(float(row["time_taken_sec"]))

    topic_fast_threshold: dict[str, float] = {
        topic: _percentile_25(values)
        for topic, values in topic_times.items()
    }

    annotated: list[dict] = []
    for row in attempt_rows:
        updated = dict(row)

        if bool(row.get("correct", False)):
            updated["error_type"] = None
            annotated.append(updated)
            continue

        topic = str(row.get("topic") or "Unknown")
        mastery = _extract_mastery(mastery_by_topic.get(topic))
        confidence = _coerce_confidence(row.get("confidence"), mastery)
        mode = str(row.get("mode") or "").lower()
        time_taken_sec = row.get("time_taken_sec")

        topic_threshold = topic_fast_threshold.get(topic, fast_threshold)
        is_fast = time_taken_sec is not None and float(time_taken_sec) <= topic_threshold
        error_type = "unknown"

        if mastery < 0.55 and confidence <= 0.50:
            error_type = "conceptual"
        elif mastery >= 0.62 and confidence >= 0.65 and is_fast:
            error_type = "careless"
        elif mode == "timed" and confidence <= 0.6 and is_fast:
            error_type = "time_pressure"
        elif mastery >= 0.50 and confidence >= 0.55 and mode == "timed":
            error_type = "careless"
        elif mastery < 0.60:
            error_type = "conceptual"
        elif mode == "timed" and is_fast:
            error_type = "time_pressure"
        elif mastery >= 0.60:
            error_type = "careless"

        updated["error_type"] = error_type
        annotated.append(updated)

    return annotated


def error_distribution_by_topic(annotated_rows: list[dict]) -> dict[str, dict]:
    """Aggregate wrong-attempt error labels into topic-level counts."""
    result: dict[str, dict] = {}

    for row in annotated_rows:
        if bool(row.get("correct", False)):
            continue

        topic = str(row.get("topic") or "Unknown")
        error_type = str(row.get("error_type") or "unknown")

        bucket = result.setdefault(
            topic,
            {
                "conceptual": 0,
                "careless": 0,
                "time_pressure": 0,
                "unknown": 0,
                "total_wrong": 0,
            },
        )

        if error_type not in {"conceptual", "careless", "time_pressure", "unknown"}:
            error_type = "unknown"

        bucket[error_type] += 1
        bucket["total_wrong"] += 1

    return result


def infer_topic_error_probs(
    attempts: list[dict],
    mastery_by_topic: dict[str, dict],
) -> dict[str, dict]:
    """Compatibility wrapper returning normalized probabilities by topic."""
    annotated = annotate_attempts_with_error_type(attempt_rows=attempts, mastery_by_topic=mastery_by_topic)
    counts = error_distribution_by_topic(annotated)

    probs: dict[str, dict] = {}
    for topic, item in counts.items():
        total_wrong = max(1, int(item.get("total_wrong", 0)))
        probs[topic] = {
            "conceptual": float(item.get("conceptual", 0)) / total_wrong,
            "careless": float(item.get("careless", 0)) / total_wrong,
            "time_pressure": float(item.get("time_pressure", 0)) / total_wrong,
        }

    return probs
