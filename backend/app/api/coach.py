"""Coach endpoints."""

import importlib
from typing import Union
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.agents.graph2 import get_coach_graph2
from app.schemas.coach import CoachQueryRequest
from app.schemas.state import CoachResponseComplete, CoachResponseNeedsInput, CoachRunState
from app.services.run_store import get_run_store

CoachContinueRequest = importlib.import_module("app.schemas.continue").CoachContinueRequest

router = APIRouter(prefix="/api/coach", tags=["coach"])


def _to_complete_response(final_state: CoachRunState) -> CoachResponseComplete:
    actions = (
        [{"type": "start_practice", "label": "Start focused practice session"}]
        if final_state.intent == "PLAN"
        else [{"type": "generate_plan", "label": "Generate a targeted study plan"}]
    )

    actions_executed = None
    if final_state.action_result:
        actions_executed = {
            "type": "create_study_session",
            "session_id": final_state.action_result.get("session_id"),
        }

    return CoachResponseComplete(
        status="complete",
        run_id=final_state.run_id,
        intent=final_state.intent or "PLAN",
        insights=final_state.diagnosis,
        artifact_type=final_state.artifact_type,
        artifact=final_state.artifact,
        plan=final_state.plan,
        evidence={
            "topic_state": [item.model_dump() for item in final_state.topic_state],
            "error_state": [item.model_dump() for item in final_state.error_state],
        },
        actions=actions,
        actions_executed=actions_executed,
        explain_mode=final_state.tool_trace,
    )


@router.post("/query")
def coach_query(payload: CoachQueryRequest) -> Union[CoachResponseNeedsInput, CoachResponseComplete]:
    run_store = get_run_store()
    run_id = str(uuid4())

    initial_state = CoachRunState(
        run_id=run_id,
        student_id=payload.student_id,
        message=payload.message,
        constraints=payload.constraints,
        window_days=payload.window_days,
        intent=None,
    )

    graph = get_coach_graph2()
    output = graph.invoke(initial_state.model_dump())
    final_state = CoachRunState.model_validate(output)

    if final_state.needs_clarification:
        run_store.save_run(final_state.run_id, final_state.model_dump())
        return CoachResponseNeedsInput(
            status="needs_user_input",
            run_id=final_state.run_id,
            question=final_state.clarification_question or {},
        )

    run_store.delete_run(final_state.run_id)
    return _to_complete_response(final_state)


@router.post("/continue")
def coach_continue(payload: CoachContinueRequest) -> CoachResponseComplete:
    run_store = get_run_store()
    stored_state = run_store.load_run(payload.run_id)
    if not stored_state:
        raise HTTPException(status_code=404, detail="Run not found")

    resumed = dict(stored_state)
    resumed["clarification_answer"] = payload.answer
    resumed["needs_clarification"] = False

    graph = get_coach_graph2()
    output = graph.invoke(resumed)
    final_state = CoachRunState.model_validate(output)

    if final_state.needs_clarification:
        run_store.save_run(final_state.run_id, final_state.model_dump())
        raise HTTPException(status_code=400, detail="Clarification answer incomplete")

    run_store.delete_run(final_state.run_id)
    return _to_complete_response(final_state)
