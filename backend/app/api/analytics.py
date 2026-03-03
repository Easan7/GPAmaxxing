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
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    ErrorBreakdownResponse,
    NextBestActionItem,
    NextBestActionsResponse,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100.0, 2)


def _mastery_level_from_average(avg_mastery: float) -> int:
    bounded = max(0.0, min(1.0, avg_mastery))
    return max(1, min(5, int(round(bounded * 4.0)) + 1))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


@router.get("/next-actions", response_model=NextBestActionsResponse)
def next_best_actions(
    student_id: str = Query(..., min_length=1),
    window_days: int = Query(180, ge=1, le=3650),
) -> NextBestActionsResponse:
    """Return top prioritized learner actions from current analytics signals."""
    try:
        state = build_student_state(student_id=student_id, since_days=window_days)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Analytics backend unavailable: {type(exc).__name__}: {exc}") from exc

    topics = state.get("topics") or {}
    ranked: list[dict] = []
    for topic, payload in topics.items():
        topic_payload = payload or {}
        mastery = _safe_float(topic_payload.get("mastery"), 0.0)
        decay_risk = _safe_float((topic_payload.get("decay") or {}).get("decay_risk"), 0.0)

        errors = topic_payload.get("error_distribution") or {}
        total_wrong = int(errors.get("total_wrong", 0) or 0)
        conceptual_count = int(errors.get("conceptual", 0) or 0)
        conceptual_ratio = (conceptual_count / total_wrong) if total_wrong > 0 else 0.0

        trend_label = str((topic_payload.get("trend") or {}).get("label") or "").strip().lower()
        trend_penalty = 0.08 if trend_label == "regressing" else 0.0

        priority = ((1.0 - mastery) * 0.45) + (conceptual_ratio * 0.35) + (decay_risk * 0.20) + trend_penalty
        ranked.append(
            {
                "topic": str(topic),
                "priority": round(priority, 4),
                "mastery": mastery,
                "decay_risk": decay_risk,
                "total_wrong": total_wrong,
                "conceptual_ratio": conceptual_ratio,
                "trend_label": trend_label,
            }
        )

    ranked.sort(key=lambda item: item["priority"], reverse=True)

    def _build_primary(item: dict) -> dict:
        topic = str(item.get("topic") or "General")
        if item["total_wrong"] > 0 and item["conceptual_ratio"] >= 0.5:
            return {
                "issue": "Conceptual gap detected",
                "detail": f"Conceptual errors are {round(item['conceptual_ratio'] * 100)}% of recent mistakes.",
                "action_label": "Practice Drill",
                "action_type": "start_practice",
                "query_prompt": f"Create a focused practice drill plan for {topic} now.",
                "eta_min": 25,
            }
        if item["decay_risk"] >= 0.6:
            return {
                "issue": "High retention risk",
                "detail": "Recent performance suggests knowledge decay risk is elevated.",
                "action_label": "Review Notes",
                "action_type": "review_notes",
                "query_prompt": f"What should I review for {topic} based on my latest mistakes?",
                "eta_min": 15,
            }
        if item["trend_label"] == "regressing":
            return {
                "issue": "Regressing trend",
                "detail": "Trend is slipping compared to your prior attempts.",
                "action_label": "Generate Plan",
                "action_type": "generate_plan",
                "query_prompt": f"Generate a focused study plan for {topic} using my latest analytics.",
                "eta_min": 10,
            }
        return {
            "issue": "Low mastery priority",
            "detail": f"Mastery is currently {round(item['mastery'] * 100)}% in this topic.",
            "action_label": "Ask AI Tutor",
            "action_type": "ask_ai_tutor",
            "query_prompt": f"Why am I weak in {topic}? Give me a concise diagnosis and next steps.",
            "eta_min": 20,
        }

    def _build_secondary(item: dict) -> dict:
        topic = str(item.get("topic") or "General")
        return {
            "issue": "Weakness diagnosis",
            "detail": f"Get an explanation-first breakdown for {topic} before your next attempt.",
            "action_label": "Ask AI Tutor",
            "action_type": "ask_ai_tutor",
            "query_prompt": f"Explain my weakness in {topic} based on my recent attempts and tell me what to fix first.",
            "eta_min": 12,
        }

    actions: list[NextBestActionItem] = []
    used_action_types: set[str] = set()
    for item in ranked[:5]:
        options = [_build_primary(item), _build_secondary(item)]
        selected = next((option for option in options if option["action_type"] not in used_action_types), options[0])
        used_action_types.add(selected["action_type"])
        actions.append(
            NextBestActionItem(
                id=f"nba-{len(actions) + 1}",
                topic=item["topic"],
                issue=selected["issue"],
                detail=selected["detail"],
                action_label=selected["action_label"],
                action_type=selected["action_type"],
                query_prompt=selected["query_prompt"],
                priority_score=item["priority"],
                eta_min=selected["eta_min"],
            )
        )
        if len(actions) >= 3:
            break

    if not actions:
        actions = [
            NextBestActionItem(
                id="nba-1",
                topic="General",
                issue="Insufficient topic signals",
                detail="Complete a few practice attempts to unlock personalized action ranking.",
                action_label="Generate Plan",
                action_type="generate_plan",
                query_prompt="Generate a targeted plan from my current data baseline.",
                priority_score=0.0,
                eta_min=10,
            )
        ]

    return NextBestActionsResponse(
        student_id=student_id,
        window_days=window_days,
        actions=actions,
        generated_at=datetime.now(timezone.utc),
    )
