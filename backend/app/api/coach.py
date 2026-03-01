"""Coach endpoints."""

from typing import Union
from uuid import uuid4

from fastapi import APIRouter

from app.agents.graph import get_coach_graph
from app.schemas.coach import CoachQueryRequest
from app.schemas.state import CoachResponseComplete, CoachResponseNeedsInput, CoachRunState

router = APIRouter(prefix="/api/coach", tags=["coach"])


@router.post("/query")
def coach_query(payload: CoachQueryRequest) -> Union[CoachResponseNeedsInput, CoachResponseComplete]:
    run_id = str(uuid4())

    initial_state = CoachRunState(
        run_id=run_id,
        student_id=payload.student_id,
        message=payload.message,
        constraints=payload.constraints,
        window_days=payload.window_days,
        intent=None,
    )

    graph = get_coach_graph()
    output = graph.invoke(initial_state.model_dump())
    final_state = CoachRunState.model_validate(output)

    if final_state.needs_clarification:
        return CoachResponseNeedsInput(
            status="needs_user_input",
            run_id=final_state.run_id,
            question=final_state.clarification_question or {},
        )

    actions = (
        [{"type": "start_practice", "label": "Start focused practice session"}]
        if final_state.intent == "PLAN"
        else [{"type": "generate_plan", "label": "Generate a targeted study plan"}]
    )

    return CoachResponseComplete(
        status="complete",
        run_id=final_state.run_id,
        intent=final_state.intent or "PLAN",
        insights=final_state.diagnosis,
        plan=final_state.plan,
        evidence={
            "topic_state": [item.model_dump() for item in final_state.topic_state],
            "error_state": [item.model_dump() for item in final_state.error_state],
        },
        actions=actions,
        explain_mode=final_state.tool_trace,
    )
