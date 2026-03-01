"""LangGraph workflow with Azure OpenAI intent routing.

This version replaces hardcoded intent routing with Azure OpenAI classification,
then routes to intent-specific agent paths with deterministic fallbacks.
"""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from openai import AzureOpenAI

try:
    from app.schemas.state import CoachRunState
    from app.services.clarification import check_needs_clarification
    from app.services.optimizer import optimize_time_allocation
    from app.services.session_service import create_study_session
    from app.services.state_builder import build_state
except ModuleNotFoundError:
    backend_root = Path(__file__).resolve().parents[2]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from app.schemas.state import CoachRunState
    from app.services.clarification import check_needs_clarification
    from app.services.optimizer import optimize_time_allocation
    from app.services.session_service import create_study_session
    from app.services.state_builder import build_state

GraphState = dict[str, Any]
ALLOWED_INTENTS = {"TREND", "WEAKNESS", "PATTERN", "PLAN"}


def _append_trace(state: GraphState, node: str, details: dict[str, Any] | None = None) -> None:
    trace = state.get("tool_trace", [])
    trace.append({"node": node, "details": details or {}})
    state["tool_trace"] = trace


@lru_cache(maxsize=1)
def _get_azure_openai_client() -> AzureOpenAI:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not endpoint or not api_key:
        raise ValueError("Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY")
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-11-04-preview"),
    )


def _fallback_intent_heuristic(message: str) -> str:
    message = message.lower()
    if any(word in message for word in ["improving", "regress", "trend", "progress"]):
        return "TREND"
    if any(word in message for word in ["careless", "weak", "struggle", "mistake"]):
        return "WEAKNESS"
    if "why" in message and any(word in message for word in ["repeat", "again", "pattern"]):
        return "PATTERN"
    return "PLAN"


def _classify_intent_with_aoai(message: str) -> tuple[str, float, str]:
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        fallback = _fallback_intent_heuristic(message)
        return fallback, 0.4, "fallback_missing_deployment"

    system_prompt = (
        "You are an intent classifier for a learning coach. "
        "Classify the query into exactly one of: TREND, WEAKNESS, PATTERN, PLAN. "
        "Return JSON only in this format: "
        '{"intent":"TREND|WEAKNESS|PATTERN|PLAN","confidence":0.0}. '
        "No markdown, no extra text."
    )

    try:
        client = _get_azure_openai_client()
        response = client.chat.completions.create(
            model=deployment,
            temperature=0,
            max_tokens=50,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        payload = json.loads(content)
        intent = str(payload.get("intent", "PLAN")).upper().strip()
        confidence = float(payload.get("confidence", 0.0))

        if intent not in ALLOWED_INTENTS:
            fallback = _fallback_intent_heuristic(message)
            return fallback, 0.3, "fallback_invalid_intent"

        confidence = max(0.0, min(1.0, confidence))
        return intent, confidence, "azure_openai"
    except Exception:
        fallback = _fallback_intent_heuristic(message)
        return fallback, 0.3, "fallback_error"


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
    message = str(state.get("message", "")).strip()
    intent, confidence, source = _classify_intent_with_aoai(message)
    state["intent"] = intent
    state["intent_confidence"] = confidence
    state["intent_source"] = source
    _append_trace(
        state,
        "route_intent",
        {"intent": intent, "confidence": confidence, "source": source},
    )
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


def node_trend_agent(state: GraphState) -> GraphState:
    topic_state = state.get("topic_state", [])
    lowest = min(topic_state, key=lambda item: item.get("mastery", 1.0)) if topic_state else None
    state["agent_result"] = {
        "agent": "trend_agent",
        "summary": "Trend analysis prepared from topic mastery snapshot.",
        "focus_topic": lowest.get("topic") if lowest else None,
    }
    _append_trace(state, "trend_agent", {"focus_topic": state["agent_result"]["focus_topic"]})
    return state


def node_weakness_agent(state: GraphState) -> GraphState:
    diagnosis = state.get("diagnosis") or {}
    state["agent_result"] = {
        "agent": "weakness_agent",
        "summary": "Weakness diagnosis generated from error pressure and mastery.",
        "focus_topic": diagnosis.get("primary_topic"),
    }
    _append_trace(state, "weakness_agent", {"focus_topic": diagnosis.get("primary_topic")})
    return state


def node_pattern_agent(state: GraphState) -> GraphState:
    primary_issue = (state.get("diagnosis") or {}).get("primary_issue") or {}
    state["agent_result"] = {
        "agent": "pattern_agent",
        "summary": "Repeated error pattern identified from historical error features.",
        "pattern_topic": primary_issue.get("topic"),
    }
    _append_trace(state, "pattern_agent", {"pattern_topic": primary_issue.get("topic")})
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
    if intent == "TREND":
        return "trend"
    if intent == "WEAKNESS":
        return "weakness"
    if intent == "PATTERN":
        return "pattern"
    return "plan"


@lru_cache(maxsize=1)
def get_coach_graph2():
    """Build and cache the compiled graph (v2 with AOAI intent routing)."""
    workflow = StateGraph(dict)

    workflow.add_node("build_state", node_build_state)
    workflow.add_node("route_intent", node_route_intent)
    workflow.add_node("uncertainty_gate", node_uncertainty_gate)

    workflow.add_node("diagnosis", node_diagnosis)
    workflow.add_node("trend_agent", node_trend_agent)
    workflow.add_node("weakness_agent", node_weakness_agent)
    workflow.add_node("pattern_agent", node_pattern_agent)

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
            "trend": "trend_agent",
            "weakness": "diagnosis",
            "pattern": "diagnosis",
            "plan": "optimizer",
        },
    )

    workflow.add_edge("trend_agent", "finalize")

    workflow.add_edge("diagnosis", "weakness_agent")
    workflow.add_edge("weakness_agent", "pattern_agent")
    workflow.add_conditional_edges(
        "pattern_agent",
        lambda state: "pattern" if state.get("intent") == "PATTERN" else "weakness",
        {
            "pattern": "finalize",
            "weakness": "finalize",
        },
    )

    workflow.add_edge("optimizer", "planner")
    workflow.add_edge("planner", "evaluator")
    workflow.add_edge("evaluator", "execute_plan_action")
    workflow.add_edge("execute_plan_action", "finalize")
    workflow.add_edge("finalize", END)

    return workflow.compile()


def _debug_print_run_header(case_num: int, message: str, constraints: dict[str, Any]) -> None:
    print("\n" + "=" * 80)
    print(f"[DEBUG] Test Case #{case_num}")
    print(f"[DEBUG] Query: {message}")
    print(f"[DEBUG] Constraints: {constraints}")


def _debug_print_run_result(result: GraphState) -> None:
    print(f"[DEBUG] Intent: {result.get('intent')}")
    print(f"[DEBUG] Intent Confidence: {result.get('intent_confidence')}")
    print(f"[DEBUG] Intent Source: {result.get('intent_source')}")
    print(f"[DEBUG] Needs Clarification: {result.get('needs_clarification')}")

    diagnosis = result.get("diagnosis")
    if diagnosis:
        print(f"[DEBUG] Diagnosis: {diagnosis}")

    plan = result.get("plan")
    if plan:
        print(f"[DEBUG] Plan Steps: {len(plan.get('checklist', []))}")
        for idx, step in enumerate(plan.get("checklist", []), start=1):
            print(f"    {idx}. {step.get('step')}")

    action_result = result.get("action_result")
    if action_result:
        print(f"[DEBUG] Action Result: {action_result}")

    agent_result = result.get("agent_result")
    if agent_result:
        print(f"[DEBUG] Agent Result: {agent_result}")

    trace = result.get("tool_trace", [])
    print(f"[DEBUG] Tool Trace Count: {len(trace)}")
    for step in trace:
        print(f"  - {step.get('node')}: {step.get('details')}" )


if __name__ == "__main__":
    print("[DEBUG] Starting graph2.py test harness")
    print(f"[DEBUG] AZURE_OPENAI_DEPLOYMENT set: {bool(os.getenv('AZURE_OPENAI_DEPLOYMENT'))}")
    print(f"[DEBUG] AZURE_OPENAI_ENDPOINT set: {bool(os.getenv('AZURE_OPENAI_ENDPOINT'))}")
    print(f"[DEBUG] AZURE_OPENAI_API_KEY set: {bool(os.getenv('AZURE_OPENAI_API_KEY'))}")

    graph = get_coach_graph2()

    test_cases = [
        {
            "message": "I have 45 minutes. Make me a focused study plan for calculus.",
            "constraints": {"time_budget_min": 45},
        },
        {
            "message": "Why do I keep repeating careless mistakes in algebra?",
            "constraints": {"time_budget_min": 30},
        },
        {
            "message": "Am I improving in geometry over the last month?",
            "constraints": {"time_budget_min": 25},
        },
    ]

    for index, case in enumerate(test_cases, start=1):
        _debug_print_run_header(index, case["message"], case["constraints"])
        inputs = {
            "student_id": "demo-student-001",
            "run_id": f"graph2-debug-{index}",
            "message": case["message"],
            "window_days": 30,
            "constraints": case["constraints"],
        }

        try:
            result = graph.invoke(inputs)
            _debug_print_run_result(result)
        except Exception as exc:
            print(f"[DEBUG][ERROR] Graph run failed: {exc}")

    print("\n[DEBUG] graph2.py test harness finished")
