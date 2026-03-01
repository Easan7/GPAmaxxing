"""Builds learner state snapshots for graph consumption."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.decay import compute_decay_risk
from app.models.error_inference import infer_error_probs
from app.models.mastery_elo import rating_to_mastery, update_topic_ratings
from app.models.patterns import detect_repeat_patterns
from app.models.trend import compute_trend
from app.schemas.state import ErrorStateItem, TopicStateItem


def _mock_attempts(student_id: str) -> list[dict]:
    """Return deterministic mock attempts for offline analytics execution.

    TODO: Replace mocked attempt list with Supabase query.
    """
    base = datetime(2026, 2, 1, 8, 0, 0)
    return [
        {
            "student_id": student_id,
            "topic": "Algebra",
            "difficulty": "medium",
            "correct": True,
            "time_taken": 82,
            "ts": base + timedelta(days=1),
            "tag": "calculation",
        },
        {
            "student_id": student_id,
            "topic": "Algebra",
            "difficulty": "hard",
            "correct": False,
            "time_taken": 74,
            "ts": base + timedelta(days=3),
            "tag": "calculation",
        },
        {
            "student_id": student_id,
            "topic": "Algebra",
            "difficulty": "medium",
            "correct": True,
            "time_taken": 88,
            "ts": base + timedelta(days=6),
            "tag": "calculation",
        },
        {
            "student_id": student_id,
            "topic": "Algebra",
            "difficulty": "hard",
            "correct": True,
            "time_taken": 91,
            "ts": base + timedelta(days=9),
            "tag": "signs",
        },
        {
            "student_id": student_id,
            "topic": "Algebra",
            "difficulty": "easy",
            "correct": True,
            "time_taken": 58,
            "ts": base + timedelta(days=12),
            "tag": "calculation",
        },
        {
            "student_id": student_id,
            "topic": "Geometry",
            "difficulty": "medium",
            "correct": False,
            "time_taken": 61,
            "ts": base + timedelta(days=2),
            "tag": "units",
        },
        {
            "student_id": student_id,
            "topic": "Geometry",
            "difficulty": "hard",
            "correct": False,
            "time_taken": 66,
            "ts": base + timedelta(days=5),
            "tag": "units",
        },
        {
            "student_id": student_id,
            "topic": "Geometry",
            "difficulty": "medium",
            "correct": True,
            "time_taken": 79,
            "ts": base + timedelta(days=8),
            "tag": "visualization",
        },
        {
            "student_id": student_id,
            "topic": "Geometry",
            "difficulty": "hard",
            "correct": False,
            "time_taken": 64,
            "ts": base + timedelta(days=11),
            "tag": "units",
        },
        {
            "student_id": student_id,
            "topic": "Geometry",
            "difficulty": "easy",
            "correct": True,
            "time_taken": 57,
            "ts": base + timedelta(days=14),
            "tag": "units",
        },
        {
            "student_id": student_id,
            "topic": "Word Problems",
            "difficulty": "medium",
            "correct": False,
            "time_taken": 68,
            "ts": base + timedelta(days=4),
            "tag": "worded",
        },
        {
            "student_id": student_id,
            "topic": "Word Problems",
            "difficulty": "hard",
            "correct": False,
            "time_taken": 70,
            "ts": base + timedelta(days=7),
            "tag": "worded",
        },
        {
            "student_id": student_id,
            "topic": "Word Problems",
            "difficulty": "medium",
            "correct": True,
            "time_taken": 86,
            "ts": base + timedelta(days=10),
            "tag": "translation",
        },
        {
            "student_id": student_id,
            "topic": "Word Problems",
            "difficulty": "hard",
            "correct": False,
            "time_taken": 72,
            "ts": base + timedelta(days=13),
            "tag": "worded",
        },
        {
            "student_id": student_id,
            "topic": "Word Problems",
            "difficulty": "easy",
            "correct": True,
            "time_taken": 62,
            "ts": base + timedelta(days=15),
            "tag": "worded",
        },
    ]


def _build_mastery_series(topic_attempts: list[dict]) -> list[tuple[datetime, float]]:
    """Create a timestamped mastery series from rolling topic ELO updates."""
    ordered = sorted(topic_attempts, key=lambda attempt: attempt["ts"])
    rating = 1300.0
    series: list[tuple[datetime, float]] = []

    for attempt in ordered:
        rating = update_topic_ratings([attempt], initial_rating=rating).get(attempt["topic"], rating)
        series.append((attempt["ts"], rating_to_mastery(rating)))

    return series


def build_state(student_id: str, window_days: int) -> tuple[list[TopicStateItem], list[ErrorStateItem]]:
    """Build deterministic topic and error state from mocked attempts."""
    now_ts = datetime(2026, 3, 1, 12, 0, 0)
    all_attempts = _mock_attempts(student_id=student_id)
    cutoff_ts = now_ts - timedelta(days=window_days)
    attempts = [attempt for attempt in all_attempts if attempt["ts"] >= cutoff_ts]

    if not attempts:
        attempts = all_attempts

    ratings = update_topic_ratings(attempts)
    mastery_by_topic = {topic: rating_to_mastery(rating) for topic, rating in ratings.items()}
    error_probs = infer_error_probs(attempts, mastery_by_topic)
    patterns = detect_repeat_patterns(attempts)

    attempts_by_topic: dict[str, list[dict]] = {}
    for attempt in attempts:
        attempts_by_topic.setdefault(attempt["topic"], []).append(attempt)

    topic_state: list[TopicStateItem] = []
    for topic, topic_attempts in sorted(attempts_by_topic.items()):
        topic_attempts_sorted = sorted(topic_attempts, key=lambda attempt: attempt["ts"])
        last_attempt_ts = topic_attempts_sorted[-1]["ts"]

        mastery_series = _build_mastery_series(topic_attempts_sorted)
        trend_slope, _trend_label = compute_trend(mastery_series)
        decay_risk = compute_decay_risk(last_attempt_ts=last_attempt_ts, now_ts=now_ts)

        attempt_count = len(topic_attempts_sorted)
        attempts_normalized = min(attempt_count, 10) / 10.0
        uncertainty = 1.0 - attempts_normalized

        if topic in patterns:
            uncertainty = min(1.0, uncertainty + 0.05)

        topic_state.append(
            TopicStateItem(
                topic=topic,
                mastery=round(mastery_by_topic.get(topic, 0.5), 4),
                trend=round(trend_slope, 4),
                decay_risk=round(decay_risk, 4),
                uncertainty=round(uncertainty, 4),
            )
        )

    error_state: list[ErrorStateItem] = []
    for topic, probs in sorted(error_probs.items()):
        error_state.append(
            ErrorStateItem(
                topic=topic,
                conceptual=round(float(probs.get("conceptual", 1 / 3)), 4),
                careless=round(float(probs.get("careless", 1 / 3)), 4),
                time_pressure=round(float(probs.get("time_pressure", 1 / 3)), 4),
            )
        )

    return topic_state, error_state
