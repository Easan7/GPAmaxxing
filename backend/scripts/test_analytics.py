"""Smoke test for Supabase analytics pipeline.

Usage:
    python scripts/test_analytics.py --student-id <uuid> [--since-days 30]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from app.models.analytics.decay import compute_decay_by_topic
from app.models.analytics.error_inference import (
    annotate_attempts_with_error_type,
    error_distribution_by_topic,
    infer_topic_error_probs,
)
from app.models.analytics.mastery_elo import compute_topic_mastery_elo
from app.models.analytics.patterns import detect_patterns
from app.models.analytics.repo import fetch_attempts_join_questions
from app.models.analytics.student_state import build_student_state
from app.models.analytics.trend import compute_trends


def _sanitize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {key: _sanitize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    return obj


def _first_n(items: list, n: int = 3) -> list:
    return items[: max(0, n)]


def _first_n_map(mapping: dict, n: int = 3) -> dict:
    keys = sorted(mapping.keys())[: max(0, n)]
    return {key: mapping[key] for key in keys}


def _print_preview(title: str, payload, limit: int = 3) -> None:
    print(f"\n{title}")
    if isinstance(payload, list):
        preview = _first_n(payload, limit)
    elif isinstance(payload, dict):
        preview = _first_n_map(payload, limit)
    else:
        preview = payload
    print(json.dumps(_sanitize(preview), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run analytics + Supabase smoke test.")
    parser.add_argument("--student-id", required=True, help="Student UUID in attempts table")
    parser.add_argument("--since-days", type=int, default=30, help="Lookback window in days")
    parser.add_argument("--limit", type=int, default=200, help="Attempt row fetch limit")
    args = parser.parse_args()

    print("[1/8] Fetching attempt rows from Supabase...")
    rows = fetch_attempts_join_questions(
        student_id=args.student_id,
        since_days=args.since_days,
        limit=args.limit,
    )
    print(f"  rows={len(rows)}")
    if not rows:
        print("No attempts returned for this student/window.")
        return
    _print_preview("  repo.py -> sample fetched rows", rows, limit=2)

    print("[2/8] Computing mastery (ELO)...")
    mastery = compute_topic_mastery_elo(rows)
    print(f"  topics_mastery={len(mastery)}")
    _print_preview("  mastery_elo.py -> sample mastery_by_topic", mastery, limit=3)

    print("[3/8] Computing decay...")
    decay = compute_decay_by_topic(mastery)
    print(f"  topics_decay={len(decay)}")
    _print_preview("  decay.py -> sample decay_by_topic", decay, limit=3)

    print("[4/8] Computing trends...")
    trends = compute_trends(rows)
    print(f"  topics_trend={len(trends)}")
    trend_preview = {
        topic: {
            "label": values.get("label"),
            "slope": values.get("slope"),
            "volatility": values.get("volatility"),
            "points_count": len(values.get("points", [])),
        }
        for topic, values in trends.items()
    }
    _print_preview("  trend.py -> sample trend signals", trend_preview, limit=3)

    print("[5/8] Annotating errors...")
    annotated = annotate_attempts_with_error_type(rows, mastery)
    print(f"  annotated_rows={len(annotated)}")
    _print_preview("  error_inference.py -> sample annotated rows", annotated, limit=2)

    print("[6/8] Aggregating error distribution...")
    error_dist = error_distribution_by_topic(annotated)
    error_probs = infer_topic_error_probs(rows, mastery)
    print(f"  topics_error_dist={len(error_dist)} topics_error_probs={len(error_probs)}")
    _print_preview("  error_inference.py -> sample error distribution", error_dist, limit=3)
    _print_preview("  error_inference.py -> sample error probabilities", error_probs, limit=3)

    print("[7/8] Detecting patterns...")
    patterns = detect_patterns(rows)
    print(f"  topics_patterns={len(patterns)}")
    _print_preview("  patterns.py -> sample pattern outputs", patterns, limit=2)

    print("[8/8] Building full student state...")
    full_state = build_student_state(student_id=args.student_id, since_days=args.since_days)
    print("  full_state_ok=true")
    _print_preview(
        "  student_state.py -> sample final topic payload",
        full_state.get("topics", {}),
        limit=2,
    )

    sample = {
        "student_id": args.student_id,
        "rows": len(rows),
        "topic_count": len(full_state.get("topics", {})),
        "weakest_topics": full_state.get("overall", {}).get("weakest_topics", []),
        "highest_decay_risk": full_state.get("overall", {}).get("highest_decay_risk", []),
        "regressing_topics": full_state.get("overall", {}).get("regressing_topics", []),
    }
    print("\nSummary:")
    print(json.dumps(_sanitize(sample), indent=2))


if __name__ == "__main__":
    main()
