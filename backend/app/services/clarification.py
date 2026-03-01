"""Clarification gate logic for incomplete user context."""

from app.schemas.state import TopicStateItem


def check_needs_clarification(
    message: str,
    constraints: dict | None,
    topic_state: list[TopicStateItem],
) -> tuple[bool, dict | None]:
    """Return whether follow-up user input is required and the question payload."""
    normalized = message.lower()
    planning_hints = ("plan", "2 hours", "today", "study")

    has_planning_signal = any(token in normalized for token in planning_hints)
    time_budget_missing = not constraints or "time_budget_min" not in constraints
    if has_planning_signal and time_budget_missing:
        return True, {
            "prompt": "How much time can you spend this session?",
            "field": "time_budget_min",
            "options": [30, 60, 120, 180],
        }

    max_uncertainty = max((item.uncertainty for item in topic_state), default=0.0)
    if max_uncertainty > 0.6:
        return True, {
            "prompt": "Are you practicing timed or untimed?",
            "field": "mode",
            "options": ["timed", "untimed"],
        }

    return False, None
