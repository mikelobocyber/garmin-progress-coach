from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from app.database import fetch_acft_entries, fetch_all_activities, get_settings
from app.services.categories import CARDIO_CATEGORIES, CATEGORY_LABELS, activity_category
from app.services.formatting import seconds_to_hms, seconds_to_pace

__all__ = ["activity_category", "build_latest_summary", "build_training_projection", "build_acft_projection"]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_run(activity: dict[str, Any]) -> bool:
    return activity_category(activity) == "running"


def _safe_mean(values: list[int | float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return round(mean(clean), 2) if clean else None


def _activity_public(activity: dict[str, Any]) -> dict[str, Any]:
    category = activity_category(activity)
    return {
        "id": activity.get("id"),
        "activity_type": activity.get("activity_type"),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, "Other"),
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


def _build_category_summary(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for activity in activities:
        category = activity_category(activity)
        bucket = buckets.setdefault(
            category,
            {
                "category": category,
                "label": CATEGORY_LABELS.get(category, "Other"),
                "sessions": 0,
                "minutes": 0,
                "miles": 0.0,
                "calories": 0,
                "avg_hr": None,
                "_hr_values": [],
            },
        )
        bucket["sessions"] += 1
        bucket["minutes"] += round((activity.get("duration_seconds") or 0) / 60)
        bucket["miles"] += float(activity.get("distance_miles") or 0)
        bucket["calories"] += int(activity.get("calories") or 0)
        if activity.get("avg_hr") is not None:
            bucket["_hr_values"].append(activity.get("avg_hr"))

    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        hr_values = bucket.pop("_hr_values")
        bucket["avg_hr"] = _safe_mean(hr_values)
        bucket["miles"] = round(bucket["miles"], 2)
        result.append(bucket)
    return sorted(result, key=lambda item: (-item["sessions"], item["label"]))


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
    category_summary = _build_category_summary(recent)
    category_counts = {item["category"]: item["sessions"] for item in category_summary}

    total_run_miles = round(sum(float(a.get("distance_miles") or 0) for a in recent_run_activities), 2)
    total_duration = sum(int(a.get("duration_seconds") or 0) for a in recent_run_activities)
    avg_pace_sec = int(total_duration / total_run_miles) if total_run_miles > 0 and total_duration > 0 else None

    total_recent_minutes = round(sum(int(a.get("duration_seconds") or 0) for a in recent) / 60)
    total_recent_calories = sum(int(a.get("calories") or 0) for a in recent)
    avg_recent_hr_all = _safe_mean([a.get("avg_hr") for a in recent])
    recent_strength_sessions = category_counts.get("strength", 0)
    recent_cardio_sessions = sum(category_counts.get(category, 0) for category in CARDIO_CATEGORIES)
    recent_non_run_sessions = max(len(recent) - len(recent_run_activities), 0)

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
    if len(recent) >= 7:
        recovery_flags.append("High overall training frequency this week")
    if len(recent_run_activities) >= 5:
        recovery_flags.append("High run frequency this week")
    if total_run_miles >= 15:
        recovery_flags.append("Higher weekly running mileage than a newer runner block")
    if recent_strength_sessions >= 4:
        recovery_flags.append("High strength-training frequency this week")
    avg_recent_hr = _safe_mean([a.get("avg_hr") for a in recent_run_activities])
    if avg_recent_hr and avg_recent_hr >= 165:
        recovery_flags.append("Average running heart rate looks high")
    if avg_recent_hr_all and avg_recent_hr_all >= 165 and not avg_recent_hr:
        recovery_flags.append("Average activity heart rate looks high")
    if not recovery_flags and recent:
        recovery_flags.append("No obvious recovery red flags from uploaded activity data")
    if not recent:
        recovery_flags.append("No recent activities found in uploaded data")

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
        "recent_activity_minutes": total_recent_minutes,
        "recent_activity_calories": total_recent_calories,
        "recent_training_mix": category_summary,
        "recent_strength_sessions": recent_strength_sessions,
        "recent_cardio_sessions": recent_cardio_sessions,
        "recent_non_run_sessions": recent_non_run_sessions,
        "recent_runs": len(recent_run_activities),
        "recent_run_miles": total_run_miles,
        "recent_avg_run_pace": seconds_to_pace(avg_pace_sec),
        "recent_avg_run_pace_seconds_per_mile": avg_pace_sec,
        "recent_avg_hr": avg_recent_hr,
        "recent_avg_activity_hr": avg_recent_hr_all,
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
    recent_count = summary.get("recent_activity_count", 0)
    strength_sessions = summary.get("recent_strength_sessions", 0)
    cardio_sessions = summary.get("recent_cardio_sessions", 0)

    if recent_count == 0 and not summary.get("latest_progress_entry"):
        status = "Needs data"
        recommendation = "Upload Garmin activities or add a manual progress entry so the app can estimate your current training pattern."
    elif marker is None:
        if cardio_sessions >= 3 and strength_sessions >= 2:
            status = "Balanced general fitness week"
            recommendation = "You have both conditioning and strength represented. Keep one easier recovery day between the hardest sessions."
        elif cardio_sessions >= 3:
            status = "Cardio-focused week"
            recommendation = "Good conditioning consistency. Add 1-2 short strength sessions if strength or body composition is part of the goal."
        elif strength_sessions >= 2:
            status = "Strength-focused week"
            recommendation = "Strength work is showing up. Add low-intensity cardio or walking if you want better conditioning without wrecking recovery."
        else:
            status = "Building consistency"
            recommendation = "Aim for 3-5 total sessions this week across cardio, strength, walking, or mobility before worrying about perfect programming."
    elif gap is not None and gap <= 0:
        status = "At or faster than running goal"
        recommendation = "Maintain speed with one quality run, one easy run, one longer easy effort, and strength work that does not crush recovery."
    elif gap is not None and gap <= 90:
        status = "Close to running goal"
        recommendation = "Use one threshold/tempo session weekly, keep the other runs easy, and place heavy leg lifting away from speed work."
    elif gap is not None and gap <= 210:
        status = "Building running fitness"
        recommendation = "Focus on consistency: three runs weekly, mostly easy, plus one controlled faster session and 1-2 strength sessions."
    else:
        status = "Base phase"
        recommendation = "Build easy cardio volume first, use strength to stay durable, then add harder speed work after your body handles the volume."

    return {
        "estimated_2_mile_time": summary.get("current_two_mile_marker"),
        "estimated_2_mile_seconds": marker,
        "goal_2_mile_time": summary.get("goal_two_mile"),
        "gap_to_goal_seconds": gap,
        "status": status,
        "risk_flags": summary.get("recovery_flags", []),
        "recommendation": recommendation,
        "training_mix": summary.get("recent_training_mix", []),
        "note": "This is an unofficial training projection for general progress. It is not an official ACFT score calculation.",
    }


# Backward-compatible function name used by older tests/integrations.
def build_acft_projection() -> dict[str, Any]:
    return build_training_projection()
