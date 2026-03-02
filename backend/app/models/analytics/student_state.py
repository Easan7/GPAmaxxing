"""Orchestrator for building unified analytics student state."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from app.models.analytics.decay import compute_decay_by_topic
from app.models.analytics.error_inference import (
    annotate_attempts_with_error_type,
    error_distribution_by_topic,
)
from app.models.analytics.mastery_elo import compute_topic_mastery_elo
from app.models.analytics.patterns import detect_patterns
from app.models.analytics.repo import fetch_attempts_join_questions
from app.models.analytics.trend import compute_trends

StudentState = dict[str, Any]


def build_student_state(student_id: str, since_days: int | None = None) -> dict:
    """Build a merged analytics state for one student from repo + pure modules."""
    rows = fetch_attempts_join_questions(student_id=student_id, since_days=since_days)

    mastery = compute_topic_mastery_elo(rows)
    decay = compute_decay_by_topic(mastery)
    trends = compute_trends(rows)
    annotated = annotate_attempts_with_error_type(rows, mastery)
    error_dist = error_distribution_by_topic(annotated)
    patterns = detect_patterns(rows)

    topic_names = sorted(
        set(mastery.keys())
        | set(decay.keys())
        | set(trends.keys())
        | set(error_dist.keys())
        | set(patterns.keys())
    )

    topics: dict[str, dict] = {}
    for topic in topic_names:
        topic_mastery = mastery.get(topic, {})
        topic_decay = decay.get(topic, {})
        topic_trend = trends.get(topic)
        topic_errors = error_dist.get(topic, {})
        topic_patterns = patterns.get(topic, {})

        topics[topic] = {
            "mastery": float(topic_mastery.get("mastery", 0.0)),
            "elo": float(topic_mastery.get("elo", 1000.0)),
            "trend": topic_trend,
            "decay": topic_decay,
            "error_distribution": topic_errors,
            "patterns": topic_patterns,
            "stats": {
                "n_attempts": int(topic_mastery.get("n_attempts", 0)),
                "last_attempted_at": topic_mastery.get("last_attempted_at"),
            },
        }

    weakest_topics = [
        {
            "topic": topic,
            "mastery": float(data.get("mastery", 0.0)),
        }
        for topic, data in sorted(
            topics.items(),
            key=lambda item: float(item[1].get("mastery", 0.0)),
        )[:5]
    ]

    highest_decay_risk = [
        {
            "topic": topic,
            "decay_risk": float((data.get("decay") or {}).get("decay_risk", 0.0)),
        }
        for topic, data in sorted(
            topics.items(),
            key=lambda item: float((item[1].get("decay") or {}).get("decay_risk", 0.0)),
            reverse=True,
        )[:5]
    ]

    regressing_topics = [
        topic
        for topic, data in topics.items()
        if (data.get("trend") or {}).get("label") == "regressing"
    ]

    return {
        "student_id": student_id,
        "generated_at": datetime.now(timezone.utc),
        "topics": topics,
        "overall": {
            "weakest_topics": weakest_topics,
            "highest_decay_risk": highest_decay_risk,
            "regressing_topics": regressing_topics,
        },
    }


def debug_print_student_state_summary(student_id: str | None = None, since_days: int | None = None) -> None:
    """Minimal debug runner that prints overall summary for one student."""
    selected_student_id = student_id or os.getenv("ANALYTICS_STUDENT_ID") or "demo-student-001"
    state = build_student_state(student_id=selected_student_id, since_days=since_days)

    print(f"student_id={state['student_id']}")
    print(f"generated_at={state['generated_at']}")
    print(f"topics={len(state.get('topics', {}))}")
    print(f"weakest_topics={state.get('overall', {}).get('weakest_topics', [])}")
    print(f"highest_decay_risk={state.get('overall', {}).get('highest_decay_risk', [])}")
    print(f"regressing_topics={state.get('overall', {}).get('regressing_topics', [])}")


if __name__ == "__main__":
    debug_print_student_state_summary()
