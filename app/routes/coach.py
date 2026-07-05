from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app.security import require_token
from app.services.summary import build_latest_summary, build_training_projection

router = APIRouter(prefix="/api/coach", tags=["coach"])


class CoachQuestion(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000)


def _mix_line(summary: dict[str, Any]) -> str:
    mix = summary.get("recent_training_mix") or []
    if not mix:
        return "No recent activity mix yet."
    parts = [f"{item['label']}: {item['sessions']} session(s), {item['minutes']} min" for item in mix[:5]]
    return "; ".join(parts)


def fallback_coach(question: str, summary: dict[str, Any], projection: dict[str, Any]) -> str:
    runs = summary.get("recent_runs", 0)
    miles = summary.get("recent_run_miles", 0)
    total_sessions = summary.get("recent_activity_count", 0)
    total_minutes = summary.get("recent_activity_minutes", 0)
    strength_sessions = summary.get("recent_strength_sessions", 0)
    cardio_sessions = summary.get("recent_cardio_sessions", 0)
    two_mile = summary.get("current_two_mile_marker") or "unknown"
    flags = summary.get("recovery_flags", [])

    lines = [
        "OpenAI is not configured yet, so here is the built-in coach answer.",
        "",
        f"Current training window: {total_sessions} activity/activities, about {total_minutes} total minutes.",
        f"Training mix: {_mix_line(summary)}",
        f"Running marker, if relevant: {two_mile}. Recent running: {runs} run(s), {miles} mile(s).",
        "",
        "What I would do next:",
    ]

    if total_sessions == 0:
        lines.append("1. Upload Garmin activities or add a manual progress entry first, then reassess.")
        lines.append("2. Start with 2-3 easy sessions this week: walking, easy cardio, light lifting, or mobility.")
    elif cardio_sessions == 0 and strength_sessions > 0:
        lines.append("1. Keep lifting, but add 1-2 easy cardio sessions or walks to build conditioning.")
        lines.append("2. Do not add hard intervals yet; build easy volume first.")
    elif strength_sessions == 0 and cardio_sessions > 0:
        lines.append("1. Keep the cardio consistency and add 1-2 short full-body strength sessions.")
        lines.append("2. Keep most cardio easy unless you are deliberately doing one quality workout.")
    elif total_sessions <= 3:
        lines.append("1. Build consistency before complexity: aim for 3-4 total sessions next week.")
        lines.append("2. Use a simple split: one cardio day, one strength day, one easy recovery/mobility day.")
    elif total_sessions <= 6:
        lines.append("1. This is a solid training rhythm. Keep one harder conditioning day and one harder strength day max.")
        lines.append("2. Put easy days between your hardest sessions so you can actually adapt.")
    else:
        lines.append("1. Your frequency is already high. Protect recovery and avoid stacking hard days.")
        lines.append("2. Make the next session easy unless sleep, soreness, and energy all look good.")

    lines.extend([
        "3. For general improvement, judge progress by consistency, total weekly minutes, how easy pace feels, strength notes, and recovery — not one perfect metric.",
        "4. For running or ACFT goals, keep logging 2-mile benchmarks. For lifting/body composition goals, use the manual progress notes after workouts.",
        "",
        f"Risk flags: {', '.join(flags) if flags else 'none from available data'}.",
        f"Projection: {projection.get('status')}: {projection.get('recommendation')}",
        "",
        f"Question answered: {question}",
    ])
    return "\n".join(lines)


@router.post("/ask")
def ask_coach(
    payload: CoachQuestion,
    _: None = Depends(require_token),
    x_openai_api_key: str | None = Header(default=None),
    x_openai_model: str | None = Header(default=None),
):
    summary = build_latest_summary()
    projection = build_training_projection()
    # A key typed into the web UI is sent only for this request and is not
    # stored by the server. The .env key remains available for server-side use.
    api_key = (x_openai_api_key or os.getenv("OPENAI_API_KEY", "")).strip()

    if not api_key:
        return {
            "source": "built_in_fallback",
            "answer": fallback_coach(payload.question, summary, projection),
            "summary_used": summary,
        }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = (x_openai_model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")).strip() or "gpt-4.1-mini"
        prompt = f"""
You are Garmin Progress Coach, a practical training assistant for general fitness improvement.

The user may care about running, weightlifting, cardio, recovery, consistency, body composition, ACFT preparation, or just getting fitter.
Do not assume every user is training for the ACFT. Treat ACFT as an optional context only when the user asks about it or has logged ACFT-style fields.
Do not diagnose medical problems. Do not claim official ACFT scoring unless official scoring data is provided.
Prioritize trends over single-day readings. Give specific, realistic training guidance.
Use the training mix, strength sessions, cardio sessions, running sessions, recovery flags, and manual notes when available.

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
