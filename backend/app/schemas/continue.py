"""Schemas for resuming paused coach runs."""

from pydantic import BaseModel


class CoachContinueRequest(BaseModel):
    """Payload containing clarification answer for a paused run."""

    run_id: str
    answer: dict
