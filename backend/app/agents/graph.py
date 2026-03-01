"""LangGraph workflow for offline adaptive coach orchestration.

This graph is intentionally deterministic and mock-driven for now.
TODO: Integrate Azure OpenAI, Azure AI Search retrieval, and richer multi-turn memory.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.schemas.state import CoachRunState
from app.services.clarification import check_needs_clarification
from app.services.optimizer import optimize_time_allocation
from app.services.session_service import create_study_session
from app.services.state_builder import build_state

GraphState = dict[str, Any]


def _append_trace(state: GraphState, node: str, details: dict[str, Any] | None = None) -> None:
    trace = state.get("tool_trace", [])
    trace.append({"node": node, "details": details or {}})
    state["tool_trace"] = trace


def node_build_state(state: GraphState) -> GraphState:
    topic_state, error_state = build_state(
        student_id=state["student_id"],
        window_days=state.get("window_days", 30),
    )
    state["topic_state"] = [item.model_dump() for item in topic_state]
    state["error_state"] = [item.model_dump() for item in error_state]
    _append_trace(state, "build_state", {"topics": len(topic_state), "errors": len(error_state)})
    return state


def node_route_intent(state: GraphState) -> GraphState:
    message = str(state.get("message", "")).lower()
    if "improving" in message or "regress" in message:
        intent = "TREND"
    elif "careless" in message or "weak" in message:
        intent = "WEAKNESS"
    elif "why" in message and "repeat" in message:
        intent = "PATTERN"
    else:
        intent = "PLAN"
    state["intent"] = intent
    _append_trace(state, "route_intent", {"intent": intent})
    return state


def node_uncertainty_gate(state: GraphState) -> GraphState:
    coach_state = CoachRunState.model_validate(state)
    needs, question, merged_constraints = check_needs_clarification(
        message=coach_state.message,
        constraints=coach_state.constraints,
        topic_state=coach_state.topic_state,
        clarification_question=coach_state.clarification_question,
        clarification_answer=coach_state.clarification_answer,
    )
    state["constraints"] = merged_constraints
    state["needs_clarification"] = needs
    state["clarification_question"] = question
    _append_trace(state, "uncertainty_gate", {"needs_clarification": needs})
    return state


def node_diagnosis(state: GraphState) -> GraphState:
    topic_state = state.get("topic_state", [])
    error_state = state.get("error_state", [])

    weakest_topic = None
    if topic_state:
        weakest_topic = min(topic_state, key=lambda item: item.get("mastery", 1.0))

    top_error = None
    if error_state:
        top_error = max(
            error_state,
            key=lambda item: max(
                item.get("conceptual", 0.0),
                item.get("careless", 0.0),
                item.get("time_pressure", 0.0),
            ),
        )

    state["diagnosis"] = {
        "primary_topic": weakest_topic.get("topic") if weakest_topic else None,
        "primary_issue": top_error,
        "summary": "Most opportunity is in weakest mastery topic with highest observed error pressure.",
    }
    _append_trace(state, "diagnosis")
    return state


def node_optimizer(state: GraphState) -> GraphState:
    coach_state = CoachRunState.model_validate(state)
    allocation = optimize_time_allocation(coach_state.topic_state, coach_state.constraints)
    state["allocation"] = allocation
    _append_trace(state, "optimizer", {"allocated_topics": len(allocation)})
    return state


def node_planner(state: GraphState) -> GraphState:
    allocation = state.get("allocation", [])
    checklist = [
        {
            "step": f"Practice {item['topic']} for {item['minutes']} minutes",
            "topic": item["topic"],
            "minutes": item["minutes"],
        }
        for item in allocation
    ]
    state["plan"] = {
        "title": "Focused Session Plan",
        "checklist": checklist,
    }
    _append_trace(state, "planner", {"steps": len(checklist)})
    return state


def node_evaluator(state: GraphState) -> GraphState:
    diagnosis = state.get("diagnosis") or {}
    note = None
    if state.get("intent") == "PLAN" and not state.get("allocation"):
        note = "missing time budget"
    else:
        note = "approved"
    diagnosis["evaluation"] = note
    state["diagnosis"] = diagnosis
    _append_trace(state, "evaluator", {"result": note})
    return state


def node_execute_plan_action(state: GraphState) -> GraphState:
    """Create a study session for approved plan runs.

    Safeguard: only execute when a time budget exists and allocation is non-empty.
    """
    constraints = state.get("constraints") or {}
    allocation = state.get("allocation") or []
    diagnosis = state.get("diagnosis") or {}

    if diagnosis.get("evaluation") != "approved":
        _append_trace(state, "execute_plan_action", {"executed": False, "reason": "not_approved"})
        return state

    if "time_budget_min" not in constraints or not allocation:
        _append_trace(state, "execute_plan_action", {"executed": False, "reason": "missing_guardrails"})
        return state

    result = create_study_session(
        student_id=str(state.get("student_id", "")),
        plan=state.get("plan") or {},
        run_id=str(state.get("run_id", "")),
    )
    state["action_result"] = result
    _append_trace(state, "execute_plan_action", {"executed": True, "session_id": result.get("session_id")})
    return state


def node_finalize(state: GraphState) -> GraphState:
    _append_trace(state, "finalize")
    return state


def _after_uncertainty(state: GraphState) -> str:
    if state.get("needs_clarification"):
        return "needs_input"
    intent = state.get("intent")
    if intent == "PLAN":
        return "plan"
    return "diagnosis"


@lru_cache(maxsize=1)
def get_coach_graph():
    """Build and cache the compiled graph."""
    workflow = StateGraph(dict)

    workflow.add_node("build_state", node_build_state)
    workflow.add_node("route_intent", node_route_intent)
    workflow.add_node("uncertainty_gate", node_uncertainty_gate)
    workflow.add_node("diagnosis", node_diagnosis)
    workflow.add_node("optimizer", node_optimizer)
    workflow.add_node("planner", node_planner)
    workflow.add_node("evaluator", node_evaluator)
    workflow.add_node("execute_plan_action", node_execute_plan_action)
    workflow.add_node("finalize", node_finalize)

    workflow.add_edge(START, "build_state")
    workflow.add_edge("build_state", "route_intent")
    workflow.add_edge("route_intent", "uncertainty_gate")

    workflow.add_conditional_edges(
        "uncertainty_gate",
        _after_uncertainty,
        {
            "needs_input": END,
            "diagnosis": "diagnosis",
            "plan": "optimizer",
        },
    )

    workflow.add_edge("diagnosis", "finalize")
    workflow.add_edge("optimizer", "planner")
    workflow.add_edge("planner", "evaluator")
    workflow.add_edge("evaluator", "execute_plan_action")
    workflow.add_edge("execute_plan_action", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()
