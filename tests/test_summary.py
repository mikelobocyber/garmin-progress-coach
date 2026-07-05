from app.database import insert_acft_entry, insert_activities
from app.services.garmin_parser import make_fingerprint
from app.services.summary import build_acft_projection, build_latest_summary


def _activity(**overrides):
    activity = {
        "activity_type": "Running",
        "title": "Easy Run",
        "start_time": "2026-07-04T08:00:00",
        "distance_miles": 3.0,
        "duration_seconds": 1800,
        "avg_hr": 150,
        "avg_pace_seconds_per_mile": 600,
        "raw": {},
    }
    activity.update(overrides)
    activity["fingerprint"] = make_fingerprint(activity)
    return activity


def test_empty_summary_has_safe_defaults(temp_db):
    summary = build_latest_summary()
    assert summary["activity_count_total"] == 0
    assert summary["recent_runs"] == 0
    assert "No recent runs found in uploaded data" in summary["recovery_flags"]

    projection = build_acft_projection()
    assert projection["status"] == "Needs data"


def test_summary_week_anchors_to_newest_activity(temp_db):
    insert_activities([
        _activity(title="Old Run", start_time="2026-01-01T08:00:00"),
        _activity(title="New Run", start_time="2026-07-04T08:00:00"),
    ])
    summary = build_latest_summary()
    # Only the newest activity falls in the anchored 7-day window.
    assert summary["recent_runs"] == 1
    assert summary["week_end"] == "2026-07-04"


def test_manual_acft_two_mile_beats_estimate(temp_db):
    insert_activities([_activity()])
    insert_acft_entry({"entry_date": "2026-07-04", "two_mile_seconds": 1000})
    summary = build_latest_summary()
    assert summary["current_two_mile_marker_seconds"] == 1000


def test_projection_note_disclaims_official_scoring(temp_db):
    projection = build_acft_projection()
    assert "unofficial" in projection["note"].lower()


def test_duplicate_insert_is_skipped(temp_db):
    activity = _activity()
    inserted, skipped = insert_activities([activity, dict(activity)])
    assert inserted == 1
    assert skipped == 1
