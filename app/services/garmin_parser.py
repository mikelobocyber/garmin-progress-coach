from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Any

from dateutil import parser as date_parser

MILES_PER_KM = 0.621371
KM_PER_MILE = 1.609344
MAX_ROWS = 20_000

# Headers we know how to map, in priority order. Matching is done on
# normalized keys, so "Avg HR", "avg_hr", and "Avg  HR " are all equivalent.
COLUMN_CANDIDATES = {
    "activity_type": ["Activity Type", "Type", "Sport", "Activity"],
    "title": ["Title", "Activity Name", "Name"],
    "start_time": ["Date", "Start Time", "Start", "Time Started"],
    "distance": ["Distance", "Distance (mi)", "Distance (miles)", "Distance (km)"],
    "duration": ["Time", "Duration", "Total Time", "Elapsed Time", "Moving Time"],
    "calories": ["Calories", "Calories Burned"],
    "avg_hr": ["Avg HR", "Average HR", "Avg Heart Rate", "Average Heart Rate"],
    "max_hr": ["Max HR", "Maximum HR", "Max Heart Rate", "Maximum Heart Rate"],
    "avg_pace": ["Avg Pace", "Average Pace", "Avg Run Pace", "Pace"],
    "best_pace": ["Best Pace", "Max Pace", "Fastest Pace"],
}

MISSING_MARKERS = {"", "--", "-", "n/a", "na", "null", "none"}


class GarminCsvError(ValueError):
    """Raised when a file cannot be interpreted as a Garmin activity CSV.

    The message is written to be shown directly to the user.
    """


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _is_missing(value: Any) -> bool:
    return value is None or str(value).strip().lower() in MISSING_MARKERS


def first_value(row: dict[str, Any], candidates: list[str]) -> tuple[Any, str | None]:
    for candidate in candidates:
        key = normalize_key(candidate)
        if key in row and not _is_missing(row[key]):
            return row[key], key
    return None, None


def _clean_number_text(value: Any) -> str:
    """Normalize numeric text before parsing.

    Garmin exports vary by locale: "1,024.5" (comma thousands) vs "2,20"
    (comma decimal, common in European exports). A comma followed by exactly
    3 digits is treated as a thousands separator; otherwise as a decimal point.
    """
    text = str(value).strip()
    text = re.sub(r",(?=\d{3}(\D|$))", "", text)
    text = text.replace(",", ".")
    return text


def parse_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    match = re.search(r"-?\d+", _clean_number_text(value))
    return int(match.group(0)) if match else None


def parse_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", _clean_number_text(value))
    return float(match.group(0)) if match else None


def parse_distance_miles(value: Any, column_name: str | None = None) -> float | None:
    number = parse_float(value)
    if number is None or number < 0:
        return None
    text = str(value).lower()
    col = (column_name or "").lower()
    is_km = (
        any(token in text for token in (" km", "kilometer", "kilometre"))
        or "km" in col
        or "kilometer" in col
    )
    return round(number * MILES_PER_KM, 3) if is_km else round(number, 3)


def parse_duration_seconds(value: Any) -> int | None:
    if _is_missing(value):
        return None
    text = str(value).strip().lower()

    # Clock formats: 00:25:12, 25:12, 1:02:33.5 — possibly with a unit
    # suffix like "5:43 /km", which we strip before splitting.
    clock = re.search(r"\d+(?::\d+(?:\.\d+)?){1,2}", text)
    if ":" in text and clock:
        parts = [float(part) for part in clock.group(0).split(":")]
        if len(parts) == 3:
            return int(parts[0] * 3600 + parts[1] * 60 + parts[2])
        if len(parts) == 2:
            return int(parts[0] * 60 + parts[1])
        if len(parts) == 1:
            return int(parts[0])
        return None

    # Unit formats: 1h 2m 3s, 25m 12s
    total = 0.0
    found = False
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", text):
        found = True
        amount = float(number)
        total += amount * {"h": 3600, "m": 60, "s": 1}[unit]
    if found:
        return int(total)

    # Garmin sometimes exports plain seconds.
    return parse_int(text)


def parse_pace_seconds_per_mile(value: Any, column_name: str | None = None) -> int | None:
    seconds = parse_duration_seconds(value)
    if seconds is None or seconds <= 0:
        return None
    text = str(value).lower()
    col = (column_name or "").lower()
    is_per_km = "/km" in text or "per km" in text or "min/km" in col or "_km" in col
    return int(round(seconds * KM_PER_MILE)) if is_per_km else seconds


def parse_start_time(value: Any) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    try:
        # fuzzy=False on purpose: better to keep the raw text than to
        # invent a date out of something like "Week 26".
        return date_parser.parse(text).isoformat()
    except (ValueError, TypeError, OverflowError):
        # Keep the original text so it still contributes to the dedupe
        # fingerprint; the summary layer simply skips undated activities.
        return text


def make_fingerprint(activity: dict[str, Any]) -> str:
    basis = "|".join(
        str(activity.get(key) or "")
        for key in ["activity_type", "title", "start_time", "distance_miles", "duration_seconds"]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _detect_dialect(text: str) -> csv.Dialect | type[csv.Dialect]:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel  # plain comma-separated


def parse_garmin_csv(content: bytes, filename: str = "upload.csv") -> list[dict[str, Any]]:
    """Parse a Garmin Connect activities CSV export into activity dicts.

    Raises GarminCsvError with a user-facing message when the file is empty,
    has no header row, or has no recognizable Garmin columns.
    """
    text = content.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise GarminCsvError("The file is empty. Export your activities from Garmin Connect as CSV and try again.")

    reader = csv.DictReader(io.StringIO(text), dialect=_detect_dialect(text))
    if not reader.fieldnames:
        raise GarminCsvError("No header row found. The first line of the CSV should list column names like 'Activity Type, Date, Distance'.")

    normalized_headers = {normalize_key(name) for name in reader.fieldnames if name}
    known_keys = {
        normalize_key(candidate)
        for candidates in COLUMN_CANDIDATES.values()
        for candidate in candidates
    }
    if not normalized_headers & known_keys:
        found = ", ".join(sorted(h for h in normalized_headers if h)) or "(none)"
        raise GarminCsvError(
            "None of the columns look like a Garmin activities export. "
            f"Columns found: {found}. Expected columns like 'Activity Type', 'Date', 'Distance', 'Time'."
        )

    activities: list[dict[str, Any]] = []
    for i, original in enumerate(reader):
        if i >= MAX_ROWS:
            break
        row = {normalize_key(key): value for key, value in original.items() if key is not None}

        activity_type, _ = first_value(row, COLUMN_CANDIDATES["activity_type"])
        title, _ = first_value(row, COLUMN_CANDIDATES["title"])
        start_time, _ = first_value(row, COLUMN_CANDIDATES["start_time"])
        distance, distance_col = first_value(row, COLUMN_CANDIDATES["distance"])
        duration, _ = first_value(row, COLUMN_CANDIDATES["duration"])
        calories, _ = first_value(row, COLUMN_CANDIDATES["calories"])
        avg_hr, _ = first_value(row, COLUMN_CANDIDATES["avg_hr"])
        max_hr, _ = first_value(row, COLUMN_CANDIDATES["max_hr"])
        avg_pace, avg_pace_col = first_value(row, COLUMN_CANDIDATES["avg_pace"])
        best_pace, best_pace_col = first_value(row, COLUMN_CANDIDATES["best_pace"])

        activity = {
            "source_filename": filename,
            "activity_type": str(activity_type or "Unknown").strip(),
            "title": str(title or "Garmin Activity").strip(),
            "start_time": parse_start_time(start_time),
            "distance_miles": parse_distance_miles(distance, distance_col),
            "duration_seconds": parse_duration_seconds(duration),
            "calories": parse_int(calories),
            "avg_hr": parse_int(avg_hr),
            "max_hr": parse_int(max_hr),
            "avg_pace_seconds_per_mile": parse_pace_seconds_per_mile(avg_pace, avg_pace_col),
            "best_pace_seconds_per_mile": parse_pace_seconds_per_mile(best_pace, best_pace_col),
            "raw": original,
        }

        # Derive average pace when Garmin omits it but distance/time exist.
        if (
            activity["avg_pace_seconds_per_mile"] is None
            and activity["distance_miles"]
            and activity["duration_seconds"]
            and activity["distance_miles"] > 0
        ):
            activity["avg_pace_seconds_per_mile"] = int(activity["duration_seconds"] / activity["distance_miles"])

        # Skip rows with no usable signal (blank lines, summary footers).
        if not any([activity["start_time"], activity["distance_miles"], activity["duration_seconds"], activity_type, title]):
            continue

        activity["fingerprint"] = make_fingerprint(activity)
        activities.append(activity)
    return activities
