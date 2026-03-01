"""Deterministic repeated-pattern detection utilities."""

from __future__ import annotations

from collections import Counter


def detect_repeat_patterns(attempts: list[dict]) -> dict[str, dict]:
    """Detect repeated error tags per topic.

    Returns only topics where the most common tag appears at least three times.
    """
    tags_by_topic: dict[str, list[str]] = {}

    for attempt in attempts:
        topic = str(attempt.get("topic", "Unknown"))
        tag = attempt.get("tag")
        if tag:
            tags_by_topic.setdefault(topic, []).append(str(tag))

    patterns: dict[str, dict] = {}
    for topic, tags in tags_by_topic.items():
        if not tags:
            continue
        top_tag, count = Counter(tags).most_common(1)[0]
        if count >= 3:
            patterns[topic] = {
                "pattern_tag": top_tag,
                "count": count,
            }

    return patterns
