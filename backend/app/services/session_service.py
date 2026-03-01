"""Study session action service.

Creates a study session from planner output.
"""

from __future__ import annotations

from uuid import uuid4

from app.config import get_settings
from app.storage.supabase_client import create_supabase_client


def _extract_goal(plan: dict) -> str:
    return str(plan.get("title") or "Focused Session Plan")


def create_study_session(student_id: str, plan: dict, run_id: str) -> dict:
    """Create session header and items from a plan.

    TODO: Add stricter validation and richer error handling/retry policy.
    """
    checklist = plan.get("checklist", []) if isinstance(plan, dict) else []
    session_id = str(uuid4())
    items_created = len(checklist)

    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        return {
            "session_id": session_id,
            "items_created": items_created,
            "persisted": False,
            "reason": "missing_supabase_config",
        }

    try:
        client = create_supabase_client(settings)

        client.table("study_sessions").insert(
            {
                "id": session_id,
                "student_id": student_id,
                "source_run_id": run_id,
                "status": "active",
                "goal": _extract_goal(plan),
            }
        ).execute()

        item_rows = []
        for index, step in enumerate(checklist):
            item_rows.append(
                {
                    "id": str(uuid4()),
                    "session_id": session_id,
                    "topic": step.get("topic"),
                    "expected_minutes": int(step.get("minutes", 0)),
                    "order_index": index,
                    "status": "pending",
                }
            )

        if item_rows:
            client.table("session_items").insert(item_rows).execute()

        return {
            "session_id": session_id,
            "items_created": len(item_rows),
            "persisted": True,
        }
    except Exception:
        # TODO: Replace broad exception catch with typed Supabase exceptions.
        return {
            "session_id": session_id,
            "items_created": items_created,
            "persisted": False,
            "reason": "supabase_insert_failed",
        }
