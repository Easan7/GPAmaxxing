"""Deterministic trend estimation utilities."""

from __future__ import annotations

from datetime import datetime


def compute_trend(mastery_series: list[tuple[datetime, float]]) -> tuple[float, str]:
    """Estimate trend slope from up to the last five mastery points.

    A simple least-squares slope over index positions is used for deterministic,
    dependency-free trend estimation.
    """
    if len(mastery_series) < 2:
        return 0.0, "stagnating"

    ordered = sorted(mastery_series, key=lambda item: item[0])[-5:]
    values = [point[1] for point in ordered]
    n = len(values)

    x_values = list(range(n))
    x_mean = sum(x_values) / n
    y_mean = sum(values) / n

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values, strict=True))
    denominator = sum((x - x_mean) ** 2 for x in x_values)

    slope = 0.0 if denominator == 0 else numerator / denominator

    if slope > 0.01:
        label = "improving"
    elif slope < -0.01:
        label = "regressing"
    else:
        label = "stagnating"

    return slope, label
