"""Deterministic error-type probability inference utilities."""

from __future__ import annotations


DIFFICULTY_TIME_BASELINES: dict[str, float] = {
    "easy": 60.0,
    "medium": 90.0,
    "hard": 120.0,
}


def _normalize_three(conceptual: float, careless: float, time_pressure: float) -> dict[str, float]:
    total = conceptual + careless + time_pressure
    if total <= 0:
        return {"conceptual": 1 / 3, "careless": 1 / 3, "time_pressure": 1 / 3}

    return {
        "conceptual": conceptual / total,
        "careless": careless / total,
        "time_pressure": time_pressure / total,
    }


def infer_error_probs(attempts: list[dict], mastery_by_topic: dict[str, float]) -> dict[str, dict]:
    """Infer per-topic error probabilities with simple deterministic heuristics.

    Heuristics:
    - conceptual increases as mastery drops below 0.5 and wrong rate rises.
    - careless increases when mastery is high but wrong answers still happen,
      especially with short response time.
    - time_pressure increases when attempts are consistently fast relative to
      expected difficulty time.
    """
    grouped: dict[str, list[dict]] = {}
    for attempt in attempts:
        topic = str(attempt.get("topic", "Unknown"))
        grouped.setdefault(topic, []).append(attempt)

    result: dict[str, dict] = {}

    for topic, topic_attempts in grouped.items():
        mastery = float(mastery_by_topic.get(topic, 0.5))
        count = max(1, len(topic_attempts))

        wrong_count = sum(1 for attempt in topic_attempts if not bool(attempt.get("correct", False)))
        wrong_rate = wrong_count / count

        expected_times = [
            DIFFICULTY_TIME_BASELINES.get(str(attempt.get("difficulty", "medium")).lower(), 90.0)
            for attempt in topic_attempts
        ]
        expected_avg = sum(expected_times) / len(expected_times)

        short_count = sum(
            1
            for attempt, expected in zip(topic_attempts, expected_times, strict=True)
            if float(attempt.get("time_taken", expected)) < (0.7 * expected)
        )
        short_ratio = short_count / count

        conceptual = max(0.0, 0.55 - mastery) + (0.70 * wrong_rate)

        if mastery > 0.6:
            careless = (0.90 * wrong_rate) + (0.70 * short_ratio)
        else:
            careless = (0.30 * wrong_rate) + (0.35 * short_ratio)

        time_pressure = (0.95 * short_ratio)
        if expected_avg > 0:
            observed_avg = sum(float(attempt.get("time_taken", expected_avg)) for attempt in topic_attempts) / count
            speed_ratio = observed_avg / expected_avg
            time_pressure += max(0.0, 0.8 - speed_ratio)

        result[topic] = _normalize_three(conceptual, careless, time_pressure)

    for topic in mastery_by_topic:
        result.setdefault(topic, {"conceptual": 1 / 3, "careless": 1 / 3, "time_pressure": 1 / 3})

    return result
