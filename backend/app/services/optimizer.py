"""Simple deterministic time allocation optimizer."""

from app.schemas.state import TopicStateItem


def _compute_topic_bounds(topic_count: int, time_budget_min: int) -> tuple[int, int]:
    """Return sensible per-topic min/max minute bounds.

    Bounds are dynamic to prevent overly fragmented or overly concentrated plans.
    """
    if topic_count <= 0:
        return 0, 0

    # Product requirement: allocate at least 30 minutes per selected topic,
    # except when the entire budget itself is below 30 minutes.
    min_per_topic = 30 if time_budget_min >= 30 else max(1, time_budget_min)
    max_per_topic = max(min_per_topic + 10, int(round(time_budget_min * 0.55)))
    return min_per_topic, max_per_topic


def _apply_horizon_topic_cap(
    max_per_topic: int,
    min_per_topic: int,
    time_budget_min: int,
    topic_count: int,
    constraints: dict | None,
) -> int:
    """Cap per-topic allocation for long-horizon plans.

    This avoids one topic dominating a multi-day schedule while preserving
    flexibility for short single-session plans.
    """
    if not constraints:
        return max_per_topic

    horizon_days_raw = constraints.get("time_horizon_days")
    if not isinstance(horizon_days_raw, int) or horizon_days_raw <= 1:
        return max_per_topic

    horizon_days = max(1, int(horizon_days_raw))

    daily_cap_raw = constraints.get("max_topic_minutes_per_day")
    if isinstance(daily_cap_raw, int) and daily_cap_raw > 0:
        daily_cap_min = int(daily_cap_raw)
    else:
        daily_cap_min = 90

    horizon_cap = daily_cap_min * horizon_days

    max_share_raw = constraints.get("max_topic_share")
    if isinstance(max_share_raw, (int, float)):
        max_share = float(max_share_raw)
    else:
        max_share = 0.22
    max_share = min(1.0, max(0.1, max_share))
    share_cap = int(round(time_budget_min * max_share))

    # Ensure the cap still allows the full budget to be allocated across the
    # selected number of topics.
    minimum_feasible_cap = max(1, (time_budget_min + max(1, topic_count) - 1) // max(1, topic_count))

    capped = min(max_per_topic, horizon_cap, share_cap)
    capped = max(capped, minimum_feasible_cap)
    return max(min_per_topic, capped)


def _preferred_round_increment(time_budget_min: int, constraints: dict | None) -> int:
    if constraints and isinstance(constraints.get("round_increment_min"), int):
        configured = int(constraints["round_increment_min"])
        if configured in {1, 5, 10}:
            return configured

    if constraints and isinstance(constraints.get("time_horizon_days"), int) and int(constraints.get("time_horizon_days")) > 1:
        return 10
    return 5


def _round_allocations_with_budget_guard(
    allocations: list[dict],
    scored_topics: list[tuple[str, float]],
    total_budget_min: int,
    min_per_topic: int,
    max_per_topic: int,
    increment: int,
) -> list[dict]:
    if increment <= 1 or not allocations:
        return allocations

    score_by_topic = {topic: score for topic, score in scored_topics}
    rounded: list[dict] = []
    for item in allocations:
        snapped = int(round(item["minutes"] / increment) * increment)
        snapped = max(min_per_topic, min(max_per_topic, snapped))
        rounded.append({"topic": item["topic"], "minutes": snapped})

    diff = total_budget_min - sum(item["minutes"] for item in rounded)
    by_priority_desc = sorted(rounded, key=lambda item: score_by_topic.get(item["topic"], 0.0), reverse=True)
    by_priority_asc = list(reversed(by_priority_desc))

    safety = 0
    while abs(diff) >= increment and safety < 2000:
        candidates = by_priority_desc if diff > 0 else by_priority_asc
        moved = False
        for slot in candidates:
            if diff > 0 and slot["minutes"] + increment <= max_per_topic:
                slot["minutes"] += increment
                diff -= increment
                moved = True
                break
            if diff < 0 and slot["minutes"] - increment >= min_per_topic:
                slot["minutes"] -= increment
                diff += increment
                moved = True
                break
        if not moved:
            break
        safety += 1

    # Final single-minute reconciliation if needed.
    safety = 0
    while diff != 0 and safety < 4000:
        candidates = by_priority_desc if diff > 0 else by_priority_asc
        moved = False
        for slot in candidates:
            if diff > 0 and slot["minutes"] < max_per_topic:
                slot["minutes"] += 1
                diff -= 1
                moved = True
                break
            if diff < 0 and slot["minutes"] > min_per_topic:
                slot["minutes"] -= 1
                diff += 1
                moved = True
                break
        if not moved:
            break
        safety += 1

    topic_order = {topic: index for index, (topic, _) in enumerate(scored_topics)}
    return sorted(rounded, key=lambda item: topic_order.get(item["topic"], 9999))


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
    max_per_topic = _apply_horizon_topic_cap(
        max_per_topic=max_per_topic,
        min_per_topic=min_per_topic,
        time_budget_min=time_budget_min,
        topic_count=len(topic_state),
        constraints=constraints,
    )

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

    priority_topics = {
        str(topic).strip()
        for topic in ((constraints or {}).get("priority_topics") or [])
        if str(topic).strip()
    }
    priority_bonus_raw = (constraints or {}).get("priority_topic_bonus") if constraints else None
    priority_bonus = float(priority_bonus_raw) if isinstance(priority_bonus_raw, (int, float)) else 0.35

    scored_topics: list[tuple[str, float]] = []
    for item in topic_candidates:
        score = max(0.0, (1.0 - item.mastery) + item.decay_risk)
        if item.topic in priority_topics:
            score += max(0.0, priority_bonus)
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
    rounded = _round_allocations_with_budget_guard(
        allocations=rounded,
        scored_topics=scored_topics,
        total_budget_min=time_budget_min,
        min_per_topic=min_per_topic,
        max_per_topic=max_per_topic,
        increment=_preferred_round_increment(time_budget_min, constraints),
    )

    topic_order = {topic: index for index, (topic, _) in enumerate(scored_topics)}
    return sorted(rounded, key=lambda item: topic_order.get(item["topic"], 9999))
