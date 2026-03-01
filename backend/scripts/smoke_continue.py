"""Smoke test for coach clarification resume flow.

Run with server active on localhost:8000.
"""

from __future__ import annotations

import json
import urllib.request


BASE_URL = "http://127.0.0.1:8000"


def post_json(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    first = post_json(
        "/api/coach/query",
        {
            "student_id": "smoke-user-1",
            "message": "Please plan my study for today",
            "window_days": 30,
            "constraints": {},
        },
    )

    print("query status:", first.get("status"))
    run_id = first.get("run_id")
    if not run_id:
        raise RuntimeError("Missing run_id from /api/coach/query")

    second = post_json(
        "/api/coach/continue",
        {
            "run_id": run_id,
            "answer": {"time_budget_min": 120},
        },
    )

    print("continue status:", second.get("status"))
    print("run_id:", second.get("run_id"))


if __name__ == "__main__":
    main()
