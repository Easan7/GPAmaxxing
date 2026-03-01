"""Clarification gate logic for incomplete user context."""

from app.schemas.state import TopicStateItem


def check_needs_clarification(
    message: str,
    constraints: dict | None,
    topic_state: list[TopicStateItem],
    clarification_question: dict | None = None,
    clarification_answer: dict | None = None,
) -> tuple[bool, dict | None, dict | None]:
    """Return whether follow-up user input is required and the question payload."""
    merged_constraints = dict(constraints or {})

    if clarification_answer:
        field = (clarification_question or {}).get("field")

        if field == "time_budget_min" and "time_budget_min" in clarification_answer:
            merged_constraints["time_budget_min"] = clarification_answer["time_budget_min"]
        elif field == "mode" and "mode" in clarification_answer:
            merged_constraints["mode"] = clarification_answer["mode"]
        else:
            if "time_budget_min" in clarification_answer:
                merged_constraints["time_budget_min"] = clarification_answer["time_budget_min"]
            if "mode" in clarification_answer:
                merged_constraints["mode"] = clarification_answer["mode"]

        return False, None, merged_constraints

    normalized = message.lower()
    planning_hints = ("plan", "2 hours", "today", "study")

    has_planning_signal = any(token in normalized for token in planning_hints)
    time_budget_missing = "time_budget_min" not in merged_constraints
    if has_planning_signal and time_budget_missing:
        return True, {
            "prompt": "How much time can you spend this session?",
            "field": "time_budget_min",
            "options": [30, 60, 120, 180],
        }, merged_constraints

    max_uncertainty = max((item.uncertainty for item in topic_state), default=0.0)
    if max_uncertainty > 0.6:
        return True, {
            "prompt": "Are you practicing timed or untimed?",
            "field": "mode",
            "options": ["timed", "untimed"],
        }, merged_constraints

    return False, None, merged_constraints
