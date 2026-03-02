"""Simple deterministic time allocation optimizer."""

from app.schemas.state import TopicStateItem


def _compute_topic_bounds(topic_count: int, time_budget_min: int) -> tuple[int, int]:
    """Return sensible per-topic min/max minute bounds.

    Bounds are dynamic to prevent overly fragmented or overly concentrated plans.
    """
    if topic_count <= 0:
        return 0, 0

    min_per_topic = 8 if time_budget_min >= 40 else 5
    max_per_topic = max(min_per_topic + 2, int(round(time_budget_min * 0.5)))
    return min_per_topic, max_per_topic


def optimize_time_allocation(topic_state: list[TopicStateItem], constraints: dict | None) -> list[dict]:
    """Allocate minutes across topics based on weakness and decay risk."""
    if not constraints:
        return []

    time_budget_min = constraints.get("time_budget_min")
    if not isinstance(time_budget_min, int) or time_budget_min <= 0:
        return []

    if not topic_state:
        return []

    min_per_topic, max_per_topic = _compute_topic_bounds(len(topic_state), time_budget_min)

    # If budget is too small to satisfy minimums for all topics, focus top-priority topics first.
    topic_candidates = list(topic_state)
    if min_per_topic * len(topic_candidates) > time_budget_min:
        topic_candidates = sorted(
            topic_candidates,
            key=lambda item: max(0.0, (1.0 - item.mastery) + item.decay_risk),
            reverse=True,
        )
        max_topics = max(1, time_budget_min // min_per_topic)
        topic_candidates = topic_candidates[:max_topics]

    scored_topics: list[tuple[str, float]] = []
    for item in topic_candidates:
        score = max(0.0, (1.0 - item.mastery) + item.decay_risk)
        scored_topics.append((item.topic, score))

    total_score = sum(score for _, score in scored_topics)
    if total_score <= 0:
        return []

    raw_allocations: list[tuple[str, float]] = [
        (topic, (score / total_score) * time_budget_min) for topic, score in scored_topics
    ]

    rounded = []
    for topic, minutes in raw_allocations:
        clipped = max(min_per_topic, min(max_per_topic, int(round(minutes))))
        rounded.append({"topic": topic, "minutes": clipped})

    allocated = sum(item["minutes"] for item in rounded)
    remainder = time_budget_min - allocated

    # Add remainder by priority without exceeding max bound.
    if remainder > 0:
        by_priority = sorted(
            rounded,
            key=lambda item: next(score for topic, score in scored_topics if topic == item["topic"]),
            reverse=True,
        )
        idx = 0
        while remainder > 0 and by_priority:
            slot = by_priority[idx % len(by_priority)]
            if slot["minutes"] < max_per_topic:
                slot["minutes"] += 1
                remainder -= 1
            idx += 1
            if idx > len(by_priority) * (max_per_topic + 2):
                break

    # Remove overflow from low-priority topics without crossing min bound.
    elif remainder < 0:
        overflow = -remainder
        by_priority = sorted(
            rounded,
            key=lambda item: next(score for topic, score in scored_topics if topic == item["topic"]),
        )
        idx = 0
        while overflow > 0 and by_priority:
            slot = by_priority[idx % len(by_priority)]
            if slot["minutes"] > min_per_topic:
                slot["minutes"] -= 1
                overflow -= 1
            idx += 1
            if idx > len(by_priority) * (max_per_topic + 2):
                break

    # Keep original priority order for readability.
    topic_order = {topic: index for index, (topic, _) in enumerate(scored_topics)}
    return sorted(rounded, key=lambda item: topic_order.get(item["topic"], 9999))
