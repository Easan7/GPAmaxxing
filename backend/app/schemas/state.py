"""Shared run-state and response schemas for coach graph execution."""

from typing import Literal

from pydantic import BaseModel, Field


class TopicStateItem(BaseModel):
    """Per-topic proficiency and confidence signals."""

    topic: str
    mastery: float
    trend: float
    decay_risk: float
    uncertainty: float


class ErrorStateItem(BaseModel):
    """Per-topic error decomposition signals."""

    topic: str
    conceptual: float
    careless: float
    time_pressure: float


class CoachRunState(BaseModel):
    """Mutable state carried across graph nodes."""

    run_id: str
    student_id: str
    message: str
    constraints: dict | None
    window_days: int
    intent: str | None
    needs_clarification: bool = False
    clarification_question: dict | None = None
    clarification_answer: dict | None = None
    topic_state: list[TopicStateItem] = Field(default_factory=list)
    error_state: list[ErrorStateItem] = Field(default_factory=list)
    diagnosis: dict | None = None
    artifact_type: str | None = None
    artifact: dict | None = None
    allocation: list[dict] = Field(default_factory=list)
    plan: dict | None = None
    action_result: dict | None = None
    tool_trace: list[dict] = Field(default_factory=list)


class CoachResponseNeedsInput(BaseModel):
    """Response returned when the graph requires user clarification."""

    status: Literal["needs_user_input"]
    run_id: str
    question: dict


class CoachResponseComplete(BaseModel):
    """Response returned when the graph finishes in one pass."""

    status: Literal["complete"]
    run_id: str
    intent: str
    insights: dict | None
    artifact_type: str | None = None
    artifact: dict | None = None
    plan: dict | None
    evidence: dict
    actions: list[dict]
    actions_executed: dict | None = None
    explain_mode: list[dict]
