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


def _get_openai_response_models() -> list[str]:
    candidates = [
        os.getenv("OPENAI_RESPONSE_MODEL"),
        "gpt-4o-mini",
        _get_openai_model(),
    ]
    seen: set[str] = set()
    models: list[str] = []
    for item in candidates:
        model = str(item or "").strip()
        if not model or model in seen:
            continue
        models.append(model)
        seen.add(model)
    return models


def _fallback_intent_heuristic(message: str) -> str:
    message = message.lower()
    if any(word in message for word in ["improving", "regress", "trend", "progress", "changed", "performance"]):
        return "TREND"
    if any(word in message for word in ["careless", "weak", "struggle", "mistake", "pattern", "repeat"]):
        return "WEAKNESS"
    return "PLAN"


def _fallback_intents_heuristic(message: str) -> tuple[list[str], str]:
    normalized = message.lower()

    trend_keywords = ["improving", "regress", "trend", "progress", "changed", "performance"]
    weakness_keywords = ["careless", "weak", "struggle", "mistake", "pattern", "repeat", "why am i weak", "weak in"]
    plan_keywords = [
        "plan",
        "study plan",
        "what should i focus",
        "what should i do",
        "how do i fix",
        "how should i improve",
        "next step",
        "roadmap",
    ]

    detected: list[str] = []
    if any(keyword in normalized for keyword in trend_keywords):
        detected.append("TREND")
    if any(keyword in normalized for keyword in weakness_keywords):
        detected.append("WEAKNESS")
    if any(keyword in normalized for keyword in plan_keywords):
        detected.append("PLAN")

    if not detected:
        detected = [_fallback_intent_heuristic(normalized)]

    if len(detected) > 1 and "PLAN" not in detected and any(token in normalized for token in ["fix", "focus", "improve"]):
        detected.append("PLAN")

    deduped: list[str] = []
    for intent in detected:
        if intent in ALLOWED_INTENTS and intent not in deduped:
            deduped.append(intent)
    if not deduped:
        deduped = ["PLAN"]

    ordered_primary_candidates = ["WEAKNESS", "TREND", "PLAN"]
    primary = next((intent for intent in ordered_primary_candidates if intent in deduped), deduped[0])
    return deduped, primary


def _normalize_intent_list(raw_intents: Any) -> list[str]:
    normalized: list[str] = []
    if isinstance(raw_intents, str):
        raw_intents = [part.strip() for part in raw_intents.split(",") if part.strip()]
    if not isinstance(raw_intents, list):
        raw_intents = []

    for item in raw_intents:
        intent = str(item).upper().strip()
        if intent in ALLOWED_INTENTS and intent not in normalized:
            normalized.append(intent)
    return normalized


def _compose_multi_intent_response(state: GraphState, executed_intents: list[str]) -> str:
    responses: dict[str, str] = {}
    artifacts_by_intent = state.get("artifacts_by_intent") or {}
    for intent in executed_intents:
        artifact = artifacts_by_intent.get(intent) or {}
        text = str(artifact.get("response") or "").strip()
        if text:
            responses[intent] = text

    if len(responses) <= 1:
        return next(iter(responses.values()), "")

    synthesis_payload = {
        "message": state.get("message"),
        "intents": executed_intents,
        "branch_responses": responses,
        "plan": state.get("plan"),
        "diagnosis": state.get("diagnosis"),
    }
    synthesis_prompt = (
        "You are a learning coach synthesizer. "
        "Merge branch outputs into one coherent response that explicitly addresses each requested intent. "
        "If PLAN exists, keep concrete minute allocations and actionable next steps. "
        "Avoid explicit historical numeric stats from prior attempts; keep those insights qualitative. "
        "Do not repeat yourself; keep it concise and integrated."
    )

    try:
        client = _get_openai_client()
        for model_name in _get_openai_response_models():
            response = client.chat.completions.create(
                model=model_name,
                max_completion_tokens=900,
                messages=[
                    {"role": "system", "content": synthesis_prompt},
                    {"role": "user", "content": json.dumps(synthesis_payload, default=str)},
                ],
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text
    except Exception:
        pass

    ordered_text = [responses[intent] for intent in ["WEAKNESS", "TREND", "PLAN"] if intent in responses]
    return "\n\n".join(ordered_text)


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


def _fetch_attempt_evidence(
    student_id: str,
    window_days: int,
    limit: int = 120,
    focus_topics: list[str] | None = None,
) -> dict[str, Any]:
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

    normalized_focus_topics = {str(topic).strip().lower() for topic in (focus_topics or []) if str(topic).strip()}
    relevant_attempts: list[dict[str, Any]] = []
    if normalized_focus_topics:
        relevant_attempts = [
            row
            for row in filtered_rows
            if str(row.get("topic") or "").strip().lower() in normalized_focus_topics
        ]

    all_samples = filtered_rows[:40]
    if relevant_attempts:
        prioritized = relevant_attempts[:16] + [row for row in all_samples if row not in relevant_attempts]
        all_samples = prioritized[:40]

    return {
        "window": cutoff_marker,
        "total_attempts": total_attempts,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
        "accuracy": round(accuracy, 4),
        "focus_topics": sorted(normalized_focus_topics),
        "all_samples": all_samples,
        "relevant_attempts": relevant_attempts[:16],
        "right_samples": right[:6],
        "wrong_samples": wrong[:6],
        "topic_wrong_counts": dict(sorted(topic_wrong_counts.items(), key=lambda item: item[1], reverse=True)),
    }


def _deterministic_fallback_response(
    intent: str,
    diagnosis: dict | None,
    plan: dict | None,
    relevant_examples: list[dict[str, Any]] | None = None,
) -> str:
    examples = relevant_examples or []

    if intent == "PLAN":
        checklist = (plan or {}).get("checklist") or []
        if checklist:
            first = checklist[0]
            base = (
                "I prepared a focused plan based on your analytics. "
                f"Start with {first.get('topic')} for {first.get('minutes')} minutes, then continue through the checklist."
            )
            if examples:
                sample = examples[0]
                return (
                    f"{base} "
                    f"For context, a recent {sample.get('topic')} item you attempted was: "
                    f"\"{sample.get('question_content')}\"."
                )
            return base
        return "I can create a study plan once a time budget is provided or generic planning is selected."

    focus = (diagnosis or {}).get("primary_topic") or (diagnosis or {}).get("focus_topic") or "your weakest topic"
    base = (
        "Based on your latest analytics and recent attempts, "
        f"focus first on {focus}, then review similar mistakes and reattempt those question types."
    )
    if examples:
        sample = examples[0]
        return (
            f"{base} "
            f"A relevant recent attempt in {sample.get('topic')} was: "
            f"\"{sample.get('question_content')}\"."
        )
    return base


def _truncate_text(text: str, max_len: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3].rstrip() + "..."


def _build_relevant_attempt_examples(state: GraphState, max_items: int = 8) -> list[dict[str, Any]]:
    evidence = state.get("attempt_evidence") or {}
    samples = list(evidence.get("all_samples") or [])
    if not samples:
        samples = list(evidence.get("right_samples") or []) + list(evidence.get("wrong_samples") or [])

    diagnosis = state.get("diagnosis") or {}
    constraints = state.get("constraints") or {}

    target_topics: set[str] = set()
    for value in [diagnosis.get("primary_topic"), diagnosis.get("focus_topic")]:
        if isinstance(value, str) and value.strip():
            target_topics.add(value.strip().lower())

    for value in constraints.get("focus_topics") or []:
        text = str(value).strip()
        if text:
            target_topics.add(text.lower())

    for value in evidence.get("focus_topics") or []:
        text = str(value).strip()
        if text:
            target_topics.add(text.lower())

    for step in (state.get("plan") or {}).get("checklist") or []:
        topic = str((step or {}).get("topic") or "").strip()
        if topic:
            target_topics.add(topic.lower())

    filtered = [
        sample
        for sample in samples
        if not target_topics or str(sample.get("topic") or "").strip().lower() in target_topics
    ]
    candidates = filtered or samples

    examples: list[dict[str, Any]] = []
    for sample in candidates:
        examples.append(
            {
                "topic": sample.get("topic"),
                "correct": bool(sample.get("correct", False)),
                "confidence": sample.get("confidence"),
                "time_taken_sec": sample.get("time_taken_sec"),
                "attempted_at": sample.get("attempted_at"),
                "question_content": _truncate_text(str(sample.get("question_content") or ""), max_len=180),
            }
        )

    plan_topic_rank: dict[str, int] = {}
    for idx, step in enumerate((state.get("plan") or {}).get("checklist") or []):
        topic = str((step or {}).get("topic") or "").strip().lower()
        if topic and topic not in plan_topic_rank:
            plan_topic_rank[topic] = idx

    def _rank(item: dict[str, Any]) -> tuple[int, int, str]:
        topic = str(item.get("topic") or "").strip().lower()
        topic_priority = plan_topic_rank.get(topic, 999)
        correctness_priority = 0 if not item.get("correct") else 1
        recency = str(item.get("attempted_at") or "")
        return (topic_priority, correctness_priority, recency)

    sorted_examples = sorted(examples, key=_rank, reverse=False)
    return sorted_examples[:max_items]


def _generate_branch_response(state: GraphState, branch: str) -> str:
    """Generate final user-facing response using the same OpenAI model."""
    relevant_examples = _build_relevant_attempt_examples(state)
    compact_examples = relevant_examples[:4]
    attempt_evidence = state.get("attempt_evidence") or {}

    topic_state = list(state.get("topic_state") or [])
    topic_state = sorted(topic_state, key=lambda item: item.get("mastery", 1.0))[:5]

    error_state = list(state.get("error_state") or [])
    error_state = sorted(
        error_state,
        key=lambda item: max(item.get("conceptual", 0.0), item.get("careless", 0.0), item.get("time_pressure", 0.0)),
        reverse=True,
    )[:5]

    def _band(value: float, low: float, high: float) -> str:
        if value < low:
            return "low"
        if value > high:
            return "high"
        return "moderate"

    topic_signals: list[dict[str, Any]] = []
    for item in topic_state:
        mastery = float(item.get("mastery", 0.0) or 0.0)
        trend = float(item.get("trend", 0.0) or 0.0)
        decay = float(item.get("decay_risk", 0.0) or 0.0)
        uncertainty = float(item.get("uncertainty", 0.0) or 0.0)

        if mastery < 0.45:
            mastery_band = "weak"
        elif mastery < 0.7:
            mastery_band = "developing"
        else:
            mastery_band = "strong"

        if trend <= -0.05:
            trend_label = "regressing"
        elif trend >= 0.05:
            trend_label = "improving"
        else:
            trend_label = "stable"

        topic_signals.append(
            {
                "topic": item.get("topic"),
                "mastery_band": mastery_band,
                "trend_label": trend_label,
                "decay_risk": _band(decay, 0.33, 0.66),
                "uncertainty": _band(uncertainty, 0.33, 0.66),
            }
        )

    error_signals: list[dict[str, Any]] = []
    for item in error_state:
        conceptual = float(item.get("conceptual", 0.0) or 0.0)
        careless = float(item.get("careless", 0.0) or 0.0)
        time_pressure = float(item.get("time_pressure", 0.0) or 0.0)
        dominant = max(
            {
                "conceptual": conceptual,
                "careless": careless,
                "time_pressure": time_pressure,
            }.items(),
            key=lambda kv: kv[1],
        )[0]
        error_signals.append(
            {
                "topic": item.get("topic"),
                "dominant_error": dominant,
                "severity": _band(max(conceptual, careless, time_pressure), 0.33, 0.66),
            }
        )

    analytics_summary = {
        "focus_topics": attempt_evidence.get("focus_topics") or [],
        "topic_wrong_counts": attempt_evidence.get("topic_wrong_counts") or {},
        "total_attempts": attempt_evidence.get("total_attempts", 0),
        "total_wrong": attempt_evidence.get("total_wrong", 0),
        "accuracy": attempt_evidence.get("accuracy", 0.0),
    }

    payload = {
        "branch": branch,
        "intent": state.get("intent"),
        "message": state.get("message"),
        "diagnosis": state.get("diagnosis"),
        "plan": state.get("plan"),
        "topic_state": topic_signals,
        "error_state": error_signals,
        "attempt_evidence": analytics_summary,
        "relevant_attempt_examples": compact_examples,
        "constraints": state.get("constraints"),
    }

    short_prompt = (
        "You are an analytics-driven learning coach. "
        "Ground all claims in provided analytics and attempt evidence. "
        "Reference at least one concrete question example with topic and context. "
        "Do not expose raw historical metrics or exact attempt stats (no mastery percentages, no exact confidence/time/error-rate numbers). "
        "Never quote numeric values from past attempts; only planned study minutes are allowed as numbers. "
        "Express performance insights qualitatively (for example: improving, unstable, recurring conceptual gap). "
        "No generic advice."
    )

    long_prompt = (
        "You are an analytics-driven learning coach inside an agentic tutoring system. "
        "Use only the provided analytics and attempt evidence; do not invent facts. "
        "Always include at least one concrete attempt example with topic and question/tag context. "
        "Do not reveal raw historical numeric stats from prior attempts (avoid explicit mastery %, conceptual/careless/time-pressure values, exact confidence/time values, or exact correct/wrong totals). "
        "Never quote numeric values from past-attempt analytics; only planned study minutes are allowed as explicit numbers. "
        "Translate data into qualitative insight and behavior-focused guidance. "
        "Interpret signals behaviorally (what this implies about understanding/execution), not just as raw numbers. "
        "For TREND/WEAKNESS: identify 2-3 core issues, explain why each is happening from mastery/trend/decay/error signals, and give specific next micro-actions. "
        "For PLAN: provide PLAN SUMMARY with topic-minute bullets from allocation, and for each topic include why chosen and precise focus drills aligned to dominant error type. "
        "Tone: analytical, concise, no fluff, no generic advice."
    )

    use_long_prompt = str(os.getenv("COACH_USE_LONG_PROMPT", "1")).lower() not in {"0", "false", "no"}
    system_prompt = long_prompt if use_long_prompt else short_prompt

    compact_payload = {
        **payload,
        "topic_state": topic_signals[:3],
        "error_state": error_signals[:3],
        "relevant_attempt_examples": compact_examples[:2],
    }

    attempts_plan = [
        {"prompt": system_prompt, "max_tokens": 1200, "payload": payload, "profile": "primary"},
        {"prompt": system_prompt, "max_tokens": 1800, "payload": compact_payload, "profile": "long_compact"},
        {"prompt": short_prompt, "max_tokens": 900, "payload": compact_payload, "profile": "short_compact"},
    ]

    llm_error: str | None = None
    last_finish_reason: str | None = None
    client = None

    try:
        client = _get_openai_client()
    except Exception as exc:
        llm_error = f"client_error: {type(exc).__name__}: {exc}"

    if client is not None:
        response_models = _get_openai_response_models()
        overall_attempt = 0
        for model_name in response_models:
            for attempt_plan in attempts_plan:
                overall_attempt += 1
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        max_completion_tokens=int(attempt_plan["max_tokens"]),
                        messages=[
                            {"role": "system", "content": str(attempt_plan["prompt"])},
                            {"role": "user", "content": json.dumps(attempt_plan["payload"], default=str)},
                        ],
                    )
                    choice = response.choices[0]
                    last_finish_reason = str(choice.finish_reason)
                    text = (choice.message.content or "").strip()
                    if text:
                        debug = dict(state.get("response_debug") or {})
                        debug[branch] = {
                            "source": "openai",
                            "attempt": overall_attempt,
                            "profile": attempt_plan["profile"],
                            "model": model_name,
                            "finish_reason": last_finish_reason,
                            "examples_used": len((attempt_plan["payload"] or {}).get("relevant_attempt_examples") or []),
                        }
                        state["response_debug"] = debug
                        return text

                    refusal = getattr(choice.message, "refusal", None)
                    llm_error = (
                        f"empty_content(model={model_name}, profile={attempt_plan['profile']}): "
                        f"finish_reason={last_finish_reason}, refusal={refusal}"
                    )
                except Exception as exc:
                    llm_error = (
                        f"attempt_{overall_attempt}_error(model={model_name}, profile={attempt_plan['profile']}): "
                        f"{type(exc).__name__}: {exc}"
                    )

    fallback_text = _deterministic_fallback_response(
        intent=str(state.get("intent") or branch),
        diagnosis=state.get("diagnosis") or {},
        plan=state.get("plan") or {},
        relevant_examples=relevant_examples,
    )

    debug = dict(state.get("response_debug") or {})
    debug[branch] = {
        "source": "deterministic_fallback",
        "error": llm_error,
        "finish_reason": last_finish_reason,
        "examples_used": len(relevant_examples),
    }
    state["response_debug"] = debug
    return fallback_text


def _extract_time_budget_from_message(message: str) -> int | None:
    normalized = message.lower()
    per_day_match = re.search(r"(\d+)\s*(hour|hours|hr|hrs|minute|minutes|min|mins)\s*(?:a|per)\s*day\b", normalized)
    if per_day_match:
        value = int(per_day_match.group(1))
        unit = per_day_match.group(2)
        return value * 60 if unit.startswith("h") else value

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


def _extract_time_horizon_days_from_message(message: str) -> int | None:
    normalized = message.lower()

    if re.search(r"\btomorrow\b", normalized):
        return 1
    if re.search(r"\b(next|this)\s+week\b", normalized):
        return 7
    if re.search(r"\b(next|this)\s+month\b", normalized):
        return 30

    horizon_match = re.search(
        r"\b(?:in\s+)?(?P<count>\d+|a|an|one)\s*(?P<unit>day|days|week|weeks|month|months)\b(?:\s*(?:left|to|till|until)\s*(?:the\s+)?exam)?",
        normalized,
    )
    if not horizon_match:
        return None

    raw_count = horizon_match.group("count")
    count = 1 if raw_count in {"a", "an", "one"} else int(raw_count)
    unit = horizon_match.group("unit")

    if unit.startswith("day"):
        return max(1, count)
    if unit.startswith("week"):
        return max(1, count * 7)
    if unit.startswith("month"):
        return max(1, count * 30)
    return None


def _derive_total_budget_from_horizon(
    time_horizon_days: int,
    explicit_daily_budget_min: int | None,
) -> tuple[int, str]:
    daily_budget = explicit_daily_budget_min if isinstance(explicit_daily_budget_min, int) and explicit_daily_budget_min > 0 else 60
    total_budget = max(1, daily_budget * max(1, time_horizon_days))
    basis = "explicit_daily_budget" if explicit_daily_budget_min else "default_daily_budget_60"
    return total_budget, basis


def _extract_focus_topics_from_message(message: str, topic_state: list[dict]) -> list[str]:
    normalized = message.lower()
    found: list[str] = []

    def _topic_aliases(topic: str) -> set[str]:
        aliases = {topic.lower().strip()}
        cleaned = re.sub(r"[^a-z0-9\s-]", " ", topic.lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            aliases.add(cleaned)
            aliases.add(cleaned.replace("-", " "))

        words = [part for part in re.split(r"[\s-]+", cleaned) if part]
        if len(words) >= 2:
            acronym = "".join(word[0] for word in words)
            if len(acronym) >= 2:
                aliases.add(acronym)

        for word in words:
            if len(word) >= 4:
                aliases.add(word)

        return {alias for alias in aliases if alias}

    for item in topic_state:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        aliases = _topic_aliases(topic)
        matched = False
        for alias in aliases:
            if len(alias) <= 3:
                if re.search(rf"\b{re.escape(alias)}\b", normalized):
                    matched = True
                    break
            elif alias in normalized:
                matched = True
                break
        if matched:
            found.append(topic)
    return sorted(set(found))


def _normalize_plan_constraints(
    message: str,
    constraints: dict | None,
    topic_state: list[dict],
    clarification_answer: dict | None,
) -> tuple[dict, bool, dict | None]:
    merged = dict(constraints or {})

    extracted_horizon_days = _extract_time_horizon_days_from_message(message)
    if extracted_horizon_days is not None and not isinstance(merged.get("time_horizon_days"), int):
        merged["time_horizon_days"] = int(extracted_horizon_days)

    extracted_daily_budget = _extract_time_budget_from_message(message)
    if extracted_daily_budget is not None and not isinstance(merged.get("daily_budget_min"), int):
        daily_hint = re.search(r"(\d+)\s*(hour|hours|hr|hrs|minute|minutes|min|mins)\s*(?:a|per)\s*day\b", message.lower())
        if daily_hint:
            merged["daily_budget_min"] = int(extracted_daily_budget)

    if not isinstance(merged.get("time_budget_min"), int):
        extracted_budget = extracted_daily_budget
        if extracted_budget is not None:
            merged["time_budget_min"] = extracted_budget

    if not isinstance(merged.get("time_budget_min"), int) and isinstance(merged.get("time_horizon_days"), int):
        total_budget, budget_basis = _derive_total_budget_from_horizon(
            time_horizon_days=int(merged["time_horizon_days"]),
            explicit_daily_budget_min=(
                int(merged["daily_budget_min"]) if isinstance(merged.get("daily_budget_min"), int) else None
            ),
        )
        merged["time_budget_min"] = total_budget
        merged["time_budget_basis"] = budget_basis

    extracted_topics = _extract_focus_topics_from_message(message, topic_state)
    if extracted_topics and not merged.get("focus_topics"):
        merged["focus_topics"] = extracted_topics

    if clarification_answer:
        if isinstance(clarification_answer.get("time_budget_min"), int):
            merged["time_budget_min"] = int(clarification_answer["time_budget_min"])

        if isinstance(clarification_answer.get("time_horizon_days"), int):
            merged["time_horizon_days"] = int(clarification_answer["time_horizon_days"])

        if isinstance(clarification_answer.get("daily_budget_min"), int):
            merged["daily_budget_min"] = int(clarification_answer["daily_budget_min"])

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
            "time_horizon_days": "integer (optional, e.g. days until exam)",
            "daily_budget_min": "integer (optional, if sharing per-day availability)",
            "focus_topics": "string[] (optional)",
            "generic_plan": "boolean (set true to skip details)",
        },
        "topic_options": [item.get("topic") for item in topic_state if item.get("topic")],
        "time_options_min": [20, 30, 45, 60, 90, 120],
    }
    return merged, True, question


def _classify_intent_with_openai(message: str) -> tuple[list[str], str, float, str, str | None]:
    system_prompt = (
        "You are an intent classifier for a learning coach. "
        "Classify the query into one or more intents from: TREND, WEAKNESS, PLAN. "
        "Use multiple intents if the user asks for analysis plus what to do next. "
        "TREND refers to progress/regression over time. "
        "WEAKNESS refers to struggling topics/mistakes/patterns/why. "
        "PLAN refers to study actions, focus areas, schedule, or fixes. "
        "Return JSON only in this format: "
        '{"intents":["TREND|WEAKNESS|PLAN"],"primary_intent":"TREND|WEAKNESS|PLAN","confidence":0.0}. '
        "No markdown, no extra text."
    )

    def _parse_intent_payload(text: str) -> tuple[list[str], str, float]:
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

        intents = _normalize_intent_list(payload.get("intents"))
        if not intents and payload.get("intent") is not None:
            intents = _normalize_intent_list([payload.get("intent")])
        if not intents:
            intents, _ = _fallback_intents_heuristic(message)

        primary_intent = str(payload.get("primary_intent") or "").upper().strip()
        if primary_intent not in intents:
            primary_intent = intents[0]

        confidence = float(payload.get("confidence", 0.0))
        return intents, primary_intent, max(0.0, min(1.0, confidence))

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

                intents, primary_intent, confidence = _parse_intent_payload(content)
                if not intents:
                    raise ValueError("No valid intents returned")

                return intents, primary_intent, confidence, "openai", None
            except Exception as exc:  # noqa: PERF203 - explicit retry with captured context
                last_error = exc

        if last_error is not None:
            raise last_error

        fallback_intents, fallback_primary = _fallback_intents_heuristic(message)
        return fallback_intents, fallback_primary, 0.3, "fallback_invalid_intent", "Invalid intent returned by model"
    except Exception as exc:
        fallback_intents, fallback_primary = _fallback_intents_heuristic(message)
        return fallback_intents, fallback_primary, 0.3, "fallback_error", f"{type(exc).__name__}: {exc}"


def node_build_state(state: GraphState) -> GraphState:
    topic_state, error_state = build_state(
        student_id=state["student_id"],
        window_days=state.get("window_days", 30),
    )
    state["topic_state"] = [item.model_dump() for item in topic_state]
    state["error_state"] = [item.model_dump() for item in error_state]
    focus_topics = _extract_focus_topics_from_message(
        str(state.get("message") or ""),
        state["topic_state"],
    )
    attempt_evidence = _fetch_attempt_evidence(
        student_id=str(state.get("student_id", "")),
        window_days=int(state.get("window_days", 30)),
        focus_topics=focus_topics,
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
            "query_focus_topics": focus_topics,
            "relevant_attempts": len(attempt_evidence.get("relevant_attempts") or []),
        },
    )
    return state


def node_route_intent(state: GraphState) -> GraphState:
    message = str(state.get("message", "")).strip()
    intents, primary_intent, confidence, source, error = _classify_intent_with_openai(message)
    state["intents"] = intents
    state["intent"] = primary_intent
    state["intent_confidence"] = confidence
    state["intent_source"] = source
    state["intent_error"] = error
    _append_trace(
        state,
        "route_intent",
        {
            "intent": primary_intent,
            "intents": intents,
            "confidence": confidence,
            "source": source,
            "error": state.get("intent_error"),
        },
    )
    return state


def node_uncertainty_gate(state: GraphState) -> GraphState:
    coach_state = CoachRunState.model_validate(state)
    intents = _normalize_intent_list(state.get("intents") or [coach_state.intent])

    merged_constraints = dict(coach_state.constraints or {})
    needs = False
    question = None

    if "PLAN" in intents:
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
            "intents": intents,
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
    response_text = _generate_branch_response(state, "TREND")
    response_meta = (state.get("response_debug") or {}).get("TREND") or {}
    state["artifact"] = {
        "agent": "trend_agent",
        "summary": "Trend analysis prepared from topic mastery snapshot.",
        "focus_topic": focus_topic.get("topic") if focus_topic else None,
        "topic_state": topic_state,
        "response": response_text,
        "response_source": response_meta.get("source"),
        "response_debug": response_meta,
    }
    _append_trace(state, "handle_trend", {"focus_topic": state["artifact"].get("focus_topic")})
    return state


def node_handle_weakness(state: GraphState) -> GraphState:
    state = node_diagnosis(state)
    diagnosis = state.get("diagnosis") or {}
    state["artifact_type"] = "weakness_report"
    response_text = _generate_branch_response(state, "WEAKNESS")
    response_meta = (state.get("response_debug") or {}).get("WEAKNESS") or {}
    state["artifact"] = {
        "agent": "weakness_agent",
        "summary": "Weakness diagnosis generated from error pressure and mastery.",
        "focus_topic": diagnosis.get("primary_topic"),
        "primary_issue": diagnosis.get("primary_issue"),
        "response": response_text,
        "response_source": response_meta.get("source"),
        "response_debug": response_meta,
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
        response_text = _generate_branch_response(state, "PLAN")
        response_meta = (state.get("response_debug") or {}).get("PLAN") or {}
        state["plan"]["response"] = response_text
        state["plan"]["response_source"] = response_meta.get("source")
        state["plan"]["response_debug"] = response_meta
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


def node_execute_intents(state: GraphState) -> GraphState:
    intents = _normalize_intent_list(state.get("intents") or [state.get("intent")])
    if not intents:
        intents = ["PLAN"]

    execution_order = [intent for intent in ["WEAKNESS", "TREND", "PLAN"] if intent in intents]
    artifacts_by_intent: dict[str, dict[str, Any]] = {}

    for intent in execution_order:
        if intent == "WEAKNESS":
            state = node_handle_weakness(state)
        elif intent == "TREND":
            state = node_handle_trend(state)
        elif intent == "PLAN":
            state = node_handle_plan(state)

        if isinstance(state.get("artifact"), dict):
            artifacts_by_intent[intent] = dict(state["artifact"])

    state["executed_intents"] = execution_order
    state["artifacts_by_intent"] = artifacts_by_intent

    if len(execution_order) > 1:
        combined_response = _compose_multi_intent_response(state, execution_order)
        state["artifact_type"] = "combined_report"
        state["artifact"] = {
            "agent": "multi_intent_agent",
            "intents": execution_order,
            "responses_by_intent": {
                intent: (artifacts_by_intent.get(intent) or {}).get("response") for intent in execution_order
            },
            "response": combined_response,
        }

    _append_trace(state, "execute_intents", {"intents": execution_order, "combined": len(execution_order) > 1})
    return state


def node_finalize(state: GraphState) -> GraphState:
    _append_trace(state, "finalize")
    return state


def _after_uncertainty(state: GraphState) -> str:
    if state.get("needs_clarification"):
        return "needs_input"
    return "execute"


@lru_cache(maxsize=1)
def get_coach_graph2():
    """Build and cache the compiled graph (v2 with OpenAI intent routing)."""
    workflow = StateGraph(dict)

    # Core orchestration stages: analytics snapshot -> intent classification -> clarification gate.
    workflow.add_node("build_student_state", node_build_state)
    workflow.add_node("classify_intent", node_route_intent)
    workflow.add_node("uncertainty_gate", node_uncertainty_gate)

    # Execute one or more intent handlers and combine when needed.
    workflow.add_node("execute_intents", node_execute_intents)
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
            "execute": "execute_intents",
        },
    )

    workflow.add_edge("execute_intents", "finalize")
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
