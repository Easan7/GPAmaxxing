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
    from app.config import get_settings
    from app.storage.supabase_client import create_supabase_client
    from app.services.optimizer import optimize_time_allocation
    from app.services.session_service import create_study_session
    from app.services.state_builder import build_state
except ModuleNotFoundError:
    backend_root = Path(__file__).resolve().parents[2]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from app.schemas.state import CoachRunState
    from app.config import get_settings
    from app.storage.supabase_client import create_supabase_client
    from app.services.optimizer import optimize_time_allocation
    from app.services.session_service import create_study_session
    from app.services.state_builder import build_state

GraphState = dict[str, Any]
ALLOWED_INTENTS = {"TREND", "WEAKNESS", "PLAN"}

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
    if any(word in message for word in ["improving", "regress", "trend", "progress", "changed", "performance"]):
        return "TREND"
    if any(word in message for word in ["careless", "weak", "struggle", "mistake", "pattern", "repeat"]):
        return "WEAKNESS"
    return "PLAN"


def _question_content(question_obj: dict) -> str:
    for key in ["question_text", "prompt", "stem", "content", "text", "title"]:
        value = question_obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    tags = question_obj.get("tags") or []
    question_type = question_obj.get("question_type")
    difficulty = question_obj.get("difficulty")
    parts = [
        f"type={question_type}" if question_type else None,
        f"difficulty={difficulty}" if difficulty else None,
        f"tags={','.join(str(tag) for tag in tags)}" if tags else None,
    ]
    return "; ".join(part for part in parts if part) or "(no question text available)"


def _fetch_attempt_evidence(student_id: str, window_days: int, limit: int = 120) -> dict[str, Any]:
    """Fetch real attempts + question content for response grounding."""
    try:
        settings = get_settings()
        client = create_supabase_client(settings)
        rows = (
            client.table("attempts")
            .select("id,correct,confidence,time_taken_sec,attempted_at,questions(*)")
            .eq("student_id", student_id)
            .order("attempted_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        return {
            "total_attempts": 0,
            "total_correct": 0,
            "total_wrong": 0,
            "accuracy": 0.0,
            "right_samples": [],
            "wrong_samples": [],
            "topic_wrong_counts": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

    filtered_rows: list[dict] = []
    for row in rows:
        question = row.get("questions")
        if isinstance(question, list):
            question = question[0] if question else {}
        if not isinstance(question, dict):
            question = {}

        filtered_rows.append(
            {
                "attempted_at": row.get("attempted_at"),
                "correct": bool(row.get("correct", False)),
                "confidence": row.get("confidence"),
                "time_taken_sec": row.get("time_taken_sec"),
                "topic": question.get("topic") or "Unknown",
                "question_type": question.get("question_type"),
                "difficulty": question.get("difficulty"),
                "tags": question.get("tags") or [],
                "question_content": _question_content(question),
            }
        )

    if window_days > 0:
        cutoff_marker = f"window_days={window_days}"
    else:
        cutoff_marker = "window_days=all"

    right = [row for row in filtered_rows if row["correct"]]
    wrong = [row for row in filtered_rows if not row["correct"]]

    topic_wrong_counts: dict[str, int] = {}
    for row in wrong:
        topic = str(row.get("topic") or "Unknown")
        topic_wrong_counts[topic] = topic_wrong_counts.get(topic, 0) + 1

    total_attempts = len(filtered_rows)
    total_correct = len(right)
    total_wrong = len(wrong)
    accuracy = (total_correct / total_attempts) if total_attempts else 0.0

    return {
        "window": cutoff_marker,
        "total_attempts": total_attempts,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
        "accuracy": round(accuracy, 4),
        "right_samples": right[:6],
        "wrong_samples": wrong[:6],
        "topic_wrong_counts": dict(sorted(topic_wrong_counts.items(), key=lambda item: item[1], reverse=True)),
    }


def _deterministic_fallback_response(intent: str, diagnosis: dict | None, plan: dict | None) -> str:
    if intent == "PLAN":
        checklist = (plan or {}).get("checklist") or []
        if checklist:
            first = checklist[0]
            return (
                "I prepared a focused plan based on your analytics. "
                f"Start with {first.get('topic')} for {first.get('minutes')} minutes, then continue through the checklist."
            )
        return "I can create a study plan once a time budget is provided or generic planning is selected."

    focus = (diagnosis or {}).get("primary_topic") or (diagnosis or {}).get("focus_topic") or "your weakest topic"
    return (
        "Based on your latest analytics and recent attempts, "
        f"focus first on {focus}, then review similar mistakes and reattempt those question types."
    )


def _generate_branch_response(state: GraphState, branch: str) -> str:
    """Generate final user-facing response using the same OpenAI model."""
    payload = {
        "branch": branch,
        "intent": state.get("intent"),
        "message": state.get("message"),
        "diagnosis": state.get("diagnosis"),
        "plan": state.get("plan"),
        "topic_state": state.get("topic_state"),
        "error_state": state.get("error_state"),
        "attempt_evidence": state.get("attempt_evidence"),
        "constraints": state.get("constraints"),
    }

    system_prompt = (
        "You are a concise learning coach. "
        "Use the provided analytics, attempt evidence, and original query. "
        "For TREND/WEAKNESS: explain what they struggle with, why (mastery/trend/decay/errors), and give short actionable next steps. "
        "For PLAN: return a concise structured plan summary with topic-minute allocations and why these topics were chosen."
    )

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=_get_openai_model(),
            max_completion_tokens=360,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            return text
    except Exception:
        pass

    return _deterministic_fallback_response(
        intent=str(state.get("intent") or branch),
        diagnosis=state.get("diagnosis") or {},
        plan=state.get("plan") or {},
    )


def _extract_time_budget_from_message(message: str) -> int | None:
    normalized = message.lower()
    hour_match = re.search(r"(\d+)\s*(hour|hours|hr|hrs)\b", normalized)
    if hour_match:
        return int(hour_match.group(1)) * 60

    min_match = re.search(r"(\d+)\s*(minute|minutes|min|mins)\b", normalized)
    if min_match:
        return int(min_match.group(1))

    bare_number = re.search(r"\b(\d{2,3})\b", normalized)
    if bare_number:
        value = int(bare_number.group(1))
        if 10 <= value <= 240:
            return value

    return None


def _extract_focus_topics_from_message(message: str, topic_state: list[dict]) -> list[str]:
    normalized = message.lower()
    found: list[str] = []
    for item in topic_state:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        if topic.lower() in normalized:
            found.append(topic)
    return sorted(set(found))


def _normalize_plan_constraints(
    message: str,
    constraints: dict | None,
    topic_state: list[dict],
    clarification_answer: dict | None,
) -> tuple[dict, bool, dict | None]:
    merged = dict(constraints or {})

    if not isinstance(merged.get("time_budget_min"), int):
        extracted_budget = _extract_time_budget_from_message(message)
        if extracted_budget is not None:
            merged["time_budget_min"] = extracted_budget

    extracted_topics = _extract_focus_topics_from_message(message, topic_state)
    if extracted_topics and not merged.get("focus_topics"):
        merged["focus_topics"] = extracted_topics

    if clarification_answer:
        if isinstance(clarification_answer.get("time_budget_min"), int):
            merged["time_budget_min"] = int(clarification_answer["time_budget_min"])

        follow_up_topics = clarification_answer.get("focus_topics")
        if isinstance(follow_up_topics, list):
            cleaned_topics = [str(topic) for topic in follow_up_topics if str(topic).strip()]
            if cleaned_topics:
                merged["focus_topics"] = sorted(set(cleaned_topics))

        if bool(clarification_answer.get("generic_plan") or clarification_answer.get("skip_details")):
            merged["generic_plan"] = True

    has_time = isinstance(merged.get("time_budget_min"), int) and merged.get("time_budget_min", 0) > 0
    generic_plan = bool(merged.get("generic_plan"))

    if has_time:
        return merged, False, None

    if generic_plan:
        return merged, False, None

    question = {
        "prompt": "Share time and optional focus topics for a tailored plan, or continue with a generic plan.",
        "field": "plan_details",
        "expected": {
            "time_budget_min": "integer (optional)",
            "focus_topics": "string[] (optional)",
            "generic_plan": "boolean (set true to skip details)",
        },
        "topic_options": [item.get("topic") for item in topic_state if item.get("topic")],
        "time_options_min": [20, 30, 45, 60, 90, 120],
    }
    return merged, True, question


def _classify_intent_with_openai(message: str) -> tuple[str, float, str, str | None]:
    system_prompt = (
        "You are an intent classifier for a learning coach. "
        "Classify the query into exactly one of: TREND, WEAKNESS, PLAN. "
        "Return JSON only in this format: "
        '{"intent":"TREND|WEAKNESS|PLAN","confidence":0.0}. '
        "No markdown, no extra text."
    )

    def _parse_intent_payload(text: str) -> tuple[str, float]:
        candidate = text.strip()
        if not candidate:
            raise ValueError("Empty intent payload")

        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
            if fence_match:
                candidate = fence_match.group(1)
            else:
                obj_match = re.search(r"\{.*\}", candidate, re.DOTALL)
                if obj_match:
                    candidate = obj_match.group(0)
            payload = json.loads(candidate)

        intent = str(payload.get("intent", "PLAN")).upper().strip()
        confidence = float(payload.get("confidence", 0.0))
        return intent, max(0.0, min(1.0, confidence))

    try:
        client = _get_openai_client()
        last_error = None
        for attempt in range(2):
            try:
                request_kwargs = {
                    "model": _get_openai_model(),
                    "max_completion_tokens": 320 if attempt == 0 else 220,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                }
                if attempt == 0:
                    request_kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**request_kwargs)
                content = (response.choices[0].message.content or "").strip()
                if not content:
                    finish_reason = response.choices[0].finish_reason
                    raise ValueError(f"Empty model content (finish_reason={finish_reason})")

                intent, confidence = _parse_intent_payload(content)
                if intent not in ALLOWED_INTENTS:
                    raise ValueError(f"Invalid intent returned: {intent}")

                return intent, confidence, "openai", None
            except Exception as exc:  # noqa: PERF203 - explicit retry with captured context
                last_error = exc

        if last_error is not None:
            raise last_error

        if intent not in ALLOWED_INTENTS:
            fallback = _fallback_intent_heuristic(message)
            return fallback, 0.3, "fallback_invalid_intent", "Invalid intent returned by model"
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
    attempt_evidence = _fetch_attempt_evidence(
        student_id=str(state.get("student_id", "")),
        window_days=int(state.get("window_days", 30)),
    )
    state["attempt_evidence"] = attempt_evidence
    _append_trace(
        state,
        "build_state",
        {
            "topics": len(topic_state),
            "errors": len(error_state),
            "attempts": attempt_evidence.get("total_attempts", 0),
            "accuracy": attempt_evidence.get("accuracy", 0.0),
        },
    )
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

    merged_constraints = dict(coach_state.constraints or {})
    needs = False
    question = None

    if coach_state.intent == "PLAN":
        merged_constraints, needs, question = _normalize_plan_constraints(
            message=coach_state.message,
            constraints=coach_state.constraints,
            topic_state=[item.model_dump() for item in coach_state.topic_state],
            clarification_answer=coach_state.clarification_answer,
        )

    state["constraints"] = merged_constraints
    state["needs_clarification"] = needs
    state["clarification_question"] = question
    _append_trace(
        state,
        "uncertainty_gate",
        {
            "needs_clarification": needs,
            "intent": coach_state.intent,
            "has_time_budget": "time_budget_min" in merged_constraints,
            "has_focus_topics": bool(merged_constraints.get("focus_topics")),
            "generic_plan": bool(merged_constraints.get("generic_plan")),
        },
    )
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
        "response": _generate_branch_response(state, "TREND"),
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
        "response": _generate_branch_response(state, "WEAKNESS"),
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
    constraints = dict(coach_state.constraints or {})

    if (not isinstance(constraints.get("time_budget_min"), int) or constraints.get("time_budget_min", 0) <= 0) and bool(
        constraints.get("generic_plan")
    ):
        constraints["time_budget_min"] = 45

    focus_topics = {str(topic) for topic in (constraints.get("focus_topics") or [])}
    if focus_topics:
        filtered_topic_state = [item for item in coach_state.topic_state if item.topic in focus_topics]
        candidate_topic_state = filtered_topic_state or coach_state.topic_state
    else:
        candidate_topic_state = coach_state.topic_state

    allocation = optimize_time_allocation(candidate_topic_state, constraints)
    state["allocation"] = allocation
    diagnosis = state.get("diagnosis") or {}
    if not allocation:
        note = "missing time budget"
    else:
        note = "approved"

    diagnosis["evaluation"] = note
    state["diagnosis"] = diagnosis
    state["plan"] = _build_plan_artifact_from_allocation(allocation)
    if state.get("plan"):
        state["plan"]["response"] = _generate_branch_response(state, "PLAN")
    state["artifact_type"] = "study_plan"
    state["artifact"] = state.get("plan")

    state["constraints"] = constraints
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
            "plan": "handle_plan",
        },
    )

    workflow.add_edge("handle_trend", "finalize")
    workflow.add_edge("handle_weakness", "finalize")
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
            "message": "Build me a study plan.",
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
