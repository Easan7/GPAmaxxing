"""Schemas for attempt submission API."""

from pydantic import BaseModel


class AttemptSubmitRequest(BaseModel):
    student_id: str
    question_id: str
    chosen_option_id: str
    mode: str | None = None
    time_taken_sec: int | None = None
    confidence: float | None = None
