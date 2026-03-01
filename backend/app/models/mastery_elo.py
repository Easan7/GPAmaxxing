"""Deterministic ELO-style mastery utilities.

This module provides pure functions for topic rating updates and rating-to-mastery
conversion. It does not perform any I/O and is safe to run in tests or offline mode.
"""

from __future__ import annotations

import math


DIFFICULTY_RATINGS: dict[str, float] = {
    "easy": 1200.0,
    "medium": 1400.0,
    "hard": 1600.0,
}


def update_topic_ratings(attempts: list[dict], initial_rating: float = 1300.0) -> dict[str, float]:
    """Update per-topic ratings using a simple ELO-style rule.

    For each attempt, the student's topic rating is updated against a difficulty
    reference rating. The expected score uses the standard logistic ELO equation
    and a fixed K-factor for stability.
    """
    k_factor = 16.0
    ratings: dict[str, float] = {}

    for attempt in attempts:
        topic = str(attempt.get("topic", "Unknown"))
        difficulty = str(attempt.get("difficulty", "medium")).lower()
        correct = bool(attempt.get("correct", False))

        current = ratings.get(topic, initial_rating)
        opponent = DIFFICULTY_RATINGS.get(difficulty, DIFFICULTY_RATINGS["medium"])

        expected = 1.0 / (1.0 + 10.0 ** ((opponent - current) / 400.0))
        actual = 1.0 if correct else 0.0
        updated = current + k_factor * (actual - expected)

        ratings[topic] = updated

    return ratings


def rating_to_mastery(rating: float) -> float:
    """Map an ELO rating to a mastery score in [0, 1] via logistic scaling."""
    mastery = 1.0 / (1.0 + math.exp(-(rating - 1400.0) / 120.0))
    return max(0.0, min(1.0, mastery))
