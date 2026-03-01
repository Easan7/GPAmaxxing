"""Simple deterministic time allocation optimizer."""

from app.schemas.state import TopicStateItem


def optimize_time_allocation(topic_state: list[TopicStateItem], constraints: dict | None) -> list[dict]:
    """Allocate minutes across topics based on weakness and decay risk."""
    if not constraints:
        return []

    time_budget_min = constraints.get("time_budget_min")
    if not isinstance(time_budget_min, int) or time_budget_min <= 0:
        return []

    scored_topics: list[tuple[str, float]] = []
    for item in topic_state:
        score = max(0.0, (1.0 - item.mastery) + item.decay_risk)
        scored_topics.append((item.topic, score))

    total_score = sum(score for _, score in scored_topics)
    if total_score <= 0:
        return []

    raw_allocations: list[tuple[str, float]] = [
        (topic, (score / total_score) * time_budget_min) for topic, score in scored_topics
    ]

    rounded = [{"topic": topic, "minutes": int(minutes)} for topic, minutes in raw_allocations]
    allocated = sum(item["minutes"] for item in rounded)
    remainder = time_budget_min - allocated

    index = 0
    while remainder > 0 and rounded:
        rounded[index % len(rounded)]["minutes"] += 1
        remainder -= 1
        index += 1

    return rounded
