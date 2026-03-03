from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import get_settings


def _get_question_gen_client() -> OpenAI:
    settings = get_settings()
    api_key = settings.QUESTION_GEN_OPENAI_API_KEY or settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError("Missing QUESTION_GEN_OPENAI_API_KEY/OPENAI_API_KEY")

    base_url = settings.QUESTION_GEN_OPENAI_BASE_URL or settings.OPENAI_BASE_URL
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _get_question_gen_model() -> str:
    settings = get_settings()
    return settings.QUESTION_GEN_MODEL or settings.OPENAI_MODEL or settings.OPENAI_CHAT_MODEL or "gpt-4o-mini"


def generate_questions_with_llm(*, payload: dict[str, Any]) -> list[dict[str, Any]]:
    client = _get_question_gen_client()

    prompt = (
        "You generate MCQ questions grounded in provided source snippets. "
        "Return JSON only with shape {\"questions\": [ ... ]}. "
        "Each question must include: prompt, topic, difficulty, question_type, tags, explanation, options. "
        "options must be exactly 4 items with labels A,B,C,D and exactly one is_correct=true. "
        "Do not leak which option is correct in prompt text."
    )

    response = client.chat.completions.create(
        model=_get_question_gen_model(),
        response_format={"type": "json_object"},
        max_completion_tokens=1200,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
    )
    content = (response.choices[0].message.content or "").strip()
    parsed = json.loads(content) if content else {}
    questions = parsed.get("questions")
    if not isinstance(questions, list):
        return []
    return [item for item in questions if isinstance(item, dict)]
