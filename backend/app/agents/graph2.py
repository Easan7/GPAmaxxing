"""LangGraph workflow with OpenAI intent routing.

This version replaces hardcoded intent routing with OpenAI classification,
then routes to intent-specific agent paths with deterministic fallbacks.
"""

from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

from langgraph.graph import END, START, StateGraph
from openai import OpenAI

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

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

def _append_trace(state: GraphState, node: str, details: dict[str, Any] | None = None) -> None:
    trace = state.get("tool_trace", [])
    trace.append({"node": node, "details": details or {}})
    state["tool_trace"] = trace


@lru_cache(maxsize=1)
def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Missing OPENAI_API_KEY")
    return OpenAI(api_key=api_key)


def _get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-4o-mini"


def _fallback_intent_heuristic(message: str) -> str:
    message = message.lower()
    if any(word in message for word in ["improving", "regress", "trend", "progress"]):
        return "TREND"
    if any(word in message for word in ["careless", "weak", "struggle", "mistake"]):
        return "WEAKNESS"
    if "why" in message and any(word in message for word in ["repeat", "again", "pattern"]):
        return "PATTERN"
    return "PLAN"


def _classify_intent_with_openai(message: str) -> tuple[str, float, str, str | None]:


    system_prompt = (
        "You are an intent classifier for a learning coach. "
        "Classify the query into exactly one of: TREND, WEAKNESS, PATTERN, PLAN. "
        "Return JSON only in this format: "
        '{"intent":"TREND|WEAKNESS|PATTERN|PLAN","confidence":0.0}. '
        "No markdown, no extra text."
    )

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=_get_openai_model(),
            max_completion_tokens=200,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            finish_reason = response.choices[0].finish_reason
            raise ValueError(f"Empty model content (finish_reason={finish_reason})")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            candidate = content
            fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if fence_match:
                candidate = fence_match.group(1)
            else:
                obj_match = re.search(r"\{.*\}", content, re.DOTALL)
                if obj_match:
                    candidate = obj_match.group(0)
            payload = json.loads(candidate)
        intent = str(payload.get("intent", "PLAN")).upper().strip()
        confidence = float(payload.get("confidence", 0.0))

        if intent not in ALLOWED_INTENTS:
            fallback = _fallback_intent_heuristic(message)
            return fallback, 0.3, "fallback_invalid_intent", "Invalid intent returned by model"

        confidence = max(0.0, min(1.0, confidence))
        return intent, confidence, "openai", None
    except Exception as exc:
        fallback = _fallback_intent_heuristic(message)
        return fallback, 0.3, "fallback_error", f"{type(exc).__name__}: {exc}"


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
    intent, confidence, source, error = _classify_intent_with_openai(message)
    state["intent"] = intent
    state["intent_confidence"] = confidence
    state["intent_source"] = source
    state["intent_error"] = error
    _append_trace(
        state,
        "route_intent",
        {
            "intent": intent,
            "confidence": confidence,
            "source": source,
            "error": state.get("intent_error"),
        },
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


def node_handle_trend(state: GraphState) -> GraphState:
    topic_state = state.get("topic_state", [])
    focus_topic = max(topic_state, key=lambda item: item.get("trend", -1.0)) if topic_state else None
    state["diagnosis"] = {
        "summary": "Trend analysis prepared from topic mastery snapshot.",
        "focus_topic": focus_topic.get("topic") if focus_topic else None,
        "trend": focus_topic.get("trend") if focus_topic else None,
    }
    state["artifact_type"] = "trend_report"
    state["artifact"] = {
        "agent": "trend_agent",
        "summary": "Trend analysis prepared from topic mastery snapshot.",
        "focus_topic": focus_topic.get("topic") if focus_topic else None,
        "topic_state": topic_state,
    }
    _append_trace(state, "handle_trend", {"focus_topic": state["artifact"].get("focus_topic")})
    return state


def node_handle_weakness(state: GraphState) -> GraphState:
    state = node_diagnosis(state)
    diagnosis = state.get("diagnosis") or {}
    state["artifact_type"] = "weakness_report"
    state["artifact"] = {
        "agent": "weakness_agent",
        "summary": "Weakness diagnosis generated from error pressure and mastery.",
        "focus_topic": diagnosis.get("primary_topic"),
        "primary_issue": diagnosis.get("primary_issue"),
    }
    _append_trace(state, "handle_weakness", {"focus_topic": diagnosis.get("primary_topic")})
    return state


def node_handle_pattern(state: GraphState) -> GraphState:
    state = node_diagnosis(state)
    primary_issue = (state.get("diagnosis") or {}).get("primary_issue") or {}
    state["artifact_type"] = "pattern_report"
    state["artifact"] = {
        "agent": "pattern_agent",
        "summary": "Repeated error pattern identified from historical error features.",
        "pattern_topic": primary_issue.get("topic"),
        "issue": primary_issue,
    }
    _append_trace(state, "handle_pattern", {"pattern_topic": primary_issue.get("topic")})
    return state


def _build_plan_artifact_from_allocation(allocation: list[dict]) -> dict:
    checklist = [
        {
            "step": f"Practice {item['topic']} for {item['minutes']} minutes",
            "topic": item["topic"],
            "minutes": item["minutes"],
        }
        for item in allocation
    ]
    return {
        "title": "Focused Session Plan",
        "checklist": checklist,
    }


def node_handle_plan(state: GraphState) -> GraphState:
    coach_state = CoachRunState.model_validate(state)
    allocation = optimize_time_allocation(coach_state.topic_state, coach_state.constraints)
    state["allocation"] = allocation
    diagnosis = state.get("diagnosis") or {}
    if not allocation:
        note = "missing time budget"
    else:
        note = "approved"

    diagnosis["evaluation"] = note
    state["diagnosis"] = diagnosis
    state["plan"] = _build_plan_artifact_from_allocation(allocation)
    state["artifact_type"] = "study_plan"
    state["artifact"] = state.get("plan")

    constraints = state.get("constraints") or {}
    if note != "approved":
        _append_trace(state, "handle_plan", {"result": note, "executed": False})
        return state

    if "time_budget_min" not in constraints or not allocation:
        _append_trace(state, "handle_plan", {"result": note, "executed": False, "reason": "missing_guardrails"})
        return state

    result = create_study_session(
        student_id=str(state.get("student_id", "")),
        plan=state.get("plan") or {},
        run_id=str(state.get("run_id", "")),
    )
    state["action_result"] = result
    _append_trace(state, "handle_plan", {"result": note, "executed": True, "session_id": result.get("session_id")})
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
    """Build and cache the compiled graph (v2 with OpenAI intent routing)."""
    workflow = StateGraph(dict)

    # Core orchestration stages: analytics snapshot -> intent classification -> clarification gate.
    workflow.add_node("build_student_state", node_build_state)
    workflow.add_node("classify_intent", node_route_intent)
    workflow.add_node("uncertainty_gate", node_uncertainty_gate)

    # One deterministic handler per intent branch.
    workflow.add_node("handle_trend", node_handle_trend)
    workflow.add_node("handle_weakness", node_handle_weakness)
    workflow.add_node("handle_pattern", node_handle_pattern)
    workflow.add_node("handle_plan", node_handle_plan)
    workflow.add_node("finalize", node_finalize)

    workflow.add_edge(START, "build_student_state")
    workflow.add_edge("build_student_state", "classify_intent")
    workflow.add_edge("classify_intent", "uncertainty_gate")

    workflow.add_conditional_edges(
        "uncertainty_gate",
        _after_uncertainty,
        {
            # Pause immediately for clarification; otherwise route by classifier intent.
            "needs_input": END,
            "trend": "handle_trend",
            "weakness": "handle_weakness",
            "pattern": "handle_pattern",
            "plan": "handle_plan",
        },
    )

    workflow.add_edge("handle_trend", "finalize")
    workflow.add_edge("handle_weakness", "finalize")
    workflow.add_edge("handle_pattern", "finalize")
    workflow.add_edge("handle_plan", "finalize")
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

    print(f"[DEBUG] Artifact Type: {result.get('artifact_type')}")
    artifact = result.get("artifact")
    if artifact:
        print(f"[DEBUG] Artifact: {artifact}")

    trace = result.get("tool_trace", [])
    print(f"[DEBUG] Tool Trace Count: {len(trace)}")
    for step in trace:
        print(f"  - {step.get('node')}: {step.get('details')}" )


if __name__ == "__main__":
    print("[DEBUG] Starting graph2.py test harness")
    print(f"[DEBUG] OPENAI_MODEL set: {bool(os.getenv('OPENAI_MODEL') or os.getenv('OPENAI_CHAT_MODEL'))}")
    print(f"[DEBUG] OPENAI_API_KEY set: {bool(os.getenv('OPENAI_API_KEY'))}")

    graph = get_coach_graph2()

    test_cases = [
        {
            "message": "I have 45 minutes. Make me a focused study plan for calculus.",
            "constraints": {"time_budget_min": 45},
        },
        {
            "message": "I feel weak in geometry and keep struggling with proofs.",
            "constraints": {"time_budget_min": 30},
        },
        {
            "message": "Why does this error pattern repeat again in algebra?",
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
