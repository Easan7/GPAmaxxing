"""Deterministic model definitions for learner state."""

from dataclasses import dataclass


@dataclass(slots=True)
class LearnerProfile:
    """Placeholder deterministic model for learner progress."""

    learner_id: str
    current_level: int = 1
