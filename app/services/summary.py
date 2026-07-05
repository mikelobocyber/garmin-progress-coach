from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from app.database import fetch_acft_entries, fetch_all_activities, get_settings
from app.services.formatting import seconds_to_hms, seconds_to_pace


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_run(activity: dict[str, Any]) -> bool:
    text = f"{activity.get('activity_type') or ''} {activity.get('title') or ''}".lower()
    return "run" in text or "treadmill" in text


def _safe_mean(values: list[int | float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return round(mean(clean), 2) if clean else None


def _activity_public(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": activity.get("id"),
        "activity_type": activity.get("activity_type"),
        "title": activity.get("title"),
        "start_time": activity.get("start_time"),
        "distance_miles": activity.get("distance_miles"),
        "duration": seconds_to_hms(activity.get("duration_seconds")),
        "duration_seconds": activity.get("duration_seconds"),
        "avg_hr": activity.get("avg_hr"),
        "max_hr": activity.get("max_hr"),
        "avg_pace": seconds_to_pace(activity.get("avg_pace_seconds_per_mile")),
        "avg_pace_seconds_per_mile": activity.get("avg_pace_seconds_per_mile"),
        "calories": activity.get("calories"),
    }


def build_latest_summary() -> dict[str, Any]:
    activities = fetch_all_activities()
    settings = get_settings()
    progress_entries = fetch_acft_entries(limit=10)

    dated = [(activity, _parse_dt(activity.get("start_time"))) for activity in activities]
    dated_with_dates = [(a, dt) for a, dt in dated if dt]
    # The 7-day window is anchored to the newest uploaded activity, not
    # "today", so an export from last month still shows a meaningful week.
    anchor = max((dt for _, dt in dated_with_dates), default=datetime.now())
    week_start = (anchor - timedelta(days=6)).date()
    recent = [a for a, dt in dated_with_dates if dt.date() >= week_start]
    recent_run_activities = [a for a in recent if _is_run(a)]
    all_runs = [a for a in activities if _is_run(a)]

    total_run_miles = round(sum(float(a.get("distance_miles") or 0) for a in recent_run_activities), 2)
    total_duration = sum(int(a.get("duration_seconds") or 0) for a in recent_run_activities)
    avg_pace_sec = int(total_duration / total_run_miles) if total_run_miles > 0 and total_duration > 0 else None

    best_two_mile_estimate_sec = None
    best_two_mile_source = None
    for run in all_runs:
        pace = run.get("avg_pace_seconds_per_mile")
        distance = run.get("distance_miles") or 0
        if pace and distance and distance >= 1.0:
            estimate = int(pace * 2)
            if best_two_mile_estimate_sec is None or estimate < best_two_mile_estimate_sec:
                best_two_mile_estimate_sec = estimate
                best_two_mile_source = run.get("title") or run.get("start_time")

    latest_progress = progress_entries[0] if progress_entries else None
    manual_two_mile = latest_progress.get("two_mile_seconds") if latest_progress else None
    display_two_mile = manual_two_mile or best_two_mile_estimate_sec

    recovery_flags: list[str] = []
    if len(recent_run_activities) >= 5:
        recovery_flags.append("High run frequency this week")
    if total_run_miles >= 15:
        recovery_flags.append("Higher weekly mileage than a newer runner block")
    avg_recent_hr = _safe_mean([a.get("avg_hr") for a in recent_run_activities])
    if avg_recent_hr and avg_recent_hr >= 165:
        recovery_flags.append("Average running heart rate looks high")
    if not recovery_flags and recent_run_activities:
        recovery_flags.append("No obvious recovery red flags from uploaded activity data")
    if not recent_run_activities:
        recovery_flags.append("No recent runs found in uploaded data")

    try:
        goal_two_mile_seconds = int(settings.get("goal_two_mile_seconds", "900"))
    except ValueError:
        goal_two_mile_seconds = 900

    gap_to_goal = None
    if display_two_mile and goal_two_mile_seconds:
        gap_to_goal = display_two_mile - goal_two_mile_seconds

    return {
        "week_start": week_start.isoformat(),
        "week_end": anchor.date().isoformat(),
        "activity_count_total": len(activities),
        "recent_activity_count": len(recent),
        "recent_runs": len(recent_run_activities),
        "recent_run_miles": total_run_miles,
        "recent_avg_run_pace": seconds_to_pace(avg_pace_sec),
        "recent_avg_run_pace_seconds_per_mile": avg_pace_sec,
        "recent_avg_hr": avg_recent_hr,
        "best_estimated_two_mile": seconds_to_hms(best_two_mile_estimate_sec),
        "best_estimated_two_mile_seconds": best_two_mile_estimate_sec,
        "best_estimated_two_mile_source": best_two_mile_source,
        "latest_manual_two_mile": seconds_to_hms(manual_two_mile),
        "current_two_mile_marker": seconds_to_hms(display_two_mile),
        "current_two_mile_marker_seconds": display_two_mile,
        "goal_two_mile": seconds_to_hms(goal_two_mile_seconds),
        "goal_two_mile_seconds": goal_two_mile_seconds,
        "gap_to_goal_seconds": gap_to_goal,
        "recovery_flags": recovery_flags,
        "latest_progress_entry": latest_progress,
        # Legacy name kept for older frontends/docs.
        "latest_acft_entry": latest_progress,
        "recent_activities": [_activity_public(a) for a in recent[:10]],
        "recent_runs_list": [_activity_public(a) for a in recent_run_activities[:10]],
        "settings": settings,
    }


def build_training_projection() -> dict[str, Any]:
    summary = build_latest_summary()
    marker = summary.get("current_two_mile_marker_seconds")
    goal = summary.get("goal_two_mile_seconds") or 900
    gap = summary.get("gap_to_goal_seconds")

    if marker is None:
        status = "Needs data"
        recommendation = "Upload Garmin runs or add a manual 2-mile benchmark so the app can estimate progress."
    elif gap is not None and gap <= 0:
        status = "At or faster than goal"
        recommendation = "Maintain speed with one quality run, one easy run, and one longer easy effort each week."
    elif gap is not None and gap <= 90:
        status = "Close"
        recommendation = "Use one threshold/tempo session weekly, then keep the other runs easy enough to recover from."
    elif gap is not None and gap <= 210:
        status = "Building"
        recommendation = "Focus on consistency: three runs weekly, mostly easy, plus one controlled faster session."
    else:
        status = "Base phase"
        recommendation = "Build easy mileage first, then add harder speed work after your body handles the volume."

    return {
        "estimated_2_mile_time": summary.get("current_two_mile_marker"),
        "estimated_2_mile_seconds": marker,
        "goal_2_mile_time": summary.get("goal_two_mile"),
        "gap_to_goal_seconds": gap,
        "status": status,
        "risk_flags": summary.get("recovery_flags", []),
        "recommendation": recommendation,
        "note": "This is an unofficial training projection for general progress. It is not an official ACFT score calculation.",
    }


# Backward-compatible function name used by older tests/integrations.
def build_acft_projection() -> dict[str, Any]:
    return build_training_projection()
