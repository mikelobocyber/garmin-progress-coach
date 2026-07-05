from __future__ import annotations

from typing import Any

CARDIO_CATEGORIES = {"running", "cycling", "cardio", "swimming", "walking_hiking"}
CATEGORY_LABELS = {
    "running": "Running",
    "strength": "Strength",
    "cycling": "Cycling",
    "cardio": "Cardio",
    "walking_hiking": "Walking/Hiking",
    "mobility": "Mobility",
    "swimming": "Swimming",
    "other": "Other",
}


def activity_category(activity: dict[str, Any]) -> str:
    """Group Garmin activity names into useful training buckets.

    Garmin's activity types are not perfectly consistent across locales,
    devices, CSV vs FIT exports, and custom activity names, so this
    intentionally uses broad text matching instead of a fragile enum.

    Shared by the summary layer (for the training mix) and the parsers
    (as the type component of the dedupe fingerprint, so "Running" from
    a CSV and "running" from a FIT file land in the same bucket).
    """
    text = f"{activity.get('activity_type') or ''} {activity.get('title') or ''}".lower()

    if any(token in text for token in ("run", "running", "treadmill")):
        return "running"
    if any(token in text for token in ("strength", "weight", "lifting", "lift", "gym", "dumbbell", "barbell", "deadlift", "squat", "bench")):
        return "strength"
    if any(token in text for token in ("bike", "biking", "cycle", "cycling", "indoor cycling", "mountain bike")):
        return "cycling"
    if any(token in text for token in ("swim", "swimming")):
        return "swimming"
    if any(token in text for token in ("walk", "walking", "hike", "hiking")):
        return "walking_hiking"
    if any(token in text for token in ("yoga", "pilates", "mobility", "stretch", "stretching", "breathwork")):
        return "mobility"
    if any(token in text for token in ("cardio", "elliptical", "stair", "row", "rowing", "erg", "hiit", "boxing", "jump rope")):
        return "cardio"
    return "other"
