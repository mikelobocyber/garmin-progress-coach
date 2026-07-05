from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

def db_path() -> Path:
    # Resolved at call time (not import time) so tests and .env changes
    # can point the app at a different database.
    return Path(os.getenv("GARMIN_AI_COACH_DB", "data/garmin_ai_coach.sqlite3"))


def get_connection() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT UNIQUE NOT NULL,
                source_filename TEXT,
                activity_type TEXT,
                title TEXT,
                start_time TEXT,
                distance_miles REAL,
                duration_seconds INTEGER,
                calories INTEGER,
                avg_hr INTEGER,
                max_hr INTEGER,
                avg_pace_seconds_per_mile INTEGER,
                best_pace_seconds_per_mile INTEGER,
                raw_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS acft_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL,
                body_weight_lbs REAL,
                deadlift_lbs INTEGER,
                sprint_drag_carry_seconds INTEGER,
                plank_seconds INTEGER,
                pushups INTEGER,
                two_mile_seconds INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities (start_time)"
        )
        # Expression index so the day-level duplicate lookup in
        # insert_activities stays fast on large imports.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activities_day ON activities (substr(start_time, 1, 10))"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_into_existing(conn: sqlite3.Connection, fingerprint: str, activity: dict[str, Any], upgrade_time: str | None = None) -> None:
    """Fill NULL fields on a stored duplicate with values from a new copy.

    Same workout seen again (e.g. CSV first, FIT later): instead of
    discarding the new copy, use it to fill in fields the stored row is
    missing — FIT files carry data the CSV export may lack, and vice
    versa (titles). When upgrade_time is set, the stored date-only
    timestamp (and its fingerprint) is replaced with the precise one.
    """
    conn.execute(
        """
        UPDATE activities SET
            distance_miles = COALESCE(distance_miles, ?),
            duration_seconds = COALESCE(duration_seconds, ?),
            calories = COALESCE(calories, ?),
            avg_hr = COALESCE(avg_hr, ?),
            max_hr = COALESCE(max_hr, ?),
            avg_pace_seconds_per_mile = COALESCE(avg_pace_seconds_per_mile, ?),
            best_pace_seconds_per_mile = COALESCE(best_pace_seconds_per_mile, ?),
            title = CASE
                WHEN (title IS NULL OR title = '' OR title = 'Garmin Activity') AND ? != 'Garmin Activity'
                THEN ? ELSE title
            END,
            start_time = COALESCE(?, start_time),
            fingerprint = COALESCE(?, fingerprint)
        WHERE fingerprint = ?
        """,
        (
            activity.get("distance_miles"),
            activity.get("duration_seconds"),
            activity.get("calories"),
            activity.get("avg_hr"),
            activity.get("max_hr"),
            activity.get("avg_pace_seconds_per_mile"),
            activity.get("best_pace_seconds_per_mile"),
            activity.get("title"),
            activity.get("title"),
            upgrade_time,
            activity["fingerprint"] if upgrade_time else None,
            fingerprint,
        ),
    )


def _is_dateonly(start_time: str | None) -> bool:
    return bool(start_time) and str(start_time).endswith("T00:00:00")


def _distance_token(value: Any) -> str:
    return f"{round(float(value) / 0.05) * 0.05:.2f}" if value else ""


def _find_day_level_match(conn: sqlite3.Connection, activity: dict[str, Any]) -> dict[str, Any] | None:
    """Match a timed activity against a stored date-only copy (or vice versa).

    Some CSV exports carry only a date, which parses as midnight, so the
    minute-level fingerprint can never equal the FIT copy's. When exactly
    one side lacks a time-of-day, fall back to matching on the same day,
    category bucket, and distance bucket.
    """
    from app.services.categories import activity_category

    start = activity.get("start_time")
    if not start:
        return None
    day = str(start)[:10]
    rows = conn.execute(
        "SELECT * FROM activities WHERE substr(start_time, 1, 10) = ?", (day,)
    ).fetchall()
    for row in rows:
        stored = dict(row)
        if _is_dateonly(stored.get("start_time")) == _is_dateonly(start):
            continue  # both timed or both date-only: fingerprints already decide
        if activity_category(stored) != activity_category(activity):
            continue
        if _distance_token(stored.get("distance_miles")) != _distance_token(activity.get("distance_miles")):
            continue
        return stored
    return None


def insert_activities(activities: Iterable[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    merged = 0
    with get_connection() as conn:
        for activity in activities:
            match = _find_day_level_match(conn, activity)
            if match is not None:
                # Upgrade the stored row's timestamp when the new copy has one.
                upgrade = activity.get("start_time") if _is_dateonly(match.get("start_time")) else None
                _merge_into_existing(conn, match["fingerprint"], activity, upgrade_time=upgrade)
                merged += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO activities (
                        fingerprint, source_filename, activity_type, title, start_time,
                        distance_miles, duration_seconds, calories, avg_hr, max_hr,
                        avg_pace_seconds_per_mile, best_pace_seconds_per_mile,
                        raw_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        activity["fingerprint"],
                        activity.get("source_filename"),
                        activity.get("activity_type"),
                        activity.get("title"),
                        activity.get("start_time"),
                        activity.get("distance_miles"),
                        activity.get("duration_seconds"),
                        activity.get("calories"),
                        activity.get("avg_hr"),
                        activity.get("max_hr"),
                        activity.get("avg_pace_seconds_per_mile"),
                        activity.get("best_pace_seconds_per_mile"),
                        json.dumps(activity.get("raw", {})),
                        now_iso(),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                _merge_into_existing(conn, activity["fingerprint"], activity)
                merged += 1
        conn.commit()
    return inserted, merged


def fetch_activities(limit: int = 50, activity_type: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM activities"
    params: list[Any] = []
    if activity_type:
        query += " WHERE LOWER(activity_type) LIKE ?"
        params.append(f"%{activity_type.lower()}%")
    query += " ORDER BY COALESCE(start_time, created_at) DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def fetch_all_activities() -> list[dict[str, Any]]:
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM activities ORDER BY COALESCE(start_time, created_at) DESC").fetchall()]


def insert_acft_entry(entry: dict[str, Any]) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO acft_entries (
                entry_date, body_weight_lbs, deadlift_lbs, sprint_drag_carry_seconds,
                plank_seconds, pushups, two_mile_seconds, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["entry_date"],
                entry.get("body_weight_lbs"),
                entry.get("deadlift_lbs"),
                entry.get("sprint_drag_carry_seconds"),
                entry.get("plank_seconds"),
                entry.get("pushups"),
                entry.get("two_mile_seconds"),
                entry.get("notes"),
                now_iso(),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def fetch_acft_entries(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM acft_entries ORDER BY entry_date DESC, id DESC LIMIT ?", (limit,)).fetchall()]


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now_iso()),
        )
        conn.commit()


def get_settings() -> dict[str, str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}
