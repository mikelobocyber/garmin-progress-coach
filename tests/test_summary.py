from app.database import insert_acft_entry, insert_activities
from app.services.garmin_parser import make_fingerprint
from app.services.summary import activity_category, build_acft_projection, build_latest_summary


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
    assert "No recent activities found in uploaded data" in summary["recovery_flags"]

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


def test_activity_category_detects_strength_and_cardio(temp_db):
    assert activity_category({"activity_type": "Strength Training", "title": "Upper Body Lift"}) == "strength"
    assert activity_category({"activity_type": "Cycling", "title": "Zone 2 Bike"}) == "cycling"
    assert activity_category({"activity_type": "Cardio", "title": "Elliptical"}) == "cardio"


def test_summary_counts_strength_and_cardio_sessions(temp_db):
    insert_activities([
        _activity(activity_type="Strength Training", title="Upper Body Lift", distance_miles=None, duration_seconds=2700),
        _activity(activity_type="Cycling", title="Zone 2 Bike", distance_miles=8.0, duration_seconds=2100),
        _activity(activity_type="Running", title="Easy Run", distance_miles=2.0, duration_seconds=1200),
    ])
    summary = build_latest_summary()
    assert summary["recent_strength_sessions"] == 1
    assert summary["recent_cardio_sessions"] == 2
    labels = {item["label"] for item in summary["recent_training_mix"]}
    assert {"Strength", "Cycling", "Running"}.issubset(labels)
