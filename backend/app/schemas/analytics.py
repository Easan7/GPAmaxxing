"""Schemas for analytics endpoints."""

from datetime import datetime

from pydantic import BaseModel


class ErrorCategoryBreakdown(BaseModel):
    """Error category aggregate metrics."""

    count: int
    percent: float


class ErrorBreakdownResponse(BaseModel):
    """Response payload for dashboard error breakdown chart."""

    student_id: str
    window_days: int
    total_attempts: int
    total_mistakes: int
    careless: ErrorCategoryBreakdown
    conceptual: ErrorCategoryBreakdown
    time_pressure: ErrorCategoryBreakdown
    unknown: ErrorCategoryBreakdown
    generated_at: datetime


class AnalyticsSummaryResponse(BaseModel):
    """Summary metrics for top-level analytics cards."""

    student_id: str
    window_days: int
    topic_count: int
    average_mastery_percent: float
    mastery_level: int | None
    improving_percent: float
    stagnating_percent: float
    regressing_percent: float
    last_attempted_at: datetime | None
    days_since_last_study: int | None
    suggested_focus_topic: str | None
    generated_at: datetime


class NextBestActionItem(BaseModel):
    """A prioritized action recommendation for the dashboard panel."""

    id: str
    topic: str
    issue: str
    detail: str
    action_label: str
    action_type: str
    query_prompt: str
    priority_score: float
    eta_min: int


class NextBestActionsResponse(BaseModel):
    """Response payload for the Next Best Actions panel."""

    student_id: str
    window_days: int
    actions: list[NextBestActionItem]
    generated_at: datetime
