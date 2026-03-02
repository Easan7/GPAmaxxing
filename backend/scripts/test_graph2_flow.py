"""Smoke test runner for graph2 workflow.

Usage:
  python scripts/test_graph2_flow.py --student-id <uuid> [--window-days 30]

Runs core direct graph scenarios:
- trend question (no clarification)
- weakness question (no clarification)
- plan question with explicit details (no clarification)
- plan question with missing details (clarification expected), then continue with generic plan
"""

from __future__ import annotations

import argparse
import json
from uuid import uuid4

from app.agents.graph2 import get_coach_graph2


def _invoke(graph, student_id: str, message: str, window_days: int, constraints: dict | None = None, run_id: str | None = None):
    payload = {
        "student_id": student_id,
        "run_id": run_id or str(uuid4()),
        "message": message,
        "window_days": window_days,
        "constraints": constraints or {},
    }
    return graph.invoke(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run graph2 end-to-end flow checks.")
    parser.add_argument("--student-id", required=True, help="Student UUID")
    parser.add_argument("--window-days", type=int, default=30, help="Analytics lookback window")
    args = parser.parse_args()

    graph = get_coach_graph2()

    cases: list[dict] = [
        {
            "name": "trend",
            "message": "How has my performance changed this month?",
            "constraints": {},
        },
        {
            "name": "weakness",
            "message": "I am weak in requirements and UCD.",
            "constraints": {},
        },
        {
            "name": "plan_with_details",
            "message": "Make me a study plan for empathy in 60 minutes",
            "constraints": {},
        },
        {
            "name": "plan_needs_input",
            "message": "Make me a study plan",
            "constraints": {},
        },
    ]

    report: list[dict] = []

    for index, case in enumerate(cases, start=1):
        result = _invoke(
            graph=graph,
            student_id=args.student_id,
            message=case["message"],
            window_days=args.window_days,
            constraints=case["constraints"],
            run_id=f"graph2-flow-{index}",
        )

        entry = {
            "case": case["name"],
            "message": case["message"],
            "intent": result.get("intent"),
            "intent_source": result.get("intent_source"),
            "needs_clarification": bool(result.get("needs_clarification")),
            "clarification_question": result.get("clarification_question"),
            "artifact_type": result.get("artifact_type"),
            "plan": result.get("plan"),
            "action_result": result.get("action_result"),
            "trace": result.get("tool_trace"),
        }

        if case["name"] == "plan_needs_input" and entry["needs_clarification"]:
            follow_up_payload = dict(result)
            follow_up_payload["clarification_answer"] = {"generic_plan": True}
            follow_up_payload["needs_clarification"] = False
            follow_up = graph.invoke(follow_up_payload)
            entry["follow_up"] = {
                "intent": follow_up.get("intent"),
                "needs_clarification": bool(follow_up.get("needs_clarification")),
                "artifact_type": follow_up.get("artifact_type"),
                "plan": follow_up.get("plan"),
                "action_result": follow_up.get("action_result"),
                "trace": follow_up.get("tool_trace"),
            }

        report.append(entry)

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
