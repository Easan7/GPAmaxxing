"""ELO-style per-topic mastery utilities.

Example:
    >>> from datetime import datetime, timezone
    >>> rows = [
    ...     {"attempted_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "correct": True, "topic": "Algebra", "difficulty": "easy"},
    ...     {"attempted_at": datetime(2026, 1, 2, tzinfo=timezone.utc), "correct": False, "topic": "Algebra", "difficulty": "hard"},
    ... ]
    >>> out = compute_topic_mastery_elo(rows)
    >>> "Algebra" in out and out["Algebra"]["n_attempts"] == 2
    True
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, TypedDict


_BASELINE_ELO = 1000.0
_K_BY_DIFFICULTY = {
    "easy": 20.0,
    "medium": 24.0,
    "hard": 28.0,
}


class TopicMasteryELO(TypedDict):
    topic: str
    elo: float
    mastery: float
    n_attempts: int
    n_correct: int
    last_attempted_at: datetime | None


def _expected_score(elo: float, baseline: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(elo - baseline) / 400.0))


def _logistic(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _mastery_from_elo(elo: float) -> float:
    mastery = _logistic((elo - _BASELINE_ELO) / 400.0)
    return max(0.0, min(1.0, mastery))


def _k_for_difficulty(difficulty: str | None) -> float:
    if not difficulty:
        return 24.0
    return _K_BY_DIFFICULTY.get(str(difficulty).lower(), 24.0)


def compute_topic_mastery_elo(attempt_rows: list[dict]) -> dict[str, dict]:
    """Compute per-topic ELO mastery from flattened attempt rows.

    Input rows are expected to include:
    - attempted_at (datetime)
    - correct (bool)
    - topic (str)
    - difficulty (str | None)

    Output is keyed by topic:
    {
      "topic": str,
      "elo": float,
      "mastery": float,
      "n_attempts": int,
      "n_correct": int,
      "last_attempted_at": datetime | None,
    }
    """
    ordered = sorted(attempt_rows, key=lambda row: row.get("attempted_at") or datetime.min)

    state: dict[str, TopicMasteryELO] = {}

    for row in ordered:
        topic = str(row.get("topic") or "Unknown")
        correct = bool(row.get("correct", False))
        attempted_at = row.get("attempted_at")
        difficulty = row.get("difficulty")

        topic_state = state.setdefault(
            topic,
            {
                "topic": topic,
                "elo": _BASELINE_ELO,
                "mastery": _mastery_from_elo(_BASELINE_ELO),
                "n_attempts": 0,
                "n_correct": 0,
                "last_attempted_at": None,
            },
        )

        elo = float(topic_state["elo"])
        expected = _expected_score(elo, _BASELINE_ELO)
        outcome = 1.0 if correct else 0.0

        k_factor = _k_for_difficulty(difficulty)
        updated_elo = elo + k_factor * (outcome - expected)

        topic_state["elo"] = float(updated_elo)
        topic_state["mastery"] = _mastery_from_elo(updated_elo)
        topic_state["n_attempts"] = int(topic_state["n_attempts"]) + 1
        topic_state["n_correct"] = int(topic_state["n_correct"]) + (1 if correct else 0)
        topic_state["last_attempted_at"] = attempted_at

    return state


def compute_mastery_by_topic(attempts: list[dict]) -> dict[str, float]:
    """Backward-compatible helper returning only mastery per topic."""
    per_topic = compute_topic_mastery_elo(attempts)
    return {topic: float(values["mastery"]) for topic, values in per_topic.items()}
