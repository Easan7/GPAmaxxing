from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.models.question_gen.generate import generate_and_insert_questions
from app.storage.supabase_client import create_supabase_client


QUESTION_SET_MARKERS = ["question", "mcq", "quiz", "scenario", "timed"]
DRILL_MARKERS = ["drill", "sprint", "rapid"]
MISTAKE_LOG_MARKERS = ["mistake log", "review mistakes", "error log"]


def _coerce_uuid_text(value: str) -> str:
    return str(value).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _classify_item_type(instructions: str) -> str:
    text = str(instructions or "").lower()
    if any(marker in text for marker in QUESTION_SET_MARKERS):
        return "question_set"
    if any(marker in text for marker in MISTAKE_LOG_MARKERS):
        return "mistake_log"
    if any(marker in text for marker in DRILL_MARKERS):
        return "drill"
    return "review"


def _date_for_day(start: date, day_number: int) -> date:
    day = max(1, int(day_number or 1))
    return start + timedelta(days=day - 1)


def _build_plan_item_rows(*, plan_id: str, plan: dict[str, Any], start_date: date) -> list[dict[str, Any]]:
    daily_schedule = list(plan.get("daily_schedule") or [])
    topic_narratives = dict((plan.get("plan_explanation") or {}).get("topic_narratives") or {})

    rows: list[dict[str, Any]] = []
    if daily_schedule:
        for day_block in daily_schedule:
            day_number = _safe_int(day_block.get("day"), 1)
            day_date = _date_for_day(start_date, day_number)
            for sort_order, topic_row in enumerate(day_block.get("topics") or [], start=1):
                topic = str(topic_row.get("topic") or "").strip()
                minutes = _safe_int(topic_row.get("minutes"), 0)
                task_text = str(topic_row.get("study_task") or "").strip()
                if not topic:
                    continue

                item_type = _classify_item_type(task_text)
                rows.append(
                    {
                        "id": str(uuid4()),
                        "plan_id": plan_id,
                        "day_date": day_date.isoformat(),
                        "sort_order": sort_order,
                        "topic": topic,
                        "minutes": minutes,
                        "item_type": item_type,
                        "title": f"{topic} - {item_type.replace('_', ' ').title()}",
                        "instructions": task_text or f"Study {topic} for {minutes} minutes.",
                        "status": "todo",
                        "completed_at": None,
                        "rationale": str(topic_narratives.get(topic) or "").strip() or None,
                        "metadata": {
                            "day": day_number,
                            "source": "plan_daily_schedule",
                            "question_type": "mcq",
                            "difficulty": "medium",
                            "tags": [topic],
                            "question_target_count": max(3, min(8, max(1, minutes // 15))),
                        },
                    }
                )
        return rows

    checklist = list(plan.get("checklist") or [])
    for sort_order, row in enumerate(checklist, start=1):
        topic = str(row.get("topic") or "").strip()
        minutes = _safe_int(row.get("minutes"), 0)
        if not topic:
            continue
        rows.append(
            {
                "id": str(uuid4()),
                "plan_id": plan_id,
                "day_date": start_date.isoformat(),
                "sort_order": sort_order,
                "topic": topic,
                "minutes": minutes,
                "item_type": "review",
                "title": f"{topic} - Review",
                "instructions": str(row.get("step") or f"Study {topic} for {minutes} minutes.").strip(),
                "status": "todo",
                "completed_at": None,
                "rationale": str(topic_narratives.get(topic) or "").strip() or None,
                "metadata": {
                    "day": 1,
                    "source": "plan_checklist",
                    "question_type": "mcq",
                    "difficulty": "medium",
                    "tags": [topic],
                    "question_target_count": max(3, min(8, max(1, minutes // 15))),
                },
            }
        )

    return rows


def _find_existing_question_ids(
    client: Any,
    *,
    topic: str,
    difficulty: str,
    question_type: str,
    tags: list[str],
    needed: int,
) -> list[str]:
    query = client.table("questions").select("id").eq("topic", topic).limit(max(needed * 3, 20))

    if difficulty:
        query = query.eq("difficulty", difficulty)
    if question_type:
        query = query.eq("question_type", question_type)
    if tags:
        query = query.contains("tags", tags[:3])

    result = query.execute()
    rows = result.data or []
    question_ids = [str(row.get("id")) for row in rows if str(row.get("id") or "").strip()]
    return question_ids[:needed]


def _attach_questions_to_item(client: Any, *, item: dict[str, Any]) -> int:
    metadata = dict(item.get("metadata") or {})
    topic = str(item.get("topic") or "").strip()
    difficulty = str(metadata.get("difficulty") or "medium").strip()
    question_type = str(metadata.get("question_type") or "mcq").strip()
    tags = [str(tag).strip() for tag in (metadata.get("tags") or [topic]) if str(tag).strip()]
    needed = max(2, min(10, _safe_int(metadata.get("question_target_count"), 4)))

    existing_ids = _find_existing_question_ids(
        client,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        tags=tags,
        needed=needed,
    )

    if len(existing_ids) < needed:
        generated = generate_and_insert_questions(
            topic=topic,
            difficulty=difficulty,
            question_type=question_type,
            tags=tags,
            n=needed - len(existing_ids),
        )
        existing_ids.extend(generated)

    selected_ids = existing_ids[:needed]
    link_rows = [
        {
            "id": str(uuid4()),
            "plan_item_id": item["id"],
            "question_id": qid,
            "sort_order": idx,
            "reason": "matched_topic_difficulty_tags",
        }
        for idx, qid in enumerate(selected_ids, start=1)
    ]
    if link_rows:
        client.table("study_plan_item_questions").insert(link_rows).execute()
    return len(link_rows)


def persist_study_plan(
    *,
    student_id: str,
    query: str,
    window_days: int,
    constraints: dict[str, Any] | None,
    analytics_snapshot: dict[str, Any] | None,
    llm_model: str | None,
    llm_response: str,
    llm_response_json: dict[str, Any],
    llm_prompt_version: str = "plan_v1",
) -> dict[str, Any]:
    settings = get_settings()
    client = create_supabase_client(settings)

    start_date = date.today()
    horizon_days = max(1, _safe_int(llm_response_json.get("time_horizon_days"), 1))
    end_date = start_date + timedelta(days=horizon_days - 1)

    plan_id = str(uuid4())
    plan_row = {
        "id": plan_id,
        "student_id": _coerce_uuid_text(student_id),
        "query": query,
        "intent": "PLAN",
        "window_days": int(window_days or 0),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "constraints": constraints or {},
        "analytics_snapshot": analytics_snapshot or {},
        "llm_prompt_version": llm_prompt_version,
        "llm_model": llm_model,
        "llm_response": llm_response,
        "llm_response_json": llm_response_json,
    }

    item_rows = _build_plan_item_rows(plan_id=plan_id, plan=llm_response_json, start_date=start_date)

    try:
        client.table("study_plans").insert(plan_row).execute()
        if item_rows:
            client.table("study_plan_items").insert(item_rows).execute()

        attached_count = 0

        return {
            "plan_id": plan_id,
            "persisted": True,
            "items_created": len(item_rows),
            "questions_attached": attached_count,
        }
    except Exception as exc:
        try:
            client.table("study_plans").delete().eq("id", plan_id).execute()
        except Exception:
            pass
        return {
            "plan_id": plan_id,
            "persisted": False,
            "reason": f"persist_failed:{type(exc).__name__}",
        }


def list_study_plans(*, student_id: str, limit: int = 20) -> list[dict[str, Any]]:
    settings = get_settings()
    client = create_supabase_client(settings)
    rows = (
        client.table("study_plans")
        .select("id,created_at,window_days,start_date,end_date")
        .eq("student_id", _coerce_uuid_text(student_id))
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 100)))
        .execute()
        .data
        or []
    )
    return rows


def get_study_plan_detail(*, plan_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    client = create_supabase_client(settings)

    plan_rows = client.table("study_plans").select("*").eq("id", plan_id).limit(1).execute().data or []
    if not plan_rows:
        return None

    plan = dict(plan_rows[0])
    item_rows = (
        client.table("study_plan_items")
        .select("*")
        .eq("plan_id", plan_id)
        .order("day_date", desc=False)
        .order("sort_order", desc=False)
        .execute()
        .data
        or []
    )

    item_ids = [str(item.get("id")) for item in item_rows if str(item.get("id") or "").strip()]
    links: list[dict[str, Any]] = []
    if item_ids:
        links = (
            client.table("study_plan_item_questions")
            .select("plan_item_id,question_id,sort_order,reason")
            .in_("plan_item_id", item_ids)
            .order("sort_order", desc=False)
            .execute()
            .data
            or []
        )

    links_by_item: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        key = str(link.get("plan_item_id") or "")
        if not key:
            continue
        links_by_item.setdefault(key, []).append(link)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in item_rows:
        item_id = str(item.get("id") or "")
        enriched = dict(item)
        enriched["questions"] = links_by_item.get(item_id, [])
        day_key = str(item.get("day_date") or "unscheduled")
        grouped.setdefault(day_key, []).append(enriched)

    plan["days"] = [{"day_date": day, "items": items} for day, items in sorted(grouped.items(), key=lambda kv: kv[0])]
    return plan


def update_plan_item_status(*, item_id: str, student_id: str, status: str, note: str | None = None) -> dict[str, Any] | None:
    if status not in {"todo", "doing", "done", "skipped"}:
        raise ValueError("invalid_status")

    settings = get_settings()
    client = create_supabase_client(settings)

    completed_at = datetime.now(timezone.utc).isoformat() if status == "done" else None
    existing = client.table("study_plan_items").select("id").eq("id", item_id).limit(1).execute().data or []
    if not existing:
        return None

    updated = (
        client.table("study_plan_items")
        .update({"status": status, "completed_at": completed_at})
        .eq("id", item_id)
        .execute()
        .data
        or []
    )
    if not updated:
        refreshed = client.table("study_plan_items").select("*").eq("id", item_id).limit(1).execute().data or []
        if not refreshed:
            return None
        updated = refreshed

    event_type_map = {
        "done": "marked_done",
        "todo": "marked_todo",
        "skipped": "marked_skipped",
        "doing": "note",
    }
    event_type = event_type_map[status]
    event_row = {
        "id": str(uuid4()),
        "plan_item_id": item_id,
        "student_id": _coerce_uuid_text(student_id),
        "event_type": event_type,
        "note": note,
    }
    try:
        client.table("study_plan_item_events").insert(event_row).execute()
    except Exception:
        pass

    return dict(updated[0])


def get_item_questions_for_attempt(*, item_id: str) -> list[dict[str, Any]]:
    settings = get_settings()
    client = create_supabase_client(settings)

    links = (
        client.table("study_plan_item_questions")
        .select("question_id,sort_order")
        .eq("plan_item_id", item_id)
        .order("sort_order", desc=False)
        .execute()
        .data
        or []
    )
    question_ids = [str(link.get("question_id")) for link in links if str(link.get("question_id") or "").strip()]
    if not question_ids:
        return []

    questions = (
        client.table("questions")
        .select("id,question_text,prompt,topic,difficulty,question_type,tags")
        .in_("id", question_ids)
        .execute()
        .data
        or []
    )
    question_by_id = {str(row.get("id")): row for row in questions}

    options = (
        client.table("question_options")
        .select("id,question_id,label,option_text")
        .in_("question_id", question_ids)
        .order("label", desc=False)
        .execute()
        .data
        or []
    )
    options_by_q: dict[str, list[dict[str, Any]]] = {}
    for option in options:
        key = str(option.get("question_id") or "")
        if not key:
            continue
        options_by_q.setdefault(key, []).append(
            {
                "id": option.get("id"),
                "label": option.get("label"),
                "option_text": option.get("option_text"),
            }
        )

    out: list[dict[str, Any]] = []
    for qid in question_ids:
        row = question_by_id.get(qid)
        if not row:
            continue
        prompt = str(row.get("question_text") or row.get("prompt") or "").strip()
        out.append(
            {
                "id": qid,
                "prompt": prompt,
                "topic": row.get("topic"),
                "difficulty": row.get("difficulty"),
                "question_type": row.get("question_type"),
                "tags": row.get("tags") or [],
                "options": options_by_q.get(qid, []),
            }
        )
    return out


def submit_attempt_and_reveal(
    *,
    student_id: str,
    question_id: str,
    chosen_option_id: str,
    mode: str | None = None,
    time_taken_sec: int | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    client = create_supabase_client(settings)

    option_rows = (
        client.table("question_options")
        .select("id,question_id,is_correct,label")
        .eq("id", chosen_option_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not option_rows:
        raise ValueError("invalid_option")

    option = option_rows[0]
    if str(option.get("question_id")) != str(question_id):
        raise ValueError("option_question_mismatch")

    correct = bool(option.get("is_correct", False))

    question_rows = (
        client.table("questions")
        .select("id,topic,question_text,prompt,explanation")
        .eq("id", question_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not question_rows:
        raise ValueError("question_not_found")
    question = question_rows[0]

    attempt_payload = {
        "id": str(uuid4()),
        "student_id": _coerce_uuid_text(student_id),
        "question_id": question_id,
        "correct": correct,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
    }
    if mode:
        attempt_payload["mode"] = str(mode)
    if time_taken_sec is not None:
        attempt_payload["time_taken_sec"] = _safe_int(time_taken_sec)
    if confidence is not None:
        attempt_payload["confidence"] = float(confidence)
    attempt_payload["chosen_option_id"] = chosen_option_id

    try:
        client.table("attempts").insert(attempt_payload).execute()
    except Exception:
        attempt_payload.pop("chosen_option_id", None)
        client.table("attempts").insert(attempt_payload).execute()

    explanation = str(question.get("explanation") or "").strip()
    return {
        "question_id": question_id,
        "chosen_option_id": chosen_option_id,
        "correct": correct,
        "correct_label": str(next((row.get("label") for row in (client.table("question_options").select("label,is_correct").eq("question_id", question_id).eq("is_correct", True).execute().data or []) if True), "")),
        "explanation": explanation,
        "prompt": str(question.get("question_text") or question.get("prompt") or ""),
        "topic": question.get("topic"),
    }
