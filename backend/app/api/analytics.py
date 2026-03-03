"""Analytics endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.models.analytics.error_inference import (
    annotate_attempts_with_error_type,
    error_distribution_by_topic,
)
from app.models.analytics.mastery_elo import compute_topic_mastery_elo
from app.models.analytics.repo import fetch_attempts_join_questions
from app.models.analytics.student_state import build_student_state
from app.schemas.analytics import AnalyticsSummaryResponse, ErrorBreakdownResponse

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100.0, 2)


def _mastery_level_from_average(avg_mastery: float) -> int:
    bounded = max(0.0, min(1.0, avg_mastery))
    return max(1, min(5, int(round(bounded * 4.0)) + 1))


@router.get("/error-breakdown", response_model=ErrorBreakdownResponse)
def error_breakdown(
    student_id: str = Query(..., min_length=1),
    window_days: int = Query(180, ge=1, le=3650),
) -> ErrorBreakdownResponse:
    """Return total mistake counts and percentages grouped by error category."""
    try:
        rows = fetch_attempts_join_questions(student_id=student_id, since_days=window_days)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Analytics backend unavailable: {type(exc).__name__}: {exc}") from exc

    mastery = compute_topic_mastery_elo(rows)
    annotated = annotate_attempts_with_error_type(rows, mastery)
    by_topic = error_distribution_by_topic(annotated)

    careless_count = 0
    conceptual_count = 0
    time_pressure_count = 0
    unknown_count = 0
    total_mistakes = 0

    for payload in by_topic.values():
        careless_count += int(payload.get("careless", 0) or 0)
        conceptual_count += int(payload.get("conceptual", 0) or 0)
        time_pressure_count += int(payload.get("time_pressure", 0) or 0)
        unknown_count += int(payload.get("unknown", 0) or 0)
        total_mistakes += int(payload.get("total_wrong", 0) or 0)

    return ErrorBreakdownResponse(
        student_id=student_id,
        window_days=window_days,
        total_attempts=len(rows),
        total_mistakes=total_mistakes,
        careless={
            "count": careless_count,
            "percent": _percent(careless_count, total_mistakes),
        },
        conceptual={
            "count": conceptual_count,
            "percent": _percent(conceptual_count, total_mistakes),
        },
        time_pressure={
            "count": time_pressure_count,
            "percent": _percent(time_pressure_count, total_mistakes),
        },
        unknown={
            "count": unknown_count,
            "percent": _percent(unknown_count, total_mistakes),
        },
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def analytics_summary(
    student_id: str = Query(..., min_length=1),
    window_days: int = Query(180, ge=1, le=3650),
) -> AnalyticsSummaryResponse:
    """Return summary metrics used by dashboard stat cards."""
    try:
        rows = fetch_attempts_join_questions(student_id=student_id, since_days=None)
        state = build_student_state(student_id=student_id, since_days=window_days)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Analytics backend unavailable: {type(exc).__name__}: {exc}") from exc

    last_attempted_at = max((row.get("attempted_at") for row in rows if row.get("attempted_at") is not None), default=None)
    days_since_last_study = None
    if isinstance(last_attempted_at, datetime):
        now_utc = datetime.now(timezone.utc)
        if last_attempted_at.tzinfo is None:
            last_attempted_at = last_attempted_at.replace(tzinfo=timezone.utc)
        days_since_last_study = max(0, (now_utc - last_attempted_at).days)

    weakest_topics = (state.get("overall") or {}).get("weakest_topics") or []
    suggested_focus_topic = None
    if weakest_topics:
        suggested_focus_topic = str((weakest_topics[0] or {}).get("topic") or "").strip() or None

    topics_payload = (state.get("topics") or {}).values()
    topic_count = len(state.get("topics") or {})

    total_mastery = 0.0
    improving_count = 0
    stagnating_count = 0
    regressing_count = 0
    for topic in topics_payload:
        mastery = float((topic or {}).get("mastery", 0.0) or 0.0)
        total_mastery += mastery
        trend_label = str(((topic or {}).get("trend") or {}).get("label") or "").strip().lower()
        if trend_label == "improving":
            improving_count += 1
        elif trend_label == "regressing":
            regressing_count += 1
        else:
            stagnating_count += 1

    avg_mastery = (total_mastery / topic_count) if topic_count else 0.0
    average_mastery_percent = round(avg_mastery * 100.0, 2)
    mastery_level = _mastery_level_from_average(avg_mastery) if topic_count > 0 else None

    return AnalyticsSummaryResponse(
        student_id=student_id,
        window_days=window_days,
        topic_count=topic_count,
        average_mastery_percent=average_mastery_percent,
        mastery_level=mastery_level,
        improving_percent=_percent(improving_count, topic_count),
        stagnating_percent=_percent(stagnating_count, topic_count),
        regressing_percent=_percent(regressing_count, topic_count),
        last_attempted_at=last_attempted_at,
        days_since_last_study=days_since_last_study,
        suggested_focus_topic=suggested_focus_topic,
        generated_at=datetime.now(timezone.utc),
    )
