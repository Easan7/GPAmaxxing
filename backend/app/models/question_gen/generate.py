from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.models.question_gen.llm import generate_questions_with_llm
from app.models.question_gen.search import retrieve_topic_context
from app.storage.supabase_client import create_supabase_client


VALID_LABELS = ["A", "B", "C", "D"]


def _normalize_options(options: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:
    if not isinstance(options, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, option in enumerate(options[:4]):
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or VALID_LABELS[index]).strip().upper()
        text = str(option.get("option_text") or "").strip()
        is_correct = bool(option.get("is_correct", False))
        if label not in VALID_LABELS or not text:
            continue
        normalized.append({"label": label, "option_text": text, "is_correct": is_correct})

    normalized = sorted(normalized, key=lambda item: VALID_LABELS.index(item["label"]))
    if len(normalized) != 4:
        return []

    if sum(1 for item in normalized if item["is_correct"]) != 1:
        return []
    return normalized


def _is_duplicate_prompt(client: Any, *, topic: str, prompt: str) -> bool:
    probe = (
        client.table("questions")
        .select("id,question_text,prompt")
        .eq("topic", topic)
        .limit(150)
        .execute()
    )
    rows = probe.data or []
    prompt_key = prompt.strip().lower()
    for row in rows:
        existing = str(row.get("question_text") or row.get("prompt") or "").strip().lower()
        if existing == prompt_key:
            return True
    return False


def _insert_question_and_options(client: Any, question: dict[str, Any]) -> str:
    question_id = str(uuid4())
    base_row = {
        "id": question_id,
        "topic": question["topic"],
        "question_type": question["question_type"],
        "difficulty": question["difficulty"],
        "tags": question["tags"],
        "explanation": question["explanation"],
    }
    insert_attempts = [
        {**base_row, "question_text": question["prompt"]},
        {**base_row, "prompt": question["prompt"]},
    ]

    insert_error: Exception | None = None
    for question_row in insert_attempts:
        try:
            client.table("questions").insert(question_row).execute()
            insert_error = None
            break
        except Exception as exc:
            insert_error = exc
    if insert_error is not None:
        raise insert_error

    option_rows = [
        {
            "id": str(uuid4()),
            "question_id": question_id,
            "label": option["label"],
            "option_text": option["option_text"],
            "is_correct": bool(option["is_correct"]),
        }
        for option in question["options"]
    ]
    client.table("question_options").insert(option_rows).execute()
    return question_id


def _validate_generated_question(raw: dict[str, Any], *, fallback_topic: str, fallback_difficulty: str, fallback_question_type: str, fallback_tags: list[str]) -> dict[str, Any] | None:
    prompt = str(raw.get("prompt") or "").strip()
    explanation = str(raw.get("explanation") or "").strip()
    topic = str(raw.get("topic") or fallback_topic).strip() or fallback_topic
    difficulty = str(raw.get("difficulty") or fallback_difficulty).strip() or fallback_difficulty
    question_type = str(raw.get("question_type") or fallback_question_type).strip() or fallback_question_type

    tags = raw.get("tags")
    if not isinstance(tags, list):
        tags = list(fallback_tags)
    tags = [str(tag).strip() for tag in tags if str(tag).strip()]

    options = _normalize_options(raw.get("options"))

    if not prompt or not explanation or not options:
        return None

    return {
        "prompt": prompt,
        "explanation": explanation,
        "topic": topic,
        "difficulty": difficulty,
        "question_type": question_type,
        "tags": tags,
        "options": options,
    }


def generate_and_insert_questions(
    *,
    topic: str,
    difficulty: str,
    question_type: str,
    tags: list[str] | None,
    n: int,
) -> list[str]:
    settings = get_settings()
    client = create_supabase_client(settings)

    requested = max(1, min(int(n), 10))
    tag_list = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]

    search_docs = retrieve_topic_context(topic=topic, tags=tag_list, top_k=max(4, requested * 2))
    payload = {
        "topic": topic,
        "difficulty": difficulty,
        "question_type": question_type,
        "tags": tag_list,
        "n": requested,
        "retrieved_context": search_docs,
    }

    generated = generate_questions_with_llm(payload=payload)

    inserted_ids: list[str] = []
    for raw in generated:
        if len(inserted_ids) >= requested:
            break

        parsed = _validate_generated_question(
            raw,
            fallback_topic=topic,
            fallback_difficulty=difficulty,
            fallback_question_type=question_type,
            fallback_tags=tag_list,
        )
        if not parsed:
            continue

        if _is_duplicate_prompt(client, topic=parsed["topic"], prompt=parsed["prompt"]):
            continue

        question_id = _insert_question_and_options(client, parsed)
        inserted_ids.append(question_id)

    return inserted_ids
