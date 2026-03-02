"""Run graph2 with a custom prompt and print statistics + final worded response.

Examples:
  python scripts/run_graph2_prompt.py --student-id <uuid> --prompt "How am I doing in UCD?"
  python scripts/run_graph2_prompt.py --student-id <uuid> --prompt "Make me a plan" --auto-generic-plan
  python scripts/run_graph2_prompt.py --student-id <uuid> --prompt "Make me a plan" --clarification-json '{"time_budget_min":60,"focus_topics":["Empathy"]}'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import OpenAI

backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.agents.graph2 import get_coach_graph2


def _get_openai_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def _get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-4o-mini"


def _generate_worded_response(final_state: dict[str, Any]) -> str:
    topic_state = final_state.get("topic_state") or []
    error_state = final_state.get("error_state") or []
    diagnosis = final_state.get("diagnosis") or {}
    artifact = final_state.get("artifact") or {}

    artifact_response = artifact.get("response") if isinstance(artifact, dict) else None
    if isinstance(artifact_response, str) and artifact_response.strip():
        return artifact_response.strip()

    client = _get_openai_client()
    def _fallback_text() -> str:
        primary_focus = diagnosis.get("primary_topic") or diagnosis.get("focus_topic") or "N/A"
        summary = str(diagnosis.get("summary") or "I analyzed your latest performance state.")
        return (
            f"{summary} "
            f"Primary focus topic: {primary_focus}. "
            "Next step: spend your next session on the weakest topic and review recent mistakes first."
        )

    if client is None:
        return _fallback_text()

    system_prompt = (
        "You are a concise learning coach. "
        "Create a practical response grounded only in provided analytics. "
        "Mention key strengths/weaknesses and a next step."
    )

    user_payload = {
        "intent": final_state.get("intent"),
        "intent_confidence": final_state.get("intent_confidence"),
        "message": final_state.get("message"),
        "diagnosis": diagnosis,
        "artifact": artifact,
        "topic_state": topic_state,
        "error_state": error_state,
        "constraints": final_state.get("constraints"),
    }

    try:
        response = client.chat.completions.create(
            model=_get_openai_model(),
            max_completion_tokens=320,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        return content or _fallback_text()
    except Exception as exc:
        return f"{_fallback_text()} (LLM fallback reason: {type(exc).__name__}: {exc})"


def _run_graph(
    student_id: str,
    prompt: str,
    window_days: int,
    constraints: dict[str, Any],
    clarification_answer: dict[str, Any] | None,
    auto_generic_plan: bool,
) -> dict[str, Any]:
    graph = get_coach_graph2()

    initial_state = {
        "run_id": str(uuid4()),
        "student_id": student_id,
        "message": prompt,
        "window_days": window_days,
        "constraints": constraints,
    }

    first = graph.invoke(initial_state)

    if not bool(first.get("needs_clarification")):
        return first

    answer = clarification_answer
    if answer is None and auto_generic_plan:
        answer = {"generic_plan": True}

    if answer is None:
        return first

    resumed = dict(first)
    resumed["clarification_answer"] = answer
    resumed["needs_clarification"] = False
    return graph.invoke(resumed)


def _ensure_completed_state(
    final_state: dict[str, Any],
    student_id: str,
    prompt: str,
    window_days: int,
    constraints: dict[str, Any],
) -> dict[str, Any]:
    """Force completion by auto-continuing plan clarifications when needed."""
    if not bool(final_state.get("needs_clarification")):
        return final_state

    intents = final_state.get("intents") or []
    normalized_intents = {str(item).upper().strip() for item in intents if str(item).strip()}
    primary_intent = str(final_state.get("intent") or "").upper().strip()
    plan_requested = primary_intent == "PLAN" or "PLAN" in normalized_intents

    if not plan_requested:
        return final_state

    graph = get_coach_graph2()
    resumed = dict(final_state)
    resumed["clarification_answer"] = {"generic_plan": True}
    resumed["needs_clarification"] = False
    return graph.invoke(resumed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run graph2 for one custom prompt.")
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--constraints-json", default="{}", help="JSON object")
    parser.add_argument("--clarification-json", default=None, help="Optional JSON object")
    parser.add_argument("--auto-generic-plan", action="store_true")
    parser.add_argument("--final-only", action="store_true", help="Print only final worded response")
    parser.add_argument(
        "--force-complete",
        action="store_true",
        help="If clarification is needed, auto-continue plan with generic settings",
    )
    args = parser.parse_args()

    constraints = json.loads(args.constraints_json or "{}")
    clarification_answer = json.loads(args.clarification_json) if args.clarification_json else None

    final_state = _run_graph(
        student_id=args.student_id,
        prompt=args.prompt,
        window_days=args.window_days,
        constraints=constraints,
        clarification_answer=clarification_answer,
        auto_generic_plan=args.auto_generic_plan,
    )

    if args.force_complete:
        final_state = _ensure_completed_state(
            final_state=final_state,
            student_id=args.student_id,
            prompt=args.prompt,
            window_days=args.window_days,
            constraints=constraints,
        )

    response_text = _generate_worded_response(final_state)

    if args.final_only:
        print(response_text)
        return

    output = {
        "intent": final_state.get("intent"),
        "intents": final_state.get("intents"),
        "intent_confidence": final_state.get("intent_confidence"),
        "intent_source": final_state.get("intent_source"),
        "needs_clarification": final_state.get("needs_clarification"),
        "clarification_question": final_state.get("clarification_question"),
        "statistics_used": {
            "topic_state": final_state.get("topic_state"),
            "error_state": final_state.get("error_state"),
            "diagnosis": final_state.get("diagnosis"),
            "artifact": final_state.get("artifact"),
            "plan": final_state.get("plan"),
            "action_result": final_state.get("action_result"),
        },
        "worded_response": response_text,
        "tool_trace": final_state.get("tool_trace"),
    }

    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
