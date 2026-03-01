"""Coach request/response schemas."""

from pydantic import BaseModel


class CoachQueryRequest(BaseModel):
    """Incoming payload for adaptive coach queries."""

    student_id: str
    message: str
    window_days: int = 30
    constraints: dict | None = None
