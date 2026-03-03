"""Attempt submission API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.attempts import AttemptSubmitRequest
from app.services.study_plan_service import submit_attempt_and_reveal

router = APIRouter(prefix="/api", tags=["attempts"])


@router.post("/attempts")
def submit_attempt(payload: AttemptSubmitRequest):
    try:
        return submit_attempt_and_reveal(
            student_id=payload.student_id,
            question_id=payload.question_id,
            chosen_option_id=payload.chosen_option_id,
            mode=payload.mode,
            time_taken_sec=payload.time_taken_sec,
            confidence=payload.confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"attempt_submit_failed:{type(exc).__name__}") from exc
