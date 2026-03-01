"""Builds learner state snapshots for graph consumption."""

from app.schemas.state import ErrorStateItem, TopicStateItem


def build_state(student_id: str, window_days: int) -> tuple[list[TopicStateItem], list[ErrorStateItem]]:
    """Return a mocked learner state with realistic normalized values.

    TODO: Replace with Supabase fetch + deterministic ELO/decay computation pipeline.
    """
    _ = (student_id, window_days)

    topic_state = [
        TopicStateItem(topic="Algebra", mastery=0.58, trend=0.25, decay_risk=0.34, uncertainty=0.22),
        TopicStateItem(topic="Geometry", mastery=0.42, trend=-0.10, decay_risk=0.56, uncertainty=0.47),
        TopicStateItem(topic="Word Problems", mastery=0.33, trend=-0.22, decay_risk=0.63, uncertainty=0.55),
    ]

    error_state = [
        ErrorStateItem(topic="Algebra", conceptual=0.30, careless=0.48, time_pressure=0.36),
        ErrorStateItem(topic="Geometry", conceptual=0.62, careless=0.41, time_pressure=0.57),
        ErrorStateItem(topic="Word Problems", conceptual=0.71, careless=0.33, time_pressure=0.52),
    ]

    return topic_state, error_state
