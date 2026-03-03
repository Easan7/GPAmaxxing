"""Schemas for persisted study plans APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PlanListItem(BaseModel):
    id: str
    created_at: str | None = None
    window_days: int | None = None
    start_date: str | None = None
    end_date: str | None = None


class PlanListResponse(BaseModel):
    student_id: str
    plans: list[PlanListItem]


class PlanItemStatusPatchRequest(BaseModel):
    student_id: str
    status: str
    note: str | None = None


class PlanQuestionsResponse(BaseModel):
    plan_item_id: str
    questions: list[dict[str, Any]]
