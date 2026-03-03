"""LangGraph workflow with OpenAI intent routing.

This version replaces hardcoded intent routing with OpenAI classification,
then routes to intent-specific agent paths with deterministic fallbacks.
"""

from __future__ import annotations

import json
import hashlib
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
    from app.services.session_service import create_study_session
    from app.services.state_builder import build_state
except ModuleNotFoundError:
    backend_root = Path(__file__).resolve().parents[2]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from app.schemas.state import CoachRunState
    from app.config import get_settings
    from app.storage.supabase_client import create_supabase_client
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


def _has_explicit_plan_request(message: str) -> bool:
    normalized = message.lower()
    explicit_markers = [
        "study plan",
        "plan",
        "schedule",
        "roadmap",
        "allocate",
        "allocation",
        "for the next",
        "next week",
        "next month",
        "next 2 weeks",
        "next 3 weeks",
        "minutes per day",
        "hours per day",
        "timeline",
    ]
    return any(marker in normalized for marker in explicit_markers)


def _compose_multi_intent_response(state: GraphState, executed_intents: list[str]) -> str:
    responses: dict[str, str] = {}
    artifacts_by_intent = state.get("artifacts_by_intent") or {}
    for intent in executed_intents:
        artifact = artifacts_by_intent.get(intent) or {}
        text = str(artifact.get("response") or "").strip()
        if text:
            responses[intent] = text

    if "PLAN" in responses:
        return responses["PLAN"]

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
        "Keep topic labels independent and verbatim; do not present one topic as a subtopic of another unless explicitly provided in branch outputs. "
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


def _derive_rag_focus_topics(state: GraphState, branch: str) -> list[str]:
    topic_state = list(state.get("topic_state") or [])
    diagnosis = state.get("diagnosis") or {}
    constraints = state.get("constraints") or {}

    candidates: list[str] = []

    for value in [diagnosis.get("primary_topic"), diagnosis.get("focus_topic")]:
        topic = str(value or "").strip()
        if topic:
            candidates.append(topic)

    for value in constraints.get("focus_topics") or []:
        topic = str(value or "").strip()
        if topic:
            candidates.append(topic)

    if branch == "WEAKNESS" and topic_state:
        weakest = sorted(topic_state, key=lambda item: float(item.get("mastery", 1.0) or 1.0))[:3]
        for item in weakest:
            topic = str(item.get("topic") or "").strip()
            if topic:
                candidates.append(topic)

    deduped: list[str] = []
    seen: set[str] = set()
    for topic in candidates:
        key = topic.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(topic)
    return deduped[:6]


def _build_rag_queries_from_attempts(state: GraphState, branch: str, max_queries: int = 4) -> list[str]:
    evidence = state.get("attempt_evidence") or {}
    focus_topics = {topic.lower() for topic in _derive_rag_focus_topics(state, branch)}

    all_samples = list(evidence.get("all_samples") or [])
    wrong_samples = [sample for sample in all_samples if not bool(sample.get("correct", False))]
    if not wrong_samples:
        wrong_samples = list(evidence.get("wrong_samples") or [])

    if focus_topics:
        filtered = [
            sample
            for sample in wrong_samples
            if str(sample.get("topic") or "").strip().lower() in focus_topics
        ]
        if filtered:
            wrong_samples = filtered

    queries: list[str] = []
    for sample in wrong_samples:
        topic = str(sample.get("topic") or "").strip()
        question = _truncate_text(str(sample.get("question_content") or "").strip(), max_len=220)
        if not question:
            continue
        query = f"{topic}: {question}" if topic else question
        if query not in queries:
            queries.append(query)
        if len(queries) >= max_queries:
            break
    return queries


def _retrieve_rag_context_from_wrong_attempts(
    state: GraphState,
    branch: str,
    *,
    top_k_per_query: int = 3,
    max_queries: int = 4,
    max_docs: int = 7,
) -> list[dict[str, Any]]:
    queries = _build_rag_queries_from_attempts(state, branch, max_queries=max_queries)
    if not queries:
        return []

    if branch != "WEAKNESS" and not bool(state.get("constraints", {}).get("rag_for_all_intents")):
        return []

    try:
        from app.storage.blob_client import AISearchClient
    except Exception:
        return []

    try:
        client = AISearchClient()
    except Exception:
        return []

    docs: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()

    for query in queries:
        try:
            result = client.retrieve(query, top_k=top_k_per_query)
        except Exception:
            continue

        for item in result.get("documents") or []:
            content = _truncate_text(str(item.get("content") or "").strip(), max_len=900)
            source = str(item.get("source") or "unknown")
            path = str(item.get("path") or "")
            score = float(item.get("score") or 0.0)
            signature = f"{source}|{path}|{content[:120]}"
            if not content or signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            docs.append(
                {
                    "source": source,
                    "path": path,
                    "score": round(score, 4),
                    "content": content,
                    "query": query,
                }
            )

    docs = sorted(docs, key=lambda item: float(item.get("score") or 0.0), reverse=True)[:max_docs]
    return docs


def _ensure_branch_rag_context(state: GraphState, branch: str) -> list[dict[str, Any]]:
    rag_by_branch = dict(state.get("rag_by_branch") or {})

    if branch in rag_by_branch:
        return list(rag_by_branch.get(branch) or [])

    docs = _retrieve_rag_context_from_wrong_attempts(state, branch)
    rag_by_branch[branch] = docs
    state["rag_by_branch"] = rag_by_branch
    return docs


def _build_rag_resource_recommendations(rag_context: list[dict[str, Any]], max_items: int = 4) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for item in rag_context or []:
        source = str(item.get("source") or "").strip()
        if not source or source in seen_sources:
            continue
        seen_sources.add(source)
        recommendations.append(
            {
                "source": source,
                "summary": _truncate_text(str(item.get("content") or "").strip(), max_len=180),
                "linked_query": str(item.get("query") or "").strip(),
                "score": float(item.get("score") or 0.0),
            }
        )
        if len(recommendations) >= max_items:
            break
    return recommendations


def _generate_branch_response(state: GraphState, branch: str) -> str:
    """Generate final user-facing response using the same OpenAI model."""
    relevant_examples = _build_relevant_attempt_examples(state)
    compact_examples = relevant_examples[:4]
    attempt_evidence = state.get("attempt_evidence") or {}
    rag_context = _ensure_branch_rag_context(state, branch)
    rag_resources = _build_rag_resource_recommendations(rag_context)

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
            trend_label = "slipping"
        elif trend >= 0.05:
            trend_label = "improving"
        else:
            trend_label = "stable"

        topic_signals.append(
            {
                "topic": item.get("topic"),
                "mastery_band": mastery_band,
                "trend_label": trend_label,
                "retention_risk": _band(decay, 0.33, 0.66),
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

    dominant_errors_by_topic: dict[str, dict[str, Any]] = {}
    for item in state.get("error_state") or []:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        conceptual = float(item.get("conceptual", 0.0) or 0.0)
        careless = float(item.get("careless", 0.0) or 0.0)
        time_pressure = float(item.get("time_pressure", 0.0) or 0.0)
        dominant_error, dominant_value = max(
            {
                "conceptual": conceptual,
                "careless": careless,
                "time_pressure": time_pressure,
            }.items(),
            key=lambda kv: kv[1],
        )
        dominant_errors_by_topic[topic] = {
            "dominant_error": dominant_error,
            "dominant_error_severity": dominant_value,
        }

    payload = {
        "branch": branch,
        "intent": state.get("intent"),
        "message": state.get("message"),
        "diagnosis": state.get("diagnosis"),
        "plan": state.get("plan"),
        "allocation": (state.get("plan") or {}).get("allocation") or state.get("allocation") or [],
        "daily_schedule": (state.get("plan") or {}).get("daily_schedule") or [],
        "plan_topics": [
            str(step.get("topic"))
            for step in ((state.get("plan") or {}).get("checklist") or [])
            if str(step.get("topic") or "").strip()
        ],
        "topic_state": topic_signals,
        "error_state": error_signals,
        "topic_explanations": (state.get("constraints") or {}).get("topic_explanation_inputs") or [],
        "priority_ranked_topics": (state.get("plan") or {}).get("priority_ranked_topics") or [],
        "dominant_errors_by_topic": dominant_errors_by_topic,
        "attempt_evidence": analytics_summary,
        "relevant_attempt_examples": compact_examples,
        "rag_context": rag_context,
        "rag_resources": rag_resources,
        "constraints": state.get("constraints"),
    }

    branch_directive = {
        "TREND": (
            "TREND OUTPUT RULES: keep response concise (max 5 bullets), summarize pattern and 2-3 actionable next steps. "
            "Do not provide full plan structures, minute allocations, or weekly schedules unless PLAN intent is present."
        ),
        "WEAKNESS": (
            "WEAKNESS OUTPUT RULES: keep response concise (max 5 bullets), diagnose likely causes and give 2-3 targeted actions. "
            "When rag_context or rag_resources are present, add a short 'RESOURCES TO REVIEW' section with 2-4 items. "
            "Each item must include: resource source name, one misunderstanding summary tied to the user's wrong-attempt topic/question, and what to review next. "
            "Do not provide full plan structures, minute allocations, or weekly schedules unless PLAN intent is present."
        ),
        "PLAN": (
            "PLAN OUTPUT RULES: output planning content with sections like 'PLAN SUMMARY', 'SCHEDULE', and 'WHY THESE TOPICS' as applicable. "
            "Do NOT change provided minute allocations, day counts, or topic placement by day. "
            "You may paraphrase labels and add concise rationale/task detail while preserving structure. "
            "Explain why the top 2 priority topics are emphasized, reference at least one real attempt example, and include dominant-error-aware tasks. "
            "Render minute values as integers (for example: 90 min, not 90.0 min). "
            "Do not include assumptions. Do not include any separate TREND or WEAKNESS analysis section."
        ),
    }.get(branch, "")

    short_prompt = (
        "You are an analytics-driven learning coach. "
        "Ground all claims in provided analytics and attempt evidence. "
        "Reference at least one concrete question example with topic and context. "
        "Do not expose raw historical metrics or exact attempt stats (no mastery percentages, no exact confidence/time/error-rate numbers). "
        "Never quote numeric values from past attempts; only planned study minutes are allowed as numbers. "
        "When plan topics are provided, use those topic labels verbatim and do not append parenthetical qualifiers. "
        f"{branch_directive} "
        "If rag_context is provided, incorporate relevant note excerpts to explain the specific mistake mechanism and how to improve. "
        "If rag_resources is provided, recommend those resources explicitly with source references. "
        "Cite note sources in plain text like (Source: filename.pdf). "
        "For TREND/WEAKNESS, use natural wording (for example: getting better, slipping, staying steady, repeated concept gap). "
        "Do not start the response with 'The analysis indicates', 'This analysis indicates', or close variants. "
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
        "Do not start the response with 'The analysis indicates', 'This analysis indicates', or close variants. "
        "For TREND/WEAKNESS, avoid rigid statistical words like 'regress/regression'; prefer natural wording such as 'slipping' or 'dipped recently'. "
        "If a plan checklist exists, only discuss topics present in that checklist and do not add extra topics. "
        "When plan_topics are provided, use those labels verbatim and avoid renaming, nesting, or adding parenthetical qualifiers. "
        "Do not present listed topics as subtopics of another topic unless explicitly provided that hierarchy in the input. "
        "If rag_context is provided, ground explanation and corrective actions in those lecturer-note snippets where relevant, and cite sources in plain text like (Source: filename.pdf). "
        "If rag_resources is provided, include a clear 'RESOURCES TO REVIEW' section and connect each resource to a misunderstanding from recent wrong attempts. "
        f"{branch_directive} "
        "For TREND/WEAKNESS: identify 2-3 core issues, explain why each is happening from mastery/trend/retention-risk/error signals, and give specific next micro-actions. "
        "For PLAN: explain and enrich the provided deterministic plan; do not alter minute allocation or daily schedule. "
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

    if branch == "WEAKNESS" and rag_context:
        top_note = rag_context[0]
        note_line = _truncate_text(str(top_note.get("content") or ""), max_len=220)
        if note_line:
            fallback_text = (
                f"{fallback_text} "
                f"A relevant lecturer note suggests: \"{note_line}\" "
                f"(Source: {top_note.get('source')})."
            )
        if rag_resources:
            resource_lines = [
                f"- {item.get('source')}: review {item.get('linked_query') or 'the related concept'}"
                for item in rag_resources[:3]
                if str(item.get("source") or "").strip()
            ]
            if resource_lines:
                fallback_text = f"{fallback_text}\n\nRESOURCES TO REVIEW\n" + "\n".join(resource_lines)

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


def _sanitize_focus_topics(focus_topics: list[str] | None, topic_state: list[dict]) -> tuple[list[str], list[str]]:
    valid_topic_map: dict[str, str] = {}
    for item in topic_state:
        topic = str(item.get("topic") or "").strip()
        if topic:
            valid_topic_map[topic.lower()] = topic

    valid: list[str] = []
    invalid: list[str] = []
    for value in focus_topics or []:
        topic = str(value or "").strip()
        if not topic:
            continue
        canonical = valid_topic_map.get(topic.lower())
        if canonical:
            if canonical not in valid:
                valid.append(canonical)
        else:
            invalid.append(topic)
    return valid, invalid


def _extract_topic_limit_from_message(message: str) -> int | None:
    normalized = message.lower()
    word_to_num = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
    }

    explicit_match = re.search(
        r"\b(?P<count>\d+|one|two|three|four|five|six)\s+(?P<qualifier>weakest|top|main|primary)?\s*topics?\b",
        normalized,
    )
    if explicit_match:
        raw_count = explicit_match.group("count")
        count = int(raw_count) if raw_count.isdigit() else word_to_num.get(raw_count)
        if isinstance(count, int):
            return max(1, min(8, count))

    weakest_match = re.search(r"\b(weakest|worst)\s+(\d+)\b", normalized)
    if weakest_match:
        count = int(weakest_match.group(2))
        return max(1, min(8, count))

    focus_weakest_match = re.search(
        r"\bfocus\s+on\s+(?:helping\s+for\s+)?(?:my\s+)?(?P<count>\d+|one|two|three|four|five|six)\s+weakest\s+topics?\b",
        normalized,
    )
    if focus_weakest_match:
        raw_count = focus_weakest_match.group("count")
        count = int(raw_count) if raw_count.isdigit() else word_to_num.get(raw_count)
        if isinstance(count, int):
            return max(1, min(8, count))

    return None


def _extract_requested_topic_candidates_from_message(message: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", message.lower()).strip()
    if not normalized:
        return []

    candidates: list[str] = []
    patterns = [
        r"\bfor\s+([a-z0-9\s,&/-]{3,80})",
    ]

    generic_terms = {
        "weakness",
        "weaknesses",
        "mistake",
        "mistakes",
        "plan",
        "study",
        "topics",
        "topic",
        "filters",
    }

    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            phrase = str(match.group(1) or "").strip()
            if not phrase:
                continue
            phrase = re.split(r"\b(?:for|about|on|in|with|over|next|this)\b", phrase)[0].strip(" ,.-")
            if not phrase:
                continue
            split_parts = [part.strip(" ,.-") for part in re.split(r",| and |/|;|\+", phrase) if part.strip(" ,.-")]
            for part in split_parts:
                if len(part) >= 3 and part not in generic_terms:
                    candidates.append(part)

    # De-duplicate while preserving order
    deduped: list[str] = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped[:8]


def _interpret_plan_request_with_openai(message: str, topic_state: list[dict]) -> dict[str, Any]:
    available_topics = [str(item.get("topic") or "").strip() for item in topic_state if str(item.get("topic") or "").strip()]
    system_prompt = (
        "You are a planning-intent parser. "
        "Extract structured planning constraints from user text. "
        "Return JSON only with keys: "
        "cover_all_topics(boolean), focus_weakest_n(int|null), specific_topics(string[]), "
        "time_horizon_days(int|null), daily_budget_min(int|null), time_budget_min(int|null), milestones(string[]), notes(string[]). "
        "Set cover_all_topics=true when user says all topics/revision. "
        "Set focus_weakest_n when user asks top/worst/weakest N topics, even if cover_all_topics=true. "
        "Do not invent topics not in available topics list."
    )

    fallback: dict[str, Any] = {
        "cover_all_topics": False,
        "focus_weakest_n": None,
        "specific_topics": [],
        "time_horizon_days": _extract_time_horizon_days_from_message(message),
        "daily_budget_min": None,
        "time_budget_min": None,
        "milestones": [],
        "notes": [],
    }

    normalized = message.lower()
    if "all topics" in normalized or "all topic" in normalized or "revision" in normalized:
        fallback["cover_all_topics"] = True

    extracted_limit = _extract_topic_limit_from_message(message)
    if extracted_limit is not None:
        fallback["focus_weakest_n"] = extracted_limit

    extracted_specific = _extract_focus_topics_from_message(message, topic_state)
    if extracted_specific:
        fallback["specific_topics"] = extracted_specific

    per_day_match = re.search(r"(\d+)\s*(hour|hours|hr|hrs|minute|minutes|min|mins)\s*(?:a|per)\s*day\b", normalized)
    if per_day_match:
        value = int(per_day_match.group(1))
        unit = per_day_match.group(2)
        fallback["daily_budget_min"] = value * 60 if unit.startswith("h") else value

    if re.search(r"\bexam\b", normalized):
        fallback["milestones"].append("exam")

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=_get_openai_model(),
            max_completion_tokens=350,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps({"message": message, "available_topics": available_topics}, default=str),
                },
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            return fallback
        parsed = json.loads(content)

        specific_topics = []
        if isinstance(parsed.get("specific_topics"), list):
            requested = [str(item) for item in parsed.get("specific_topics")]
            specific_topics, _ = _sanitize_focus_topics(requested, topic_state)

        parsed_focus_weakest_n = parsed.get("focus_weakest_n")
        if not isinstance(parsed_focus_weakest_n, int):
            parsed_focus_weakest_n = parsed.get("topic_limit")

        interpreted = {
            "cover_all_topics": bool(parsed.get("cover_all_topics")) if "cover_all_topics" in parsed else bool(fallback.get("cover_all_topics")),
            "focus_weakest_n": int(parsed_focus_weakest_n) if isinstance(parsed_focus_weakest_n, int) else fallback.get("focus_weakest_n"),
            "specific_topics": specific_topics or fallback.get("specific_topics") or [],
            "time_horizon_days": int(parsed["time_horizon_days"]) if isinstance(parsed.get("time_horizon_days"), int) else fallback.get("time_horizon_days"),
            "daily_budget_min": int(parsed["daily_budget_min"]) if isinstance(parsed.get("daily_budget_min"), int) else fallback.get("daily_budget_min"),
            "time_budget_min": int(parsed["time_budget_min"]) if isinstance(parsed.get("time_budget_min"), int) else fallback.get("time_budget_min"),
            "milestones": [str(item) for item in parsed.get("milestones") or []][:6],
            "notes": [str(item) for item in parsed.get("notes") or []][:6],
        }

        if isinstance(interpreted.get("focus_weakest_n"), int):
            interpreted["focus_weakest_n"] = max(1, min(8, int(interpreted["focus_weakest_n"])))

        if interpreted.get("specific_topics") and not interpreted.get("cover_all_topics") and not isinstance(interpreted.get("focus_weakest_n"), int):
            interpreted["focus_weakest_n"] = None
        return interpreted
    except Exception:
        return fallback


def _normalize_plan_constraints(
    message: str,
    constraints: dict | None,
    topic_state: list[dict],
    clarification_answer: dict | None,
) -> tuple[dict, bool, dict | None]:
    merged = dict(constraints or {})
    invalid_focus_topics: list[str] = []
    requested_topic_candidates = _extract_requested_topic_candidates_from_message(message)
    interpreted_plan = _interpret_plan_request_with_openai(message, topic_state)
    merged["plan_interpretation"] = interpreted_plan

    if bool(interpreted_plan.get("cover_all_topics")):
        merged["cover_all_topics"] = True
        merged["topic_limit"] = max(1, len(topic_state))

    if isinstance(interpreted_plan.get("focus_weakest_n"), int):
        merged["focus_weakest_n"] = int(interpreted_plan["focus_weakest_n"])
        if not bool(merged.get("cover_all_topics")):
            merged["topic_limit"] = int(interpreted_plan["focus_weakest_n"])

    if interpreted_plan.get("specific_topics"):
        merged["focus_topics"] = list(interpreted_plan.get("specific_topics") or [])

    if isinstance(interpreted_plan.get("time_horizon_days"), int) and not isinstance(merged.get("time_horizon_days"), int):
        merged["time_horizon_days"] = int(interpreted_plan["time_horizon_days"])

    if isinstance(interpreted_plan.get("daily_budget_min"), int) and not isinstance(merged.get("daily_budget_min"), int):
        merged["daily_budget_min"] = int(interpreted_plan["daily_budget_min"])

    if isinstance(interpreted_plan.get("time_budget_min"), int) and not isinstance(merged.get("time_budget_min"), int):
        merged["time_budget_min"] = int(interpreted_plan["time_budget_min"])

    milestones = [str(item) for item in interpreted_plan.get("milestones") or [] if str(item).strip()]
    if milestones:
        merged["milestones"] = milestones

    extracted_horizon_days = _extract_time_horizon_days_from_message(message)
    if extracted_horizon_days is not None and not isinstance(merged.get("time_horizon_days"), int):
        merged["time_horizon_days"] = int(extracted_horizon_days)

    extracted_budget_any = _extract_time_budget_from_message(message)
    daily_hint = re.search(r"(\d+)\s*(hour|hours|hr|hrs|minute|minutes|min|mins)\s*(?:a|per)\s*day\b", message.lower())
    has_daily_hint = bool(daily_hint)

    if extracted_budget_any is not None and not isinstance(merged.get("daily_budget_min"), int) and has_daily_hint:
        merged["daily_budget_min"] = int(extracted_budget_any)

    # Only treat parsed budget as total budget when it was not expressed as per-day.
    if not isinstance(merged.get("time_budget_min"), int) and extracted_budget_any is not None and not has_daily_hint:
        merged["time_budget_min"] = int(extracted_budget_any)

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

    extracted_topic_limit = _extract_topic_limit_from_message(message)
    if extracted_topic_limit is not None:
        if bool(merged.get("cover_all_topics")):
            if not isinstance(merged.get("focus_weakest_n"), int):
                merged["focus_weakest_n"] = int(extracted_topic_limit)
        elif not isinstance(merged.get("topic_limit"), int):
            merged["topic_limit"] = int(extracted_topic_limit)

    if clarification_answer:
        if isinstance(clarification_answer.get("time_budget_min"), int):
            merged["time_budget_min"] = int(clarification_answer["time_budget_min"])

        if isinstance(clarification_answer.get("time_horizon_days"), int):
            merged["time_horizon_days"] = int(clarification_answer["time_horizon_days"])

        if isinstance(clarification_answer.get("daily_budget_min"), int):
            merged["daily_budget_min"] = int(clarification_answer["daily_budget_min"])

        if isinstance(clarification_answer.get("topic_limit"), int):
            if bool(merged.get("cover_all_topics")):
                merged["focus_weakest_n"] = int(clarification_answer["topic_limit"])
            else:
                merged["topic_limit"] = int(clarification_answer["topic_limit"])

        focus_note = clarification_answer.get("focus_note")
        if isinstance(focus_note, str) and focus_note.strip():
            extracted_from_note = _extract_focus_topics_from_message(focus_note, topic_state)
            if extracted_from_note:
                merged["focus_topics"] = extracted_from_note

        follow_up_topics = clarification_answer.get("focus_topics")
        if isinstance(follow_up_topics, list):
            cleaned_topics = [str(topic) for topic in follow_up_topics if str(topic).strip()]
            if cleaned_topics:
                merged["focus_topics"] = sorted(set(cleaned_topics))

        if bool(clarification_answer.get("generic_plan") or clarification_answer.get("skip_details")):
            merged["generic_plan"] = True

    # Validate focus topics against known analytics topics.
    if isinstance(merged.get("focus_topics"), list):
        valid_focus_topics, invalid_focus_topics = _sanitize_focus_topics(merged.get("focus_topics"), topic_state)
        if valid_focus_topics:
            merged["focus_topics"] = valid_focus_topics
        else:
            merged.pop("focus_topics", None)

    # Re-derive total budget after clarification because follow-up can provide
    # time_horizon_days / daily_budget_min without explicit time_budget_min.
    if not isinstance(merged.get("time_budget_min"), int) and isinstance(merged.get("time_horizon_days"), int):
        total_budget, budget_basis = _derive_total_budget_from_horizon(
            time_horizon_days=int(merged["time_horizon_days"]),
            explicit_daily_budget_min=(
                int(merged["daily_budget_min"]) if isinstance(merged.get("daily_budget_min"), int) else None
            ),
        )
        merged["time_budget_min"] = total_budget
        merged["time_budget_basis"] = budget_basis

    if invalid_focus_topics:
        merged["invalid_focus_topics"] = invalid_focus_topics

    if requested_topic_candidates and not merged.get("focus_topics"):
        valid_topic_names = {
            str(item.get("topic") or "").strip().lower()
            for item in topic_state
            if str(item.get("topic") or "").strip()
        }
        unmatched = [topic for topic in requested_topic_candidates if topic.lower() not in valid_topic_names]
        if unmatched:
            merged["invalid_focus_topics"] = sorted(set((merged.get("invalid_focus_topics") or []) + unmatched))

    assumptions: list[str] = []

    if not isinstance(merged.get("time_horizon_days"), int) or int(merged.get("time_horizon_days", 0)) <= 0:
        merged["time_horizon_days"] = 7
        assumptions.append("default_horizon_days=7")

    if not isinstance(merged.get("daily_budget_min"), int) or int(merged.get("daily_budget_min", 0)) <= 0:
        merged["daily_budget_min"] = 60
        assumptions.append("default_daily_budget_min=60")

    if not isinstance(merged.get("time_budget_min"), int) or int(merged.get("time_budget_min", 0)) <= 0:
        total_budget, budget_basis = _derive_total_budget_from_horizon(
            time_horizon_days=int(merged.get("time_horizon_days", 7)),
            explicit_daily_budget_min=int(merged.get("daily_budget_min", 60)),
        )
        merged["time_budget_min"] = total_budget
        merged["time_budget_basis"] = budget_basis
        assumptions.append(f"derived_total_budget_min={total_budget}")

    if not isinstance(merged.get("topic_limit"), int) or int(merged.get("topic_limit", 0)) <= 0:
        merged["topic_limit"] = 3
        assumptions.append("default_topic_limit=3")

    if assumptions:
        merged["assumptions"] = assumptions

    if isinstance(merged.get("topic_limit"), int) and int(merged.get("topic_limit", 0)) > 0:
        merged["topic_limit"] = max(1, min(len(topic_state) if topic_state else 8, int(merged["topic_limit"])))

    if isinstance(merged.get("focus_weakest_n"), int) and int(merged.get("focus_weakest_n", 0)) > 0:
        merged["focus_weakest_n"] = max(1, min(len(topic_state) if topic_state else 8, int(merged["focus_weakest_n"])))

    return merged, False, None


def _classify_intent_with_openai(message: str) -> tuple[list[str], str, float, str, str | None]:
    system_prompt = (
        "You are an intent classifier for a learning coach. "
        "Classify the query into one or more intents from: TREND, WEAKNESS, PLAN. "
        "Use multiple intents if the user asks for analysis plus what to do next. "
        "TREND refers to progress/regression over time. "
        "WEAKNESS refers to struggling topics/mistakes/patterns/why. "
        "PLAN refers to explicit requests for a study plan, schedule, allocation, timeline, or structured roadmap. "
        "Do NOT classify as PLAN when the user only asks for diagnosis/advice without explicit planning request. "
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

    constraints = state.get("constraints") or {}
    plan_mode_enabled = bool(constraints.get("plan_mode"))
    if plan_mode_enabled:
        intents = ["PLAN"]
        primary_intent = "PLAN"
        confidence = 1.0
        source = "client_override"
        error = None
    else:
        intents, primary_intent, confidence, source, error = _classify_intent_with_openai(message)
        if "PLAN" in intents and not _has_explicit_plan_request(message):
            intents = [intent for intent in intents if intent != "PLAN"]
            if not intents:
                intents = ["WEAKNESS"]
            primary_intent = intents[0]

    if not plan_mode_enabled and "PLAN" in intents:
        state["plan_mode_required_notice"] = True

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

    if bool(state.get("plan_mode_required_notice")):
        state["needs_clarification"] = False
        state["clarification_question"] = None
        _append_trace(
            state,
            "uncertainty_gate",
            {
                "needs_clarification": False,
                "intent": coach_state.intent,
                "intents": intents,
                "plan_mode_required_notice": True,
            },
        )
        return state

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

    # Prefer an error profile from the same weakest topic to avoid cross-topic
    # phrasing like "Topic A, specifically Topic B".
    primary_issue = top_error
    if weakest_topic and error_state:
        weakest_topic_name = str(weakest_topic.get("topic") or "").strip().lower()
        matched_error = next(
            (
                item
                for item in error_state
                if str(item.get("topic") or "").strip().lower() == weakest_topic_name
            ),
            None,
        )
        if matched_error:
            primary_issue = matched_error

    state["diagnosis"] = {
        "primary_topic": weakest_topic.get("topic") if weakest_topic else None,
        "primary_issue": primary_issue,
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
        "rag_sources": [
            item.get("source")
            for item in ((state.get("rag_by_branch") or {}).get("WEAKNESS") or [])
            if str(item.get("source") or "").strip()
        ][:6],
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


def _format_minutes(value: float) -> str:
    return str(int(round(float(value))))


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(value) for value in values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = max(0.0, min(len(sorted_values) - 1, (len(sorted_values) - 1) * q))
    lower = int(index)
    upper = min(len(sorted_values) - 1, lower + 1)
    weight = index - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _confidence_bucket(value: Any) -> str:
    if value is None:
        return "med"
    numeric = float(value or 0.0)
    if numeric < 0.4:
        return "low"
    if numeric > 0.7:
        return "high"
    return "med"


def _speed_bucket(time_taken_sec: Any, threshold_sec: float) -> str:
    if time_taken_sec is None:
        return "normal"
    seconds = float(time_taken_sec or 0.0)
    threshold = max(1.0, float(threshold_sec or 0.0))
    if seconds <= threshold:
        return "fast"
    if seconds >= threshold * 1.8:
        return "slow"
    return "normal"


def _build_speed_thresholds(attempt_evidence: dict) -> tuple[float, dict[str, float]]:
    samples = list((attempt_evidence or {}).get("all_samples") or [])
    global_times = [float(item.get("time_taken_sec") or 0.0) for item in samples if item.get("time_taken_sec") is not None]
    global_p25 = _quantile(global_times, 0.25) if global_times else 30.0

    per_topic: dict[str, list[float]] = {}
    for item in samples:
        topic = str(item.get("topic") or "").strip().lower()
        if not topic:
            continue
        value = item.get("time_taken_sec")
        if value is None:
            continue
        per_topic.setdefault(topic, []).append(float(value))

    per_topic_p25 = {topic: _quantile(values, 0.25) for topic, values in per_topic.items() if values}
    return float(global_p25), per_topic_p25


def _confidence_pattern(correct: bool, confidence: Any) -> str:
    if confidence is None:
        return "mixed_confidence"
    value = float(confidence or 0.0)
    if not correct and value >= 0.7:
        return "overconfident_error"
    if not correct and value <= 0.4:
        return "low_confidence"
    if correct and value <= 0.4:
        return "cautious_correct"
    if correct and value >= 0.7:
        return "confident_correct"
    return "mixed_confidence"


def _behavior_pattern(dominant_error: str, sample: dict | None) -> str:
    if dominant_error == "time_pressure":
        return "rushed"
    if dominant_error == "careless":
        return "verification_lapse"
    if sample and bool(sample.get("correct")):
        return "partial_understanding"
    return "uncertain_reasoning"


def _behavioral_reason(dominant_error: str, trend_direction: str, retention_status: str, topic: str = "") -> str:
    conceptual_bank = [
        "Definition-level recall is shaky in key ideas.",
        "Adjacent concepts are getting mixed under question pressure.",
        "Conceptual framing is unstable before answer selection.",
    ]
    careless_bank = [
        "Answer checking is inconsistent despite workable understanding.",
        "Verification steps are skipped, causing avoidable slips.",
        "Selection errors appear when options are scanned too quickly.",
    ]
    time_bank = [
        "Timer pressure triggers premature commits.",
        "Speed-driven decisions reduce option evaluation quality.",
        "Fast pacing is outrunning reasoning depth.",
    ]

    if dominant_error == "careless":
        bank = careless_bank
    elif dominant_error == "time_pressure":
        bank = time_bank
    else:
        bank = conceptual_bank

    seed = f"{topic}|{dominant_error}|{trend_direction}|{retention_status}"
    index = int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16) % len(bank)

    urgency = " Needs urgent correction." if trend_direction == "slipping" else ""
    retention_note = " Add spaced refresh checkpoints." if retention_status == "high risk" else ""
    return bank[index] + urgency + retention_note


def _select_micro_evidence_for_topic(
    *,
    topic: str,
    dominant_error: str,
    topic_samples: list[dict],
    global_p25: float,
    topic_p25: float | None,
) -> list[dict]:
    threshold = float(topic_p25 if topic_p25 is not None else global_p25)
    wrong = [item for item in topic_samples if not bool(item.get("correct", False))]
    right = [item for item in topic_samples if bool(item.get("correct", False))]

    def _pick_wrong() -> dict | None:
        if not wrong:
            return None
        if dominant_error == "time_pressure":
            candidate = next(
                (item for item in wrong if _speed_bucket(item.get("time_taken_sec"), threshold) == "fast"),
                None,
            )
            if candidate:
                return candidate
        if dominant_error == "careless":
            candidate = next(
                (
                    item
                    for item in wrong
                    if _confidence_bucket(item.get("confidence")) == "high"
                    and _speed_bucket(item.get("time_taken_sec"), threshold) in {"fast", "normal"}
                ),
                None,
            )
            if candidate:
                return candidate
        if dominant_error == "conceptual":
            candidate = next((item for item in wrong if _confidence_bucket(item.get("confidence")) == "low"), None)
            if candidate:
                return candidate
        return wrong[0]

    picked: list[dict] = []
    first_wrong = _pick_wrong()
    if first_wrong:
        picked.append(first_wrong)

    second_wrong = next((item for item in wrong if item is not first_wrong), None)
    if second_wrong:
        picked.append(second_wrong)

    recent_correct = right[0] if right else None
    if recent_correct:
        picked.append(recent_correct)

    evidence_items: list[dict] = []
    for sample in picked[:3]:
        correct = bool(sample.get("correct", False))
        evidence_items.append(
            {
                "question_snippet": _truncate_text(str(sample.get("question_content") or ""), max_len=140),
                "outcome": "correct" if correct else "incorrect",
                "mode": "timed" if sample.get("time_taken_sec") is not None else "untimed",
                "confidence_bucket": _confidence_bucket(sample.get("confidence")),
                "speed_bucket": _speed_bucket(sample.get("time_taken_sec"), threshold),
                "confidence_pattern": _confidence_pattern(correct, sample.get("confidence")),
                "behavior_pattern": _behavior_pattern(dominant_error, sample),
                "question_type": str(sample.get("question_type") or "mixed").strip().lower(),
                "difficulty": str(sample.get("difficulty") or "medium").strip().lower(),
                "tags": [str(tag).strip().lower() for tag in (sample.get("tags") or []) if str(tag).strip()],
            }
        )
    return evidence_items


def _build_topic_explanation_inputs(
    topic_state: list[dict],
    error_state: list[dict],
    attempt_evidence: dict,
    priority_ranked_topics: list[dict],
) -> list[dict]:
    topic_lookup = {
        str(item.get("topic") or "").strip().lower(): item
        for item in (topic_state or [])
        if str(item.get("topic") or "").strip()
    }
    error_lookup = {
        str(item.get("topic") or "").strip().lower(): item
        for item in (error_state or [])
        if str(item.get("topic") or "").strip()
    }

    all_samples = list((attempt_evidence or {}).get("all_samples") or [])
    global_p25, per_topic_p25 = _build_speed_thresholds(attempt_evidence)

    def _mastery_level(value: float) -> str:
        if value < 0.45:
            return "weak"
        if value < 0.7:
            return "developing"
        return "strong"

    def _trend_direction(value: float) -> str:
        if value <= -0.05:
            return "slipping"
        if value >= 0.05:
            return "improving"
        return "stable"

    def _retention_status(value: float) -> str:
        if value >= 0.66:
            return "high risk"
        if value >= 0.33:
            return "medium risk"
        return "low risk"

    enriched: list[dict] = []
    for rank, item in enumerate(priority_ranked_topics or [], start=1):
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue

        topic_key = topic.lower()
        topic_meta = topic_lookup.get(topic_key, {})
        error_meta = error_lookup.get(topic_key, {})

        mastery = float(item.get("mastery", topic_meta.get("mastery", 0.0)) or 0.0)
        trend = float(item.get("trend", topic_meta.get("trend", 0.0)) or 0.0)
        decay_risk = float(item.get("decay_risk", topic_meta.get("decay_risk", 0.0)) or 0.0)

        conceptual = float(error_meta.get("conceptual", 0.0) or 0.0)
        careless = float(error_meta.get("careless", 0.0) or 0.0)
        time_pressure = float(error_meta.get("time_pressure", 0.0) or 0.0)
        dominant_error, dominant_error_severity = max(
            {
                "conceptual": conceptual,
                "careless": careless,
                "time_pressure": time_pressure,
            }.items(),
            key=lambda kv: kv[1],
        )

        topic_samples = [
            sample
            for sample in all_samples
            if str(sample.get("topic") or "").strip().lower() == topic_key
        ]
        evidence_items = _select_micro_evidence_for_topic(
            topic=topic,
            dominant_error=dominant_error,
            topic_samples=topic_samples,
            global_p25=global_p25,
            topic_p25=per_topic_p25.get(topic_key),
        )
        representative_attempt = evidence_items[0] if evidence_items else {
            "question_snippet": "",
            "outcome": "incorrect",
            "mode": "timed",
            "confidence_bucket": "med",
            "speed_bucket": "normal",
            "confidence_pattern": "mixed_confidence",
            "behavior_pattern": _behavior_pattern(dominant_error, None),
        }

        trend_direction = _trend_direction(trend)
        retention_status = _retention_status(decay_risk)

        enriched.append(
            {
                "topic": topic,
                "priority_score": float(item.get("priority_score", 0.0) or 0.0),
                "priority_rank": rank,
                "mastery_level": _mastery_level(mastery),
                "trend_direction": trend_direction,
                "retention_status": retention_status,
                "dominant_error": dominant_error,
                "behavioral_reason": _behavioral_reason(dominant_error, trend_direction, retention_status, topic),
                "representative_attempt": representative_attempt,
                "micro_evidence": evidence_items,
            }
        )

    return enriched


def _build_behavior_corrective_task_bank(topic_explanations: list[dict]) -> dict[str, list[str]]:
    task_bank: dict[str, list[str]] = {}

    task_library: dict[str, list[dict[str, Any]]] = {
        "conceptual": [
            {"id": "c_def_1", "question_type": "definition", "difficulty": "easy", "tags": ["concept"], "template": "For {topic}, run a 20-minute definition rebuild, answer 10 quick-recall prompts, then re-explain 3 misses in your own words."},
            {"id": "c_def_2", "question_type": "definition", "difficulty": "medium", "tags": ["concept"], "template": "Do 2 concept cycles on {topic}: 8 recall cards per cycle, then review each wrong card with a one-line correction."},
            {"id": "c_mcq_1", "question_type": "mcq", "difficulty": "easy", "tags": ["classification"], "template": "Solve 12 {topic} MCQs focused on core distinctions, then audit every distractor you selected and why it was wrong."},
            {"id": "c_mcq_2", "question_type": "mcq", "difficulty": "medium", "tags": ["tradeoff"], "template": "Attempt 2 sets of 6 {topic} MCQs, then do a retrieval recap and rewrite explanations for all incorrect choices."},
            {"id": "c_scn_1", "question_type": "scenario", "difficulty": "medium", "tags": ["persona", "context"], "template": "Work through 4 {topic} scenarios, map each to the correct principle, then review mistakes with a corrected reasoning path."},
            {"id": "c_scn_2", "question_type": "scenario", "difficulty": "hard", "tags": ["application"], "template": "Do a 25-minute scenario drill for {topic} (5 items), then replay each miss and state the exact concept you overlooked."},
            {"id": "c_tag_1", "question_type": "mixed", "difficulty": "medium", "tags": ["iteration", "evaluation"], "template": "For {topic}, complete an iteration-vs-evaluation contrast set (8 items), then review and annotate each confusion point."},
            {"id": "c_tag_2", "question_type": "mixed", "difficulty": "hard", "tags": ["ethnography", "persona"], "template": "Run an ethnography/persona mapping drill in {topic}: 6 prompts, then explain each mismatch and how to correct it."},
            {"id": "c_ret_1", "question_type": "mixed", "difficulty": "medium", "tags": ["retention"], "template": "Use spaced retrieval for {topic}: 3 mini rounds of 5 prompts each, then review repeated misses and summarize fixes."},
            {"id": "c_ret_2", "question_type": "mixed", "difficulty": "hard", "tags": ["retention"], "template": "Do a delayed-recall block for {topic} (10 questions), then review error clusters and write one corrective rule per cluster."},
            {"id": "c_expl_1", "question_type": "explanation", "difficulty": "medium", "tags": ["reasoning"], "template": "Pick 5 {topic} misses, explain the correct answer out loud, then check if your explanation matches the concept boundary."},
            {"id": "c_expl_2", "question_type": "explanation", "difficulty": "hard", "tags": ["reasoning"], "template": "Run a teach-back set for {topic}: answer 6 items and justify each choice, then review where explanation quality breaks."},
        ],
        "careless": [
            {"id": "k_verify_1", "question_type": "mcq", "difficulty": "easy", "tags": ["verification"], "template": "For {topic}, do 10 questions in slow-pass mode, apply a 2-step verification checklist, then review all corrected slips."},
            {"id": "k_verify_2", "question_type": "mcq", "difficulty": "medium", "tags": ["verification"], "template": "Run 2 rounds of 6 {topic} items with deliberate pacing, then audit each error for missed keyword or option mismatch."},
            {"id": "k_key_1", "question_type": "definition", "difficulty": "easy", "tags": ["keyword"], "template": "Answer 8 {topic} prompts while underlining keywords first, then review any miss where a key term was ignored."},
            {"id": "k_key_2", "question_type": "scenario", "difficulty": "medium", "tags": ["keyword"], "template": "Solve 5 {topic} scenarios with forced keyword extraction, then re-check decisions and log avoidable reading errors."},
            {"id": "k_option_1", "question_type": "mcq", "difficulty": "medium", "tags": ["options"], "template": "Do an option-elimination drill for {topic} (12 MCQs), then review each wrong answer and identify the ignored contradiction."},
            {"id": "k_option_2", "question_type": "mcq", "difficulty": "hard", "tags": ["options"], "template": "Run a 20-minute precision set for {topic}, then replay 4 misreads and write the correct elimination sequence."},
            {"id": "k_check_1", "question_type": "mixed", "difficulty": "medium", "tags": ["checklist"], "template": "Use a final-answer checklist on 10 {topic} questions, then review where checklist steps prevented or missed errors."},
            {"id": "k_check_2", "question_type": "mixed", "difficulty": "hard", "tags": ["checklist"], "template": "Do 2 cycles of checklist-driven {topic} questions (6 each), then compare first-pass vs verified outcomes."},
            {"id": "k_conf_1", "question_type": "mixed", "difficulty": "medium", "tags": ["confidence"], "template": "For {topic}, mark confidence before answering 8 items, then review overconfident errors and define a verification trigger."},
            {"id": "k_conf_2", "question_type": "scenario", "difficulty": "hard", "tags": ["confidence"], "template": "Complete 6 {topic} scenarios, flag high-confidence picks, then inspect where confidence outpaced evidence."},
            {"id": "k_peer_1", "question_type": "explanation", "difficulty": "medium", "tags": ["explain"], "template": "Do a peer-check simulation for {topic}: justify 6 answers and review points where verification logic was skipped."},
            {"id": "k_peer_2", "question_type": "explanation", "difficulty": "hard", "tags": ["explain"], "template": "Run a controlled-accuracy session on {topic} (18 minutes), then review slips with a 'why this trap worked' note."},
        ],
        "time_pressure": [
            {"id": "t_sprint_1", "question_type": "mcq", "difficulty": "easy", "tags": ["timed"], "template": "Run a timed 12-minute {topic} sprint (8 questions), then review all rushed misses and write corrected decision steps."},
            {"id": "t_sprint_2", "question_type": "mcq", "difficulty": "medium", "tags": ["timed"], "template": "Do 2 timed blocks for {topic} (10 minutes each), then compare accuracy and identify where pacing broke reasoning."},
            {"id": "t_scn_1", "question_type": "scenario", "difficulty": "medium", "tags": ["timed", "scenario"], "template": "Attempt 5 timed {topic} scenarios in 15 minutes, then replay each incorrect fast decision with full reasoning."},
            {"id": "t_scn_2", "question_type": "scenario", "difficulty": "hard", "tags": ["timed", "scenario"], "template": "Run a 20-minute scenario mock for {topic}, then review where time pressure forced premature commits."},
            {"id": "t_pace_1", "question_type": "mixed", "difficulty": "easy", "tags": ["pacing"], "template": "Practice paced answering on {topic}: 10 items with per-item time caps, then review misses caused by rushing."},
            {"id": "t_pace_2", "question_type": "mixed", "difficulty": "medium", "tags": ["pacing"], "template": "Use a 3-phase timing plan on {topic} (scan/decide/verify), then audit where phases collapsed under pressure."},
            {"id": "t_post_1", "question_type": "mixed", "difficulty": "medium", "tags": ["post-analysis"], "template": "Complete a 15-minute timed set for {topic}, then classify each wrong answer as rush, misread, or concept miss."},
            {"id": "t_post_2", "question_type": "mixed", "difficulty": "hard", "tags": ["post-analysis"], "template": "Do 2 rapid rounds on {topic}, then perform a post-timing analysis and rewrite 3 improved response routines."},
            {"id": "t_conf_1", "question_type": "mcq", "difficulty": "medium", "tags": ["confidence"], "template": "Run a timed confidence-check drill on {topic} (8 items), then review where high-confidence fast picks were wrong."},
            {"id": "t_conf_2", "question_type": "scenario", "difficulty": "hard", "tags": ["confidence"], "template": "Attempt timed scenario choices in {topic}, then contrast first-choice speed with second-pass corrected answers."},
            {"id": "t_ret_1", "question_type": "mixed", "difficulty": "medium", "tags": ["retention"], "template": "Do a timed retrieval set for {topic} (3 short blocks), then review which recalls failed under speed and why."},
            {"id": "t_ret_2", "question_type": "mixed", "difficulty": "hard", "tags": ["retention"], "template": "Run a high-pressure mixed drill for {topic} (20 minutes), then debrief misses and set pacing guardrails for next run."},
        ],
    }

    used_template_ids: set[str] = set()
    for index, item in enumerate(topic_explanations or []):
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue

        dominant_error = str(item.get("dominant_error") or "conceptual").strip()
        if dominant_error not in task_library:
            dominant_error = "conceptual"

        evidence = list(item.get("micro_evidence") or [])
        reference = evidence[0] if evidence else {}
        question_type = str(reference.get("question_type") or "mixed").strip().lower()
        difficulty = str(reference.get("difficulty") or "medium").strip().lower()
        tags = [str(tag).strip().lower() for tag in (reference.get("tags") or []) if str(tag).strip()]

        catalog = list(task_library[dominant_error])
        matched = [
            template
            for template in catalog
            if question_type in {"", "mixed"} or template.get("question_type") in {question_type, "mixed"}
        ] or catalog
        matched = [
            template
            for template in matched
            if template.get("difficulty") in {difficulty, "medium"}
        ] or matched
        if tags:
            tag_matched = [
                template
                for template in matched
                if any(tag in (template.get("tags") or []) for tag in tags)
            ]
            if tag_matched:
                matched = tag_matched

        seed = f"{topic}|{dominant_error}|{question_type}|{difficulty}|{'-'.join(sorted(tags))}|{index}"
        start = int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16) % max(1, len(matched))
        ordered = matched[start:] + matched[:start]
        ordered += [template for template in catalog if template not in ordered]

        selected_templates: list[dict[str, Any]] = []
        for template in ordered:
            template_id = str(template.get("id") or "")
            if template_id and template_id in used_template_ids:
                continue
            selected_templates.append(template)
            if template_id:
                used_template_ids.add(template_id)
            if len(selected_templates) >= 4:
                break

        if len(selected_templates) < 4:
            for template in ordered:
                if template not in selected_templates:
                    selected_templates.append(template)
                if len(selected_templates) >= 4:
                    break

        task_bank[topic] = [str(template.get("template") or "").format(topic=topic) for template in selected_templates if str(template.get("template") or "").strip()]

    return task_bank


def _compute_topic_priority_scores(topic_state: list[dict], error_state: list[dict]) -> list[dict]:
    error_lookup: dict[str, dict[str, Any]] = {}
    for item in error_state or []:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
        conceptual = float(item.get("conceptual", 0.0) or 0.0)
        careless = float(item.get("careless", 0.0) or 0.0)
        time_pressure = float(item.get("time_pressure", 0.0) or 0.0)
        dominant_error, dominant_severity = max(
            {
                "conceptual": conceptual,
                "careless": careless,
                "time_pressure": time_pressure,
            }.items(),
            key=lambda kv: kv[1],
        )
        error_lookup[topic.lower()] = {
            "dominant_error": dominant_error,
            "dominant_error_severity": float(dominant_severity),
        }

    scored: list[dict[str, Any]] = []
    for item in topic_state or []:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue

        mastery = float(item.get("mastery", 0.0) or 0.0)
        trend = float(item.get("trend", 0.0) or 0.0)
        decay_risk = float(item.get("decay_risk", 0.0) or 0.0)
        error_meta = error_lookup.get(topic.lower(), {"dominant_error": "conceptual", "dominant_error_severity": 0.0})
        dominant_error = str(error_meta.get("dominant_error") or "conceptual")
        dominant_error_severity = float(error_meta.get("dominant_error_severity", 0.0) or 0.0)

        priority_score = (
            (1 - mastery) * 0.5
            + max(0.0, -trend) * 0.2
            + decay_risk * 0.2
            + dominant_error_severity * 0.1
        )

        scored.append(
            {
                "topic": topic,
                "priority_score": float(priority_score),
                "mastery": mastery,
                "trend": trend,
                "decay_risk": decay_risk,
                "dominant_error": dominant_error,
                "dominant_error_severity": dominant_error_severity,
            }
        )

    if not scored:
        return []

    total = sum(float(item.get("priority_score", 0.0) or 0.0) for item in scored)
    if total <= 0:
        uniform = 1.0 / len(scored)
        for item in scored:
            item["priority_score"] = uniform
    else:
        for item in scored:
            item["priority_score"] = float(item["priority_score"]) / total

    return sorted(scored, key=lambda item: item.get("priority_score", 0.0), reverse=True)


def _allocate_minutes_by_priority(priority_topics: list[dict], total_budget_min: int) -> list[dict]:
    ranked = [item for item in (priority_topics or []) if str(item.get("topic") or "").strip()]
    budget = int(total_budget_min or 0)
    if not ranked or budget <= 0:
        return []

    min_per_topic = 15

    def _strict_min_total(count: int) -> int:
        return (count * min_per_topic) + (count * (count - 1) // 2)

    max_topics = len(ranked)
    while max_topics > 1 and _strict_min_total(max_topics) > budget:
        max_topics -= 1
    ranked = ranked[:max_topics]

    score_sum = sum(float(item.get("priority_score", 0.0) or 0.0) for item in ranked)
    if score_sum <= 0:
        normalized = [1.0 / len(ranked)] * len(ranked)
    else:
        normalized = [float(item.get("priority_score", 0.0) or 0.0) / score_sum for item in ranked]

    base = [min_per_topic + (len(ranked) - idx - 1) for idx in range(len(ranked))]
    remaining_budget = budget - sum(base)
    if remaining_budget < 0:
        remaining_budget = 0

    extras = [int(round(weight * remaining_budget)) for weight in normalized]
    extra_diff = remaining_budget - sum(extras)
    if extras:
        extras[0] += extra_diff

    minutes = [base[idx] + extras[idx] for idx in range(len(ranked))]

    for index in range(len(minutes) - 1):
        guard = 0
        while minutes[index] <= minutes[index + 1] and guard < 300:
            donor = next((j for j in range(len(minutes) - 1, index, -1) if minutes[j] > min_per_topic), None)
            if donor is None:
                break
            minutes[donor] -= 1
            minutes[index] += 1
            guard += 1

    diff = budget - sum(minutes)
    if diff != 0 and minutes:
        minutes[0] += diff

    result = []
    for idx, item in enumerate(ranked):
        result.append({"topic": str(item.get("topic")), "minutes": int(minutes[idx])})

    return result


def _build_daily_distribution(allocation: list[dict], horizon_days: int, daily_budget_min: int) -> list[dict]:
    if not allocation or horizon_days <= 0 or daily_budget_min <= 0:
        return []

    ranked = [
        {"topic": str(item.get("topic")), "minutes": int(item.get("minutes", 0) or 0)}
        for item in allocation
        if str(item.get("topic") or "").strip() and int(item.get("minutes", 0) or 0) > 0
    ]
    if not ranked:
        return []

    topic_order = [item["topic"] for item in ranked]
    remaining = {item["topic"]: int(item["minutes"]) for item in ranked}
    max_topics_per_day = 4 if daily_budget_min >= 100 else 3
    step_chunk = 10

    day_preferences: list[list[str]] = []
    for day_idx in range(horizon_days):
        if day_idx == 0:
            pref = topic_order[:max_topics_per_day]
        elif day_idx == 1 and len(topic_order) > 1:
            pref = [topic_order[1]] + [topic for topic in topic_order if topic != topic_order[1]][: max_topics_per_day - 1]
        elif day_idx == horizon_days - 1:
            pref = topic_order[: min(3, len(topic_order))]
        else:
            start = day_idx % len(topic_order)
            rotated = topic_order[start:] + topic_order[:start]
            pref = rotated[:max_topics_per_day]
        day_preferences.append(pref)

    if horizon_days >= 7 and topic_order:
        top_topic = topic_order[0]
        appearance_days = [idx for idx, pref in enumerate(day_preferences) if top_topic in pref]
        target = max(3, len(appearance_days))
        if len(appearance_days) < target:
            for idx in range(min(horizon_days, target)):
                if top_topic not in day_preferences[idx]:
                    day_preferences[idx] = [top_topic] + [topic for topic in day_preferences[idx] if topic != top_topic]
                    day_preferences[idx] = day_preferences[idx][:max_topics_per_day]

    schedule_rows: list[dict[str, Any]] = []
    for day_idx in range(horizon_days):
        preferred = [topic for topic in day_preferences[day_idx] if remaining.get(topic, 0) > 0]
        day_minutes: dict[str, int] = {}
        budget_left = daily_budget_min
        guard = 0

        while budget_left > 0 and any(value > 0 for value in remaining.values()) and guard < 500:
            candidates = [topic for topic in preferred if remaining.get(topic, 0) > 0]
            if not candidates:
                spill = [topic for topic in topic_order if remaining.get(topic, 0) > 0 and topic not in day_minutes]
                if spill and len(day_minutes) < max_topics_per_day:
                    preferred.append(spill[0])
                    candidates = [spill[0]]
                else:
                    candidates = [topic for topic in day_minutes if remaining.get(topic, 0) > 0]
                    if not candidates:
                        break

            topic = max(candidates, key=lambda item: remaining.get(item, 0))
            if topic not in day_minutes and len(day_minutes) >= max_topics_per_day:
                break

            add = min(step_chunk, remaining.get(topic, 0), budget_left)
            if add <= 0:
                break
            day_minutes[topic] = day_minutes.get(topic, 0) + add
            remaining[topic] -= add
            budget_left -= add
            guard += 1

        schedule_rows.append(
            {
                "day": day_idx + 1,
                "topics": [
                    {"topic": topic, "minutes": int(minutes)}
                    for topic, minutes in sorted(day_minutes.items(), key=lambda item: item[1], reverse=True)
                    if int(minutes) > 0
                ],
                "total_minutes": int(sum(day_minutes.values())),
            }
        )

    if topic_order and schedule_rows:
        def _ensure_topic_on_day(target_day: int, topic: str) -> None:
            day_idx = max(0, min(len(schedule_rows) - 1, target_day - 1))
            day_topics = schedule_rows[day_idx]["topics"]
            if any(str(item.get("topic")) == topic for item in day_topics):
                return
            donor_idx = next(
                (
                    idx
                    for idx, row in enumerate(schedule_rows)
                    if idx != day_idx and any(str(item.get("topic")) == topic and int(item.get("minutes", 0)) >= 10 for item in row["topics"])
                ),
                None,
            )
            if donor_idx is None:
                return
            donor_row = schedule_rows[donor_idx]
            donor_topic_row = next(item for item in donor_row["topics"] if str(item.get("topic")) == topic)
            donor_topic_row["minutes"] = int(donor_topic_row.get("minutes", 0)) - 10
            if donor_topic_row["minutes"] <= 0:
                donor_row["topics"] = [item for item in donor_row["topics"] if str(item.get("topic")) != topic]
            donor_row["total_minutes"] = int(sum(int(item.get("minutes", 0)) for item in donor_row["topics"]))

            if len(day_topics) >= max_topics_per_day:
                smallest = min(day_topics, key=lambda item: int(item.get("minutes", 0)))
                smallest_topic = str(smallest.get("topic"))
                moved = min(10, int(smallest.get("minutes", 0)))
                smallest["minutes"] = int(smallest.get("minutes", 0)) - moved
                if smallest["minutes"] <= 0:
                    schedule_rows[day_idx]["topics"] = [
                        item for item in schedule_rows[day_idx]["topics"] if str(item.get("topic")) != smallest_topic
                    ]
                donor_row["topics"].append({"topic": smallest_topic, "minutes": moved})
                donor_row["total_minutes"] = int(sum(int(item.get("minutes", 0)) for item in donor_row["topics"]))

            schedule_rows[day_idx]["topics"].append({"topic": topic, "minutes": 10})
            schedule_rows[day_idx]["topics"] = sorted(
                schedule_rows[day_idx]["topics"], key=lambda item: int(item.get("minutes", 0)), reverse=True
            )
            schedule_rows[day_idx]["total_minutes"] = int(
                sum(int(item.get("minutes", 0)) for item in schedule_rows[day_idx]["topics"])
            )

        _ensure_topic_on_day(1, topic_order[0])
        if len(topic_order) > 1:
            _ensure_topic_on_day(2, topic_order[1])
        if horizon_days >= 1:
            for topic in topic_order[: min(3, len(topic_order))]:
                _ensure_topic_on_day(horizon_days, topic)

        for idx in range(1, len(schedule_rows)):
            prev_set = [str(item.get("topic")) for item in schedule_rows[idx - 1]["topics"]]
            curr_set = [str(item.get("topic")) for item in schedule_rows[idx]["topics"]]
            if prev_set == curr_set and len(topic_order) > len(curr_set):
                alt = next((topic for topic in topic_order if topic not in curr_set), None)
                if alt:
                    _ensure_topic_on_day(idx + 1, alt)

    if horizon_days >= 7 and topic_order:
        top_topic = topic_order[0]
        top_appearances = sum(
            1 for row in schedule_rows if any(str(item.get("topic")) == top_topic for item in row.get("topics") or [])
        )
        if top_appearances < 3:
            for day_target in [3, 5, 7]:
                if day_target <= horizon_days:
                    day_row = schedule_rows[day_target - 1]
                    if not any(str(item.get("topic")) == top_topic for item in day_row.get("topics") or []):
                        donor = next(
                            (
                                row
                                for row in schedule_rows
                                if any(str(item.get("topic")) == top_topic and int(item.get("minutes", 0)) >= 20 for item in row.get("topics") or [])
                            ),
                            None,
                        )
                        if donor:
                            donor_item = next(item for item in donor["topics"] if str(item.get("topic")) == top_topic)
                            donor_item["minutes"] -= 10
                            if donor_item["minutes"] <= 0:
                                donor["topics"] = [item for item in donor["topics"] if str(item.get("topic")) != top_topic]
                            day_row["topics"].append({"topic": top_topic, "minutes": 10})

    for row in schedule_rows:
        row["topics"] = sorted(row.get("topics") or [], key=lambda item: int(item.get("minutes", 0)), reverse=True)
        row["total_minutes"] = int(sum(int(item.get("minutes", 0)) for item in row.get("topics") or []))

    return schedule_rows


def _build_topic_focus_drills(error_state: list[dict], topics: list[str]) -> dict[str, str]:
    dominant_error_by_topic: dict[str, str] = {}
    for item in error_state or []:
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue
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
        dominant_error_by_topic[topic] = dominant

    drills: dict[str, str] = {}
    for topic in topics:
        dominant = dominant_error_by_topic.get(topic)
        if dominant == "time_pressure":
            drills[topic] = "Run a timed question sprint, then review where speed hurt accuracy and refine your approach."
        elif dominant == "careless":
            drills[topic] = "Do an accuracy-first pass: mark keywords, eliminate distractors, and verify your final choice."
        else:
            drills[topic] = "Do a short concept recap, then solve a few targeted questions and explain each answer."
    return drills


def _generate_topic_study_tasks(topic_explanations: list[dict]) -> dict[str, list[str]]:
    topics = [str(item.get("topic") or "").strip() for item in topic_explanations if str(item.get("topic") or "").strip()]
    fallback_bank = _build_behavior_corrective_task_bank(topic_explanations=topic_explanations)
    if not topics:
        return {}

    try:
        client = _get_openai_client()
        prompt = (
            "You are a behavior-corrective task writer for study planning. "
            "Generate 2-3 behavior-corrective tasks per topic based on dominant_error. "
            "Return JSON object only where keys are exact topic names and values are arrays of task strings. "
            "Each task must target the failure mechanism, be measurable, include a review/reflection step, and avoid template repetition. "
            "If dominant_error is conceptual, include recap + retrieval + explanation steps. "
            "If dominant_error is careless, include slow-pass and verification steps. "
            "If dominant_error is time_pressure, include timed drill and post-timing analysis. "
            "Avoid generic phrasing like 'review more' or 'practice more'."
        )
        payload = {
            "topic_explanations": topic_explanations,
        }
        response = client.chat.completions.create(
            model=_get_openai_model(),
            max_completion_tokens=450,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        parsed = json.loads(content) if content else {}
        tasks: dict[str, list[str]] = {}
        for topic in topics:
            value = parsed.get(topic)
            if isinstance(value, list):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
            else:
                one = str(value or "").strip()
                cleaned = [one] if one else []

            if not cleaned:
                cleaned = fallback_bank.get(
                    topic,
                    [f"For {topic}, complete 10 targeted questions, then review mistakes and rewrite corrected reasoning for 3 misses."],
                )
            tasks[topic] = cleaned[:3]
        return tasks
    except Exception:
        return {
            topic: (
                fallback_bank.get(topic)
                or [f"For {topic}, complete 10 targeted questions, then review mistakes and rewrite corrected reasoning for 3 misses."]
            )
            for topic in topics
        }


def _generate_plan_strategy_with_openai(
    *,
    topic_explanations: list[dict],
    priority_topics: list[str],
    allocation: list[dict],
    daily_schedule: list[dict],
    relevant_attempt_examples: list[dict],
) -> dict[str, Any]:
    def _fallback_topic_narratives() -> dict[str, str]:
        narratives: dict[str, str] = {}
        lead_bank = [
            "This topic is prioritized because",
            "This area is receiving earlier blocks since",
            "Practice emphasis is higher here because",
            "This topic needs focused correction because",
        ]
        for index, item in enumerate(topic_explanations or []):
            topic = str(item.get("topic") or "").strip()
            if not topic:
                continue
            lead = lead_bank[index % len(lead_bank)]
            reason = str(item.get("behavioral_reason") or "Needs reinforcement in recent attempts.").strip()
            evidence = list(item.get("micro_evidence") or [])
            chosen = evidence[0] if evidence else {}
            snippet = str(chosen.get("question_snippet") or "recent question").strip()
            outcome = str(chosen.get("outcome") or "incorrect").strip()
            mode = str(chosen.get("mode") or "timed").strip()
            confidence_bucket = str(chosen.get("confidence_bucket") or "med").strip()
            speed_bucket = str(chosen.get("speed_bucket") or "normal").strip()
            narratives[topic] = (
                f"{lead} {reason} Example evidence: \"{snippet}\" ({outcome}, {mode}, confidence={confidence_bucket}, speed={speed_bucket})."
            )
        return narratives

    topics = [str(item.get("topic") or "").strip() for item in topic_explanations if str(item.get("topic") or "").strip()]
    fallback_task_map = _generate_topic_study_tasks(topic_explanations=topic_explanations)
    fallback = {
        "priority_headline": "Priority topics get earlier and more frequent practice blocks.",
        "topic_task_bank": fallback_task_map,
        "topic_narratives": _fallback_topic_narratives(),
        "why_these_topics": (
            f"Priority emphasis is placed on {', '.join(priority_topics)} while still maintaining coverage across all selected topics."
            if priority_topics
            else "Topic coverage is balanced to reinforce weaker areas while keeping overall revision breadth."
        ),
        "how_to_execute": "Complete each block with intent, then do a brief error review before moving to the next topic.",
    }

    if not topics:
        return fallback

    try:
        client = _get_openai_client()
        prompt = (
            "You are explaining a precomputed study plan. "
            "Return JSON only with keys: priority_headline(string), topic_task_bank(object), topic_narratives(object), "
            "why_these_topics(string), how_to_execute(string). "
            "For each topic: explain why it was prioritized using mastery_level, trend_direction, retention_status, and dominant_error. "
            "Use 2-3 micro evidence items when available; include question_snippet, outcome, mode, confidence_bucket, speed_bucket. "
            "Propose corrective tasks that directly fix that behavior and are behavior-specific, not generic. "
            "Task requirements: include concrete action, measurable scope (e.g., 10 questions/2 cycles/20 minutes), and a review step. "
            "If dominant_error is conceptual: recap + retrieval + explanation structure. "
            "If dominant_error is careless: deliberate slow-pass + verification structure. "
            "If dominant_error is time_pressure: timed drill + post-timing analysis structure. "
            "If two topics have different dominant_error types, their task structures must differ. "
            "Avoid repeating identical task text across topics unless absolutely necessary. "
            "If trend_direction is slipping, emphasize correction urgency; if improving, emphasize reinforcement. "
            "If retention_status is high risk, recommend spaced repetition block. "
            "Do NOT modify minute allocations, daily schedule, or topics. "
            "Allow qualitative language such as recent dip, retention risk rising, confidence mismatch, speed-driven errors. "
            "Avoid explicit percentages and exact historical confidence/time numbers."
        )
        payload = {
            "topic_explanations": topic_explanations,
            "priority_topics": priority_topics,
            "allocation": allocation,
            "daily_schedule": daily_schedule,
            "relevant_attempt_examples": relevant_attempt_examples,
        }
        response = client.chat.completions.create(
            model=_get_openai_model(),
            max_completion_tokens=900,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        parsed = json.loads(content) if content else {}

        topic_task_bank_raw = parsed.get("topic_task_bank") or {}
        topic_task_bank: dict[str, list[str]] = {}
        for topic in topics:
            raw_value = topic_task_bank_raw.get(topic)
            if isinstance(raw_value, list):
                cleaned = [str(item).strip() for item in raw_value if str(item).strip()]
            else:
                single = str(raw_value or "").strip()
                cleaned = [single] if single else []
            if not cleaned:
                fallback_items = fallback_task_map.get(topic) or [
                    f"For {topic}, complete 10 targeted questions, then review mistakes and rewrite corrected reasoning for 3 misses."
                ]
                cleaned = [str(item).strip() for item in fallback_items if str(item).strip()]
            topic_task_bank[topic] = cleaned[:4]

        return {
            "priority_headline": str(parsed.get("priority_headline") or fallback["priority_headline"]).strip(),
            "topic_task_bank": topic_task_bank,
            "topic_narratives": {
                str(topic): str((parsed.get("topic_narratives") or {}).get(topic) or fallback.get("topic_narratives", {}).get(topic) or "").strip()
                for topic in topics
            },
            "why_these_topics": str(parsed.get("why_these_topics") or fallback["why_these_topics"]).strip(),
            "how_to_execute": str(parsed.get("how_to_execute") or fallback["how_to_execute"]).strip(),
        }
    except Exception:
        return fallback


def _generate_plan_explanation(
    *,
    plan: dict | None,
    constraints: dict | None,
    error_state: list[dict],
) -> dict[str, str]:
    plan = plan or {}
    constraints = constraints or {}
    checklist = list(plan.get("checklist") or [])
    topics = [str(item.get("topic") or "").strip() for item in checklist if str(item.get("topic") or "").strip()]
    priority_topics = [str(item).strip() for item in (plan.get("priority_topics") or []) if str(item).strip()]

    fallback_why = (
        f"Priority emphasis is placed on {', '.join(priority_topics)} because they currently need the most reinforcement. "
        "The remaining topics are still scheduled to keep full coverage and avoid gaps before the exam."
        if priority_topics
        else "Topics are allocated based on current learning need and retention risk while preserving balanced exam coverage."
    )
    fallback_note = "Keep each day practical: do the planned tasks, review mistakes briefly, and move to the next block without overextending."

    if not topics:
        return {"why_these_topics": fallback_why, "execution_note": fallback_note}

    try:
        client = _get_openai_client()
        prompt = (
            "You are a planner explanation writer for an adaptive learning coach. "
            "Given selected topics, priority topics, and plan constraints, write a concise explanation section. "
            "Return JSON only with keys: why_these_topics (required), execution_note (optional). "
            "Rule of thumb: keep it flexible and human, but grounded in plan intent. "
            "If priority topics exist, explicitly mention that they are emphasized while coverage still includes all scheduled topics when relevant. "
            "Do not include assumptions, numeric analytics, percentages, or phrases like 'the analysis indicates'. "
            "Keep why_these_topics to 2-4 sentences. Keep execution_note to 1 sentence."
        )
        payload = {
            "topics": topics,
            "priority_topics": priority_topics,
            "cover_all_topics": bool(constraints.get("cover_all_topics")),
            "focus_weakest_n": constraints.get("focus_weakest_n"),
            "time_horizon_days": plan.get("time_horizon_days"),
            "error_state": error_state,
        }
        response = client.chat.completions.create(
            model=_get_openai_model(),
            max_completion_tokens=420,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        parsed = json.loads(content) if content else {}

        why_text = str(parsed.get("why_these_topics") or "").strip() or fallback_why
        note_text = str(parsed.get("execution_note") or "").strip() or fallback_note
        return {
            "why_these_topics": why_text,
            "execution_note": note_text,
        }
    except Exception:
        return {"why_these_topics": fallback_why, "execution_note": fallback_note}


def _build_daily_schedule(allocation: list[dict], constraints: dict | None = None) -> list[dict]:
    horizon_days = int((constraints or {}).get("time_horizon_days") or 0)
    if horizon_days <= 1 or not allocation:
        return []

    total_minutes = sum(int(item.get("minutes", 0) or 0) for item in allocation)
    if total_minutes <= 0:
        return []

    daily_budget = int((constraints or {}).get("daily_budget_min") or 0)
    if daily_budget <= 0:
        daily_budget = max(1, int(round(total_minutes / horizon_days)))

    strategy = dict((constraints or {}).get("plan_strategy") or {})
    topic_task_bank = dict(strategy.get("topic_task_bank") or {})
    deterministic_task_bank = _build_behavior_corrective_task_bank(
        topic_explanations=list((constraints or {}).get("topic_explanation_inputs") or [])
    )

    def _is_generic_task(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        generic_markers = [
            "practice targeted questions and review mistakes",
            "practice more",
            "review more",
        ]
        return any(marker in normalized for marker in generic_markers)

    for topic, fallback_tasks in deterministic_task_bank.items():
        current = topic_task_bank.get(topic)
        if isinstance(current, list):
            cleaned_current = [str(item).strip() for item in current if str(item).strip()]
        else:
            cleaned_current = []

        if not cleaned_current or all(_is_generic_task(item) for item in cleaned_current):
            topic_task_bank[topic] = fallback_tasks
    used_task_texts: set[str] = set()

    def _task_for_topic(topic: str, day_index: int) -> str:
        bank = [str(item).strip() for item in (topic_task_bank.get(topic) or []) if str(item).strip()]
        if not bank:
            return f"For {topic}, complete 8 focused questions, then review mistakes and capture 2 correction rules."

        seed = f"{topic}|{day_index}|{horizon_days}"
        offset = int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:8], 16) % max(1, len(bank))
        ordered = bank[offset:] + bank[:offset]

        if horizon_days > 1:
            for candidate in ordered:
                normalized = candidate.strip().lower()
                if normalized not in used_task_texts:
                    used_task_texts.add(normalized)
                    return candidate

        chosen = ordered[0]
        used_task_texts.add(chosen.strip().lower())
        return chosen

    base_schedule = _build_daily_distribution(
        allocation=allocation,
        horizon_days=horizon_days,
        daily_budget_min=daily_budget,
    )

    schedule: list[dict] = []
    for day in base_schedule:
        entries = []
        for item in day.get("topics") or []:
            topic = str(item.get("topic") or "").strip()
            minutes = int(item.get("minutes", 0) or 0)
            if not topic or minutes <= 0:
                continue
            day_index = int(day.get("day") or 0)
            entries.append(
                {
                    "topic": topic,
                    "minutes": minutes,
                    "study_task": _task_for_topic(topic, day_index),
                }
            )

        schedule.append(
            {
                "day": int(day.get("day") or 0),
                "topics": entries,
                "total_minutes": int(day.get("total_minutes") or 0),
            }
        )

    return schedule


def _build_plan_artifact_from_allocation(allocation: list[dict], constraints: dict | None = None) -> dict:
    horizon_days = int((constraints or {}).get("time_horizon_days") or 0)
    daily_budget_min = int((constraints or {}).get("daily_budget_min") or 0)
    total_minutes = sum(int(item.get("minutes", 0) or 0) for item in allocation)

    checklist = []
    for item in allocation:
        topic = item["topic"]
        minutes = int(item["minutes"])
        if horizon_days > 1:
            per_day = round(minutes / horizon_days, 1)
            step = f"Practice {topic} for {minutes} minutes total (~{_format_minutes(per_day)} min/day)"
        else:
            step = f"Practice {topic} for {minutes} minutes"

        row = {
            "step": step,
            "topic": topic,
            "minutes": minutes,
        }
        if horizon_days > 1:
            row["minutes_total"] = minutes
            row["minutes_per_day"] = int(per_day) if float(per_day).is_integer() else per_day
        checklist.append(row)

    artifact = {
        "title": "Focused Session Plan",
        "checklist": checklist,
        "total_minutes": total_minutes,
        "allocation": allocation,
        "priority_ranked_topics": list((constraints or {}).get("priority_ranked_topics") or []),
    }

    invalid_focus_topics = list((constraints or {}).get("invalid_focus_topics") or [])
    if invalid_focus_topics:
        artifact["ignored_unmatched_topics"] = invalid_focus_topics

    if horizon_days > 1:
        artifact["time_horizon_days"] = horizon_days
        artifact["daily_budget_min"] = daily_budget_min
        avg_per_day = round(total_minutes / horizon_days, 1)
        artifact["total_minutes_per_day"] = int(avg_per_day) if float(avg_per_day).is_integer() else avg_per_day
        artifact["daily_schedule"] = _build_daily_schedule(allocation, constraints)

    priority_topics = list((constraints or {}).get("priority_topics") or [])
    if priority_topics:
        artifact["priority_topics"] = priority_topics

    return artifact


def _render_plan_response_from_artifact(plan: dict | None) -> str:
    plan = plan or {}
    checklist = list(plan.get("checklist") or [])
    daily_schedule = list(plan.get("daily_schedule") or [])
    priority_topics = [str(topic) for topic in (plan.get("priority_topics") or []) if str(topic).strip()]
    plan_explanation = dict(plan.get("plan_explanation") or {})
    topic_narratives = dict(plan_explanation.get("topic_narratives") or {})

    def _humanize_narrative_text(text: str) -> str:
        narrative = str(text or "").strip()
        if not narrative:
            return ""

        pattern = re.compile(r'Example evidence:\s*"([^"]+)"\s*\(([^)]*)\)\.?', re.IGNORECASE)
        match = pattern.search(narrative)
        if not match:
            return narrative

        snippet = match.group(1).strip()
        raw_features = [item.strip().lower() for item in match.group(2).split(",") if item.strip()]

        outcome = ""
        mode = ""
        confidence = ""
        speed = ""
        for feature in raw_features:
            if feature in {"correct", "incorrect"}:
                outcome = feature
            elif feature in {"timed", "untimed"}:
                mode = feature
            elif feature.startswith("confidence="):
                confidence = feature.split("=", 1)[1].strip()
            elif feature.startswith("speed="):
                speed = feature.split("=", 1)[1].strip()

        interpretation_parts: list[str] = []
        if outcome == "incorrect" and confidence == "low":
            interpretation_parts.append("This suggests uncertainty in concept selection, not just a minor slip")
        elif outcome == "incorrect" and confidence == "high":
            interpretation_parts.append("This points to overconfidence where the final choice is not fully verified")
        elif outcome == "correct" and confidence == "low":
            interpretation_parts.append("This shows the answer is often recoverable but confidence is still fragile")
        elif outcome == "correct" and confidence == "high":
            interpretation_parts.append("This indicates the concept is becoming stable under similar question styles")

        if mode == "timed" and speed == "fast":
            interpretation_parts.append("Pacing likely pushed an early commit")
        elif mode == "timed" and speed == "slow":
            interpretation_parts.append("Time pressure may be causing overthinking before committing")
        elif mode == "timed":
            interpretation_parts.append("The issue appears during timed execution rather than untimed recall")

        if not interpretation_parts:
            interpretation_parts.append("This pattern highlights where your decision process is currently breaking down")

        humanized = f'Example evidence: "{snippet}". ' + "; ".join(interpretation_parts) + "."
        return narrative[: match.start()] + humanized + narrative[match.end() :]

    lines: list[str] = ["**PLAN SUMMARY**"]
    for step in checklist:
        topic = str(step.get("topic") or "").strip()
        if not topic:
            continue
        total = int(step.get("minutes_total") or step.get("minutes") or 0)
        per_day = step.get("minutes_per_day")
        if isinstance(per_day, (int, float)):
            lines.append(f"- **{topic}**: {total} minutes total (~{_format_minutes(float(per_day))} min/day)")
        else:
            lines.append(f"- **{topic}**: {total} minutes")

    if priority_topics:
        lines.append("")
        lines.append("**PRIORITY FOCUS**")
        lines.append(f"- {', '.join(priority_topics)}")
        headline = str(plan_explanation.get("priority_headline") or "").strip()
        if headline:
            lines.append(f"- {headline}")

    lines.append("")
    lines.append("**SCHEDULE**")
    if daily_schedule:
        for day in daily_schedule:
            day_num = int(day.get("day") or 0)
            lines.append(f"**Day {day_num}**")
            for item in day.get("topics") or []:
                topic = str(item.get("topic") or "").strip()
                minutes = int(item.get("minutes") or 0)
                task = str(item.get("study_task") or "Practice targeted questions and review mistakes.").strip()
                if not topic or minutes <= 0:
                    continue
                lines.append(f"- {topic}: {minutes} minutes")
                lines.append(f"  - Study Task: {task}")
            lines.append("")
    else:
        lines.append("- Follow the checklist topic allocations for each study day.")
        lines.append("")

    if topic_narratives:
        lines.append("")
        lines.append("**TOPIC INSIGHTS**")
        for step in checklist:
            topic = str(step.get("topic") or "").strip()
            if not topic:
                continue
            narrative = _humanize_narrative_text(str(topic_narratives.get(topic) or "").strip())
            if not narrative:
                continue
            lines.append(f"- **{topic}**: {narrative}")

    execution_note = str(plan_explanation.get("execution_note") or "").strip()
    if execution_note:
        lines.append("")
        lines.append("**HOW TO EXECUTE**")
        lines.append(f"- {execution_note}")

    return "\n".join(lines).strip()


def _validate_plan_explanation_quality(plan: dict | None, constraints: dict | None) -> dict[str, Any]:
    plan = plan or {}
    constraints = constraints or {}

    schedule = list(plan.get("daily_schedule") or [])
    horizon = int(plan.get("time_horizon_days") or constraints.get("time_horizon_days") or 1)

    task_texts: list[str] = []
    generic_markers = [
        "practice targeted questions and review mistakes",
        "practice more",
        "review more",
    ]
    has_generic = False
    for day in schedule:
        for entry in day.get("topics") or []:
            task = str(entry.get("study_task") or "").strip()
            if not task:
                continue
            normalized = task.lower()
            task_texts.append(normalized)
            if any(marker in normalized for marker in generic_markers):
                has_generic = True

    unique_task_count = len(set(task_texts))
    repeated_task_count = len(task_texts) - unique_task_count
    no_repeats_across_days = bool(horizon <= 1 or repeated_task_count == 0)

    minimum_expected = min(len(task_texts), 3) if task_texts else 0
    has_task_variety = unique_task_count >= minimum_expected

    ranked = list(plan.get("priority_ranked_topics") or constraints.get("priority_ranked_topics") or [])
    top2 = [str(item.get("topic") or "").strip() for item in ranked[:2] if str(item.get("topic") or "").strip()]
    narratives = dict((plan.get("plan_explanation") or {}).get("topic_narratives") or {})
    explanation_inputs = {
        str(item.get("topic") or "").strip(): list(item.get("micro_evidence") or [])
        for item in (constraints.get("topic_explanation_inputs") or [])
        if str(item.get("topic") or "").strip()
    }
    evidence_topics_covered = 0
    for topic in top2:
        narrative = str(narratives.get(topic) or "").strip()
        has_quote = '"' in narrative
        has_micro = bool(explanation_inputs.get(topic))
        if has_quote and has_micro:
            evidence_topics_covered += 1

    top2_evidence_ok = evidence_topics_covered >= min(2, len(top2))

    return {
        "horizon_days": horizon,
        "task_count": len(task_texts),
        "unique_task_count": unique_task_count,
        "repeated_task_count": repeated_task_count,
        "has_task_variety": has_task_variety,
        "no_repeated_identical_tasks": no_repeats_across_days,
        "has_generic_task_phrase": has_generic,
        "top2_topics": top2,
        "top2_evidence_topics_covered": evidence_topics_covered,
        "top2_evidence_ok": top2_evidence_ok,
        "passed": bool(no_repeats_across_days and has_task_variety and (not has_generic) and top2_evidence_ok),
    }


def node_handle_plan(state: GraphState) -> GraphState:
    coach_state = CoachRunState.model_validate(state)
    constraints = dict(coach_state.constraints or {})

    if (not isinstance(constraints.get("time_budget_min"), int) or constraints.get("time_budget_min", 0) <= 0) and bool(
        constraints.get("generic_plan")
    ):
        constraints["time_budget_min"] = 45

    cover_all_topics = bool(constraints.get("cover_all_topics"))
    focus_topics = {str(topic) for topic in (constraints.get("focus_topics") or [])}
    if focus_topics:
        filtered_topic_state = [item for item in coach_state.topic_state if item.topic in focus_topics]
        candidate_topic_state = filtered_topic_state or coach_state.topic_state
    else:
        candidate_topic_state = coach_state.topic_state

    topic_limit = constraints.get("topic_limit")
    if not cover_all_topics and isinstance(topic_limit, int) and topic_limit > 0 and candidate_topic_state:
        ranked_candidates = sorted(
            candidate_topic_state,
            key=lambda item: max(0.0, (1.0 - item.mastery) + item.decay_risk),
            reverse=True,
        )
        candidate_topic_state = ranked_candidates[:topic_limit]

    priority_ranked_topics = _compute_topic_priority_scores(
        topic_state=[item.model_dump() for item in candidate_topic_state],
        error_state=[item.model_dump() for item in coach_state.error_state],
    )

    focus_weakest_n = constraints.get("focus_weakest_n")
    if isinstance(focus_weakest_n, int) and focus_weakest_n > 0 and priority_ranked_topics:
        priority_topics = [str(item.get("topic")) for item in priority_ranked_topics[:focus_weakest_n] if str(item.get("topic") or "").strip()]
        constraints["priority_topics"] = priority_topics
    elif not constraints.get("priority_topics"):
        constraints.pop("priority_topics", None)

    constraints["priority_ranked_topics"] = priority_ranked_topics

    selected_topics = [item.topic for item in candidate_topic_state]
    if selected_topics:
        state["attempt_evidence"] = _fetch_attempt_evidence(
            student_id=str(state.get("student_id", "")),
            window_days=int(state.get("window_days", 30)),
            focus_topics=selected_topics,
        )

    allocation = _allocate_minutes_by_priority(
        priority_topics=priority_ranked_topics,
        total_budget_min=int(constraints.get("time_budget_min") or 0),
    )
    state["allocation"] = allocation
    horizon_days = int(constraints.get("time_horizon_days") or 1)
    daily_budget_min = int(constraints.get("daily_budget_min") or 60)
    deterministic_daily_schedule = _build_daily_distribution(
        allocation=allocation,
        horizon_days=max(1, horizon_days),
        daily_budget_min=max(1, daily_budget_min),
    )
    constraints["deterministic_daily_schedule"] = deterministic_daily_schedule

    topic_explanation_inputs = _build_topic_explanation_inputs(
        topic_state=[item.model_dump() for item in candidate_topic_state],
        error_state=[item.model_dump() for item in coach_state.error_state],
        attempt_evidence=state.get("attempt_evidence") or {},
        priority_ranked_topics=priority_ranked_topics,
    )
    constraints["topic_explanation_inputs"] = topic_explanation_inputs

    constraints["plan_strategy"] = _generate_plan_strategy_with_openai(
        topic_explanations=topic_explanation_inputs,
        priority_topics=[str(topic) for topic in (constraints.get("priority_topics") or []) if str(topic).strip()],
        allocation=allocation,
        daily_schedule=deterministic_daily_schedule,
        relevant_attempt_examples=(state.get("attempt_evidence") or {}).get("relevant_attempts") or [],
    )
    constraints["topic_focus_drills"] = _build_topic_focus_drills(
        error_state=[item.model_dump() for item in coach_state.error_state],
        topics=[item.topic for item in candidate_topic_state],
    )
    state["plan_debug"] = {
        "priority_formula": "(1-mastery)*0.5 + max(0,-trend)*0.2 + decay_risk*0.2 + dominant_error_severity*0.1",
        "priority_scores": priority_ranked_topics,
        "allocation_signature": "|".join(f"{item.get('topic')}:{item.get('minutes')}" for item in allocation),
    }
    diagnosis = state.get("diagnosis") or {}
    if not allocation:
        note = "missing time budget"
    else:
        note = "approved"

    diagnosis["evaluation"] = note
    state["diagnosis"] = diagnosis
    state["plan"] = _build_plan_artifact_from_allocation(allocation, constraints)
    if state.get("plan"):
        state["plan"].update(
            {
                "priority_ranked_topics": priority_ranked_topics,
                "allocation": allocation,
                "time_horizon_days": max(1, horizon_days),
                "daily_budget_min": max(1, daily_budget_min),
            }
        )
        if not state["plan"].get("daily_schedule"):
            state["plan"]["daily_schedule"] = deterministic_daily_schedule
    if state.get("plan"):
        strategy = dict(constraints.get("plan_strategy") or {})
        if strategy:
            state["plan"]["plan_explanation"] = {
                "priority_headline": str(strategy.get("priority_headline") or "").strip(),
                "why_these_topics": str(strategy.get("why_these_topics") or "").strip(),
                "execution_note": str(strategy.get("how_to_execute") or "").strip(),
                "topic_narratives": dict(strategy.get("topic_narratives") or {}),
            }
        else:
            state["plan"]["plan_explanation"] = _generate_plan_explanation(
                plan=state.get("plan") or {},
                constraints=constraints,
                error_state=[item.model_dump() for item in coach_state.error_state],
            )
        response_text = _render_plan_response_from_artifact(state.get("plan") or {})
        response_meta = {
            "source": "deterministic_plan_renderer",
            "profile": "artifact_schedule_with_llm_strategy",
        }
        explanation_validation = _validate_plan_explanation_quality(state.get("plan") or {}, constraints)
        state["plan"]["response"] = response_text
        state["plan"]["response_source"] = response_meta.get("source")
        state["plan"]["response_debug"] = response_meta
        state["plan"]["explanation_validation"] = explanation_validation
        state["plan_debug"]["explanation_validation"] = explanation_validation
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
    _append_trace(
        state,
        "handle_plan",
        {
            "result": note,
            "executed": True,
            "session_id": result.get("session_id"),
            "topic_limit": constraints.get("topic_limit"),
            "selected_topics": selected_topics,
        },
    )
    return state


def node_execute_intents(state: GraphState) -> GraphState:
    if bool(state.get("plan_mode_required_notice")):
        notice = "Study Plan Mode is currently off. Please turn it on, then ask for a study plan again."
        state["artifact_type"] = "mode_notice"
        state["artifact"] = {
            "agent": "mode_guard",
            "response": notice,
            "reason": "plan_requested_while_plan_mode_off",
        }
        state["executed_intents"] = []
        _append_trace(
            state,
            "execute_intents",
            {"intents": [], "combined": False, "mode_notice": True},
        )
        return state

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

