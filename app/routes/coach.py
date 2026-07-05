from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.security import require_token
from app.services.summary import build_latest_summary, build_training_projection

router = APIRouter(prefix="/api/coach", tags=["coach"])


class CoachQuestion(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000)


def fallback_coach(question: str, summary: dict[str, Any], projection: dict[str, Any]) -> str:
    runs = summary.get("recent_runs", 0)
    miles = summary.get("recent_run_miles", 0)
    two_mile = summary.get("current_two_mile_marker") or "unknown"
    goal = summary.get("goal_two_mile") or "not set"
    flags = summary.get("recovery_flags", [])

    lines = [
        "OpenAI is not configured yet, so here is the built-in coach answer.",
        "",
        f"Current 2-mile benchmark: {two_mile}. Goal: {goal}.",
        f"Recent running: {runs} runs and {miles} miles in the current data window.",
        "",
        "What I would do next:",
    ]

    if runs == 0:
        lines.append("1. Upload Garmin activities or add a manual benchmark first, then reassess.")
        lines.append("2. Start with 2-3 easy sessions this week instead of jumping into hard intervals.")
    elif runs <= 2:
        lines.append("1. Add one more easy run or walk/run session before increasing intensity.")
        lines.append("2. Keep at most one quality day, such as short controlled intervals or a light tempo.")
    elif runs <= 4:
        lines.append("1. Keep a balanced week: one easy run, one quality run, and one longer easy effort.")
        lines.append("2. Add strength or mobility around the runs without crushing your legs before speed work.")
    else:
        lines.append("1. Your run frequency is already high enough. Protect recovery this week.")
        lines.append("2. Make the next session easy unless you feel unusually fresh.")

    lines.extend([
        "3. If your goal is general fitness, judge progress by consistency, easy pace, recovery, and how you feel — not just one test time.",
        "4. If your goal is ACFT, keep logging push-ups, plank, deadlift, SDC/agility, and 2-mile benchmarks.",
        "",
        f"Risk flags: {', '.join(flags) if flags else 'none from available data'}.",
        f"Projection: {projection.get('status')}: {projection.get('recommendation')}",
        "",
        f"Question answered: {question}",
    ])
    return "\n".join(lines)


@router.post("/ask")
def ask_coach(payload: CoachQuestion, _: None = Depends(require_token)):
    summary = build_latest_summary()
    projection = build_training_projection()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        return {
            "source": "built_in_fallback",
            "answer": fallback_coach(payload.question, summary, projection),
            "summary_used": summary,
        }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        prompt = f"""
You are Garmin AI Coach, a practical training assistant for general fitness improvement.

The user may care about running, recovery, consistency, strength, body composition, ACFT preparation, or just getting fitter.
Do not assume every user is training for the ACFT. Treat ACFT as an optional context only when the user asks about it or has logged ACFT-style fields.
Do not diagnose medical problems. Do not claim official ACFT scoring unless official scoring data is provided.
Prioritize trends over single-day readings. Give specific, realistic training guidance.

User question:
{payload.question}

Latest training summary JSON:
{json.dumps(summary, indent=2)}

Training projection JSON:
{json.dumps(projection, indent=2)}

Answer in a helpful, direct tone. Include:
- what the data suggests
- what to do next
- what to avoid
""".strip()

        response = client.responses.create(model=model, input=prompt)
        answer = getattr(response, "output_text", None) or str(response)
        return {"source": "openai", "model": model, "answer": answer, "summary_used": summary}
    except Exception:  # noqa: BLE001 - fail softly for easy setup
        return {
            "source": "built_in_fallback_after_openai_error",
            "error": "OpenAI coaching is unavailable. Check your API key/model settings if you want richer answers.",
            "answer": fallback_coach(payload.question, summary, projection),
            "summary_used": summary,
        }
