"""Supabase-backed repository helpers for analytics inputs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TypedDict

from app.config import get_settings
from app.storage.supabase_client import create_supabase_client


class AttemptWithQuestion(TypedDict):
    attempted_at: datetime
    correct: bool
    time_taken_sec: int | None
    confidence: float | None
    mode: str | None
    topic: str | None
    question_type: str | None
    difficulty: str | None
    tags: list[str]


def _parse_attempted_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _extract_question_obj(row: dict) -> dict:
    question_obj = row.get("questions")
    if isinstance(question_obj, list):
        return question_obj[0] if question_obj else {}
    if isinstance(question_obj, dict):
        return question_obj
    return {}


def fetch_attempts_join_questions(
    student_id: str,
    since_days: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Fetch attempts joined with questions and return flattened dict rows."""
    settings = get_settings()
    client = create_supabase_client(settings)

    page_size = min(max(limit, 1), 200)
    max_pages = 5
    collected: list[dict] = []

    attempted_at_gte: str | None = None
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        attempted_at_gte = cutoff.isoformat()

    for page in range(max_pages):
        if len(collected) >= limit:
            break

        start = page * page_size
        end = start + page_size - 1

        query = (
            client.table("attempts")
            .select(
                "id,student_id,question_id,correct,time_taken_sec,confidence,mode,attempted_at,"
                "questions(topic,question_type,difficulty,tags)"
            )
            .eq("student_id", student_id)
            .order("attempted_at", desc=False)
            .range(start, end)
        )

        if attempted_at_gte is not None:
            query = query.gte("attempted_at", attempted_at_gte)

        response = query.execute()

        if getattr(response, "error", None):
            raise RuntimeError(f"Supabase query failed: {response.error}")

        rows = response.data or []
        for row in rows:
            question = _extract_question_obj(row)
            collected.append(
                {
                    "attempted_at": _parse_attempted_at(row.get("attempted_at")),
                    "correct": bool(row.get("correct", False)),
                    "time_taken_sec": int(row["time_taken_sec"]) if row.get("time_taken_sec") is not None else None,
                    "confidence": float(row["confidence"]) if row.get("confidence") is not None else None,
                    "mode": row.get("mode"),
                    "topic": question.get("topic"),
                    "question_type": question.get("question_type"),
                    "difficulty": question.get("difficulty"),
                    "tags": [str(tag) for tag in (question.get("tags") or [])],
                }
            )

        if len(rows) < page_size:
            break

    return collected[:limit]
