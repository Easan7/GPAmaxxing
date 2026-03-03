"""Study plans APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.plans import PlanItemStatusPatchRequest, PlanListResponse, PlanQuestionsResponse
from app.services.study_plan_service import (
    get_item_questions_for_attempt,
    get_study_plan_detail,
    list_study_plans,
    update_plan_item_status,
)

router = APIRouter(prefix="/api", tags=["plans"])


@router.get("/plans", response_model=PlanListResponse)
def list_plans(student_id: str = Query(..., min_length=1)) -> PlanListResponse:
    rows = list_study_plans(student_id=student_id)
    return PlanListResponse(student_id=student_id, plans=rows)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    plan = get_study_plan_detail(plan_id=plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.patch("/plan-items/{item_id}")
def patch_plan_item(item_id: str, payload: PlanItemStatusPatchRequest):
    try:
        updated = update_plan_item_status(
            item_id=item_id,
            student_id=payload.student_id,
            status=payload.status,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not updated:
        raise HTTPException(status_code=404, detail="Plan item not found")
    return updated


@router.get("/plan-items/{item_id}/questions", response_model=PlanQuestionsResponse)
def get_plan_item_questions(item_id: str) -> PlanQuestionsResponse:
    questions = get_item_questions_for_attempt(item_id=item_id)
    return PlanQuestionsResponse(plan_item_id=item_id, questions=questions)
