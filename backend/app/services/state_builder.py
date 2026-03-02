"""Builds learner state snapshots for graph consumption."""

from __future__ import annotations

from app.models.analytics.student_state import build_student_state
from app.schemas.state import ErrorStateItem, TopicStateItem


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_error_probs(error_distribution: dict) -> tuple[float, float, float]:
    total_wrong = int(error_distribution.get("total_wrong", 0) or 0)
    if total_wrong <= 0:
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)

    conceptual = _safe_float(error_distribution.get("conceptual", 0.0)) / total_wrong
    careless = _safe_float(error_distribution.get("careless", 0.0)) / total_wrong
    time_pressure = _safe_float(error_distribution.get("time_pressure", 0.0)) / total_wrong
    return conceptual, careless, time_pressure


def build_state(student_id: str, window_days: int) -> tuple[list[TopicStateItem], list[ErrorStateItem]]:
    """Build topic and error state from live Supabase-backed analytics."""
    try:
        state = build_student_state(student_id=student_id, since_days=window_days)
    except Exception:
        # Keep agent flow alive when analytics backing store is unavailable.
        return [], []
    topics_payload: dict[str, dict] = state.get("topics", {})

    topic_state: list[TopicStateItem] = []
    error_state: list[ErrorStateItem] = []

    for topic, payload in sorted(topics_payload.items()):
        trend_block = payload.get("trend") or {}
        decay_block = payload.get("decay") or {}
        stats_block = payload.get("stats") or {}
        patterns_block = payload.get("patterns") or {}
        error_distribution = payload.get("error_distribution") or {}

        trend_slope = _safe_float(trend_block.get("slope", 0.0))
        decay_risk = _safe_float(decay_block.get("decay_risk", 0.0))
        mastery = _safe_float(payload.get("mastery", 0.5), 0.5)

        attempts = max(0, int(stats_block.get("n_attempts", 0) or 0))
        attempts_normalized = min(attempts, 12) / 12.0
        volatility = _safe_float(trend_block.get("volatility", 0.0))
        pattern_alerts = patterns_block.get("alerts") or []
        uncertainty = 1.0 - attempts_normalized
        uncertainty = min(1.0, uncertainty + min(0.2, volatility * 5.0))
        if pattern_alerts:
            uncertainty = min(1.0, uncertainty + 0.05)

        topic_state.append(
            TopicStateItem(
                topic=topic,
                mastery=round(mastery, 4),
                trend=round(trend_slope, 4),
                decay_risk=round(decay_risk, 4),
                uncertainty=round(uncertainty, 4),
            )
        )

        conceptual, careless, time_pressure = _normalize_error_probs(error_distribution)
        error_state.append(
            ErrorStateItem(
                topic=topic,
                conceptual=round(conceptual, 4),
                careless=round(careless, 4),
                time_pressure=round(time_pressure, 4),
            )
        )

    return topic_state, error_state
