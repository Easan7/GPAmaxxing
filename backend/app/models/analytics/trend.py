"""Trend utilities over joined attempt rows."""

from __future__ import annotations

import math
import statistics
from datetime import datetime


_BASELINE_ELO = 1000.0
_K_BY_DIFFICULTY = {
    "easy": 20.0,
    "medium": 24.0,
    "hard": 28.0,
}


def _expected_score(elo: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(elo - _BASELINE_ELO) / 400.0))


def _mastery_from_elo(elo: float) -> float:
    mastery = 1.0 / (1.0 + math.exp(-(elo - _BASELINE_ELO) / 400.0))
    return max(0.0, min(1.0, mastery))


def _k_for_difficulty(difficulty: str | None) -> float:
    if not difficulty:
        return 24.0
    return _K_BY_DIFFICULTY.get(str(difficulty).lower(), 24.0)


def _compute_slope(points: list[dict]) -> float:
    if len(points) < 2:
        return 0.0

    first_ts = points[0]["t"]
    x_values: list[float] = [
        max(0.0, (point["t"] - first_ts).total_seconds() / 86400.0)
        for point in points
    ]
    y_values: list[float] = [float(point["mastery"]) for point in points]

    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)

    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values, strict=True))
    var = sum((x - x_mean) ** 2 for x in x_values)
    if var == 0.0:
        return 0.0
    return cov / var


def _label_for_slope(slope: float) -> str:
    if slope > 0.01:
        return "improving"
    if slope < -0.01:
        return "regressing"
    return "stagnating"


def _volatility(points: list[dict]) -> float:
    if len(points) < 2:
        return 0.0

    deltas = [
        float(curr["mastery"]) - float(prev["mastery"])
        for prev, curr in zip(points, points[1:])
    ]
    if len(deltas) < 2:
        return 0.0
    return float(statistics.pstdev(deltas))


def compute_trends(attempt_rows: list[dict]) -> dict[str, dict]:
    """Compute per-topic trend signals from running ELO mastery points.

    Input rows are flattened analytics rows containing:
    - attempted_at (datetime)
    - correct (bool)
    - topic (str)
    - difficulty (str | None)
    """
    attempts_by_topic: dict[str, list[dict]] = {}
    for row in attempt_rows:
        topic = str(row.get("topic") or "Unknown")
        attempted_at = row.get("attempted_at")
        if not isinstance(attempted_at, datetime):
            continue
        attempts_by_topic.setdefault(topic, []).append(row)

    result: dict[str, dict] = {}

    for topic, rows in attempts_by_topic.items():
        ordered = sorted(rows, key=lambda row: row["attempted_at"])
        elo = _BASELINE_ELO
        points: list[dict] = []

        for row in ordered:
            outcome = 1.0 if bool(row.get("correct", False)) else 0.0
            difficulty = row.get("difficulty")
            expected = _expected_score(elo)
            k_factor = _k_for_difficulty(difficulty)
            elo = elo + k_factor * (outcome - expected)

            points.append(
                {
                    "t": row["attempted_at"],
                    "mastery": _mastery_from_elo(elo),
                }
            )

        points_capped = points[-50:]
        slope = _compute_slope(points_capped)
        result[topic] = {
            "slope": float(slope),
            "label": _label_for_slope(slope),
            "volatility": _volatility(points_capped),
            "points": points_capped,
        }

    return result


def compute_topic_trends(attempts: list[dict]) -> dict[str, float]:
    """Backward-compatible helper returning only slope per topic."""
    trend_map = compute_trends(attempts)
    return {topic: float(values.get("slope", 0.0)) for topic, values in trend_map.items()}
