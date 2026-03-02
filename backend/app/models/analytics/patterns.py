"""Pattern detection utilities over joined attempt rows."""

from __future__ import annotations

from collections import Counter


def detect_patterns(
    attempt_rows: list[dict],
    window_size: int = 50,
    min_count: int = 3,
) -> dict[str, dict]:
    """Detect repeated mistake patterns in recent wrong attempts.

    Uses the most recent `window_size` attempts overall, then aggregates only
    wrong attempts by topic for tags and question_type frequencies.
    """
    ordered = sorted(
        attempt_rows,
        key=lambda row: row.get("attempted_at"),
        reverse=True,
    )
    window = ordered[: max(0, window_size)]
    wrong_rows = [row for row in window if not bool(row.get("correct", False))]

    topics = sorted({str(row.get("topic") or "Unknown") for row in window})
    tag_counts_by_topic: dict[str, Counter] = {topic: Counter() for topic in topics}
    qtype_counts_by_topic: dict[str, Counter] = {topic: Counter() for topic in topics}

    for row in wrong_rows:
        topic = str(row.get("topic") or "Unknown")

        tags = row.get("tags") or []
        for tag in tags:
            tag_counts_by_topic[topic][str(tag)] += 1

        question_type = row.get("question_type")
        if question_type is not None:
            qtype_counts_by_topic[topic][str(question_type)] += 1

    result: dict[str, dict] = {}
    for topic in topics:
        tag_counter = tag_counts_by_topic.get(topic, Counter())
        qtype_counter = qtype_counts_by_topic.get(topic, Counter())

        top_tags = [
            {"tag": key, "wrong_count": int(count)}
            for key, count in tag_counter.most_common(5)
        ]
        top_question_types = [
            {"question_type": key, "wrong_count": int(count)}
            for key, count in qtype_counter.most_common(5)
        ]

        alerts: list[dict] = []
        for key, count in tag_counter.items():
            if count >= min_count:
                alerts.append({"kind": "tag", "key": key, "count": int(count)})
        for key, count in qtype_counter.items():
            if count >= min_count:
                alerts.append({"kind": "question_type", "key": key, "count": int(count)})

        result[topic] = {
            "top_tags": top_tags,
            "top_question_types": top_question_types,
            "alerts": alerts,
        }

    return result


def detect_topic_patterns(attempts: list[dict]) -> dict[str, dict]:
    """Backward-compatible wrapper returning compact tag-pattern signal."""
    detailed = detect_patterns(attempts)
    compact: dict[str, dict] = {}

    for topic, payload in detailed.items():
        matching_tag_alerts = [alert for alert in payload.get("alerts", []) if alert.get("kind") == "tag"]
        if not matching_tag_alerts:
            continue
        best = sorted(matching_tag_alerts, key=lambda item: int(item.get("count", 0)), reverse=True)[0]
        compact[topic] = {
            "pattern_tag": best.get("key"),
            "count": int(best.get("count", 0)),
        }

    return compact
