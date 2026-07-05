from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

from garmin_fit_sdk import Decoder, Stream

from app.services.garmin_parser import MILES_PER_KM, make_fingerprint

# Zip-bomb guards. "Export Original" zips contain one small FIT file;
# a folder copied off a watch is at most a few hundred.
MAX_ZIP_MEMBERS = 200
MAX_MEMBER_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024

METERS_PER_MILE = 1609.344


class GarminFitError(ValueError):
    """Raised when a file cannot be read as FIT data.

    The message is written to be shown directly to the user. A *valid* FIT
    file that just isn't an activity (e.g. daily monitoring data from a
    watch folder) is not an error — parse_fit returns [] for those.
    """


def _pretty_type(sport: Any, sub_sport: Any) -> str:
    """Turn FIT sport/sub_sport enums into a CSV-style activity type.

    Prefers the more specific sub_sport ("strength_training" over
    "training") so categorization matches what CSV exports produce.
    """
    for value in (sub_sport, sport):
        text = str(value or "").strip().lower()
        if text and text != "generic" and not text.isdigit():
            return text.replace("_", " ").title()
    return "Unknown"


# Seconds between the Unix and FIT epochs (1989-12-31T00:00:00Z).
FIT_EPOCH_OFFSET = 631065600


def _local_offset(messages: dict[str, Any]) -> timedelta:
    """Derive the watch's UTC offset from the FIT activity message.

    FIT session timestamps are UTC, but CSV exports use local wall-clock
    time. Without this correction the same workout would get different
    dedupe fingerprints from the two formats.

    The SDK converts `timestamp` to a datetime but leaves `local_timestamp`
    as raw FIT-epoch seconds (it is a local wall-clock value, not UTC).
    """
    for mesg in messages.get("activity_mesgs", []) or []:
        timestamp = mesg.get("timestamp")
        local = mesg.get("local_timestamp")
        if isinstance(timestamp, datetime) and isinstance(local, (int, float)):
            utc_seconds = timestamp.replace(tzinfo=timezone.utc).timestamp() - FIT_EPOCH_OFFSET
            offset_seconds = float(local) - utc_seconds
            # Round to 15 min to shrug off clock drift while keeping
            # real-world offsets (including :30 and :45 zones) exact.
            quarter_hours = round(offset_seconds / 900)
            return timedelta(seconds=quarter_hours * 900)
    return timedelta(0)


def _session_to_activity(session: dict[str, Any], offset: timedelta, filename: str) -> dict[str, Any] | None:
    start = session.get("start_time") or session.get("timestamp")
    if isinstance(start, datetime):
        start_iso = (start.replace(tzinfo=None) + offset).isoformat()
    else:
        start_iso = None

    distance_m = session.get("total_distance")
    distance_miles = round(float(distance_m) / METERS_PER_MILE, 3) if distance_m else None

    # Prefer timer time (excludes pauses) to match how Garmin CSV reports "Time".
    duration_raw = session.get("total_timer_time") or session.get("total_elapsed_time")
    duration_seconds = int(duration_raw) if duration_raw else None

    avg_pace = None
    if distance_miles and duration_seconds and distance_miles > 0.05:
        avg_pace = int(duration_seconds / distance_miles)

    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    activity = {
        "source_filename": filename,
        "activity_type": _pretty_type(session.get("sport"), session.get("sub_sport")),
        "title": "Garmin Activity",  # FIT sessions carry no user-facing title.
        "start_time": start_iso,
        "distance_miles": distance_miles,
        "duration_seconds": duration_seconds,
        "calories": _int_or_none(session.get("total_calories")),
        "avg_hr": _int_or_none(session.get("avg_heart_rate")),
        "max_hr": _int_or_none(session.get("max_heart_rate")),
        "avg_pace_seconds_per_mile": avg_pace,
        "best_pace_seconds_per_mile": None,
        # Store session summary values only — never the per-second record
        # samples (GPS, heart rate), keeping the privacy promise intact.
        "raw": {
            "format": "fit",
            "sport": str(session.get("sport")),
            "sub_sport": str(session.get("sub_sport")),
        },
    }

    if not any([activity["start_time"], activity["distance_miles"], activity["duration_seconds"]]):
        return None

    activity["fingerprint"] = make_fingerprint(activity)
    return activity


def parse_fit(content: bytes, filename: str = "activity.fit") -> list[dict[str, Any]]:
    """Parse one FIT file into activity dicts (one per session).

    Returns [] for valid FIT files that contain no activity sessions,
    such as monitoring/wellness files from a watch's GARMIN folder.
    """
    stream = Stream.from_byte_array(bytearray(content))
    decoder = Decoder(stream)
    if not decoder.is_fit():
        raise GarminFitError(f"{filename} isn't a FIT file. Use 'Export Original' on a Garmin Connect activity, or copy .fit files from your watch.")

    messages, errors = decoder.read(merge_heart_rates=False)
    sessions = messages.get("session_mesgs", []) or []
    if errors and not sessions:
        raise GarminFitError(f"{filename} looks like a FIT file but couldn't be decoded — it may be truncated or corrupt.")

    offset = _local_offset(messages)
    activities = []
    for session in sessions:
        activity = _session_to_activity(session, offset, filename)
        if activity:
            activities.append(activity)
    return activities


def parse_fit_zip(content: bytes, filename: str = "export.zip") -> tuple[list[dict[str, Any]], list[str]]:
    """Parse every .fit inside a zip (Garmin's 'Export Original' format).

    Returns (activities, notes) where notes describe members that were
    skipped and why. Members are read in memory only — nothing is
    extracted to disk, so hostile paths in the archive are inert.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise GarminFitError(f"{filename} isn't a readable zip file.") from exc

    members = [m for m in archive.infolist() if not m.is_dir() and m.filename.lower().endswith(".fit")]
    if not members:
        raise GarminFitError(f"No .fit files inside {filename}. Garmin's 'Export Original' zip should contain one.")
    if len(members) > MAX_ZIP_MEMBERS:
        raise GarminFitError(f"{filename} contains {len(members)} FIT files — more than the {MAX_ZIP_MEMBERS} this app will import at once.")

    activities: list[dict[str, Any]] = []
    notes: list[str] = []
    total = 0
    for member in members:
        if member.file_size > MAX_MEMBER_BYTES:
            notes.append(f"{member.filename}: skipped (too large)")
            continue
        total += member.file_size
        if total > MAX_TOTAL_BYTES:
            raise GarminFitError(f"{filename} decompresses to more than {MAX_TOTAL_BYTES // (1024 * 1024)} MB — refusing to import it.")
        data = archive.read(member)
        try:
            parsed = parse_fit(data, filename=member.filename)
        except GarminFitError:
            notes.append(f"{member.filename}: skipped (not readable as FIT)")
            continue
        if not parsed:
            notes.append(f"{member.filename}: skipped (not an activity)")
            continue
        activities.extend(parsed)
    return activities, notes
