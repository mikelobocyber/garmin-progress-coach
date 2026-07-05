import io
import zipfile
from datetime import datetime, timezone

import pytest

from app.database import fetch_all_activities, insert_activities
from app.services.fit_parser import GarminFitError, parse_fit, parse_fit_zip
from app.services.garmin_parser import parse_garmin_csv
from tests.fit_fixture import make_fit_bytes

RUN_START_UTC = datetime(2026, 7, 4, 12, 5, tzinfo=timezone.utc)  # 08:05 local at UTC-4

# The same run as it appears in a Garmin CSV export: local wall-clock time,
# miles, a user-facing title, seconds truncated differently.
MATCHING_CSV = (
    b"Activity Type,Date,Title,Distance,Time,Avg HR,Avg Pace\n"
    b"Running,2026-07-04 08:05:12,Two Mile Check,2.00,00:18:24,171,09:12\n"
)


def _run_fit(**overrides):
    defaults = dict(start_utc=RUN_START_UTC, utc_offset_hours=-4)
    defaults.update(overrides)
    return make_fit_bytes(**defaults)


def test_parse_fit_extracts_session_summary():
    [activity] = parse_fit(_run_fit())
    assert activity["activity_type"] == "Running"
    assert activity["distance_miles"] == pytest.approx(2.0, abs=0.01)
    assert activity["duration_seconds"] == 1104
    assert activity["avg_hr"] == 171
    assert activity["max_hr"] == 187
    assert activity["avg_pace_seconds_per_mile"] == pytest.approx(552, abs=2)


def test_parse_fit_converts_utc_to_local_time():
    [activity] = parse_fit(_run_fit())
    assert activity["start_time"].startswith("2026-07-04T08:05")


def test_parse_fit_never_stores_raw_samples():
    [activity] = parse_fit(_run_fit())
    # Only summary metadata goes into raw_json — no GPS/HR sample streams.
    assert set(activity["raw"].keys()) <= {"format", "sport", "sub_sport"}


def test_parse_fit_sub_sport_maps_to_strength():
    [activity] = parse_fit(_run_fit(sport="training", sub_sport="strength_training", distance_meters=None))
    assert activity["activity_type"] == "Strength Training"


def test_parse_fit_monitoring_file_returns_empty():
    assert parse_fit(make_fit_bytes(start_utc=RUN_START_UTC, include_session=False)) == []


def test_parse_fit_rejects_non_fit_bytes():
    with pytest.raises(GarminFitError):
        parse_fit(b"definitely not a fit file")


def test_fingerprints_match_across_csv_and_fit():
    [fit_activity] = parse_fit(_run_fit())
    [csv_activity] = parse_garmin_csv(MATCHING_CSV)
    assert fit_activity["fingerprint"] == csv_activity["fingerprint"]


def test_fit_upload_after_csv_merges_and_upgrades(temp_db):
    # CSV row first: has a title but pretend it lacks max HR.
    [csv_activity] = parse_garmin_csv(MATCHING_CSV)
    csv_activity["max_hr"] = None
    insert_activities([csv_activity])

    # FIT copy of the same run arrives later with max HR but no title.
    [fit_activity] = parse_fit(_run_fit())
    inserted, merged = insert_activities([fit_activity])
    assert (inserted, merged) == (0, 1)

    [row] = fetch_all_activities()
    assert row["title"] == "Two Mile Check"  # CSV title kept
    assert row["max_hr"] == 187              # FIT filled the gap


def test_csv_after_fit_upgrades_placeholder_title(temp_db):
    [fit_activity] = parse_fit(_run_fit())
    insert_activities([fit_activity])
    [csv_activity] = parse_garmin_csv(MATCHING_CSV)
    insert_activities([csv_activity])

    [row] = fetch_all_activities()
    assert row["title"] == "Two Mile Check"  # placeholder replaced


def _zip_of(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_parse_fit_zip_mixed_contents():
    entries = {
        "activity.fit": _run_fit(),
        "monitoring.fit": make_fit_bytes(start_utc=RUN_START_UTC, include_session=False),
        "readme.txt": b"ignore me",
    }
    activities, notes = parse_fit_zip(_zip_of(entries))
    assert len(activities) == 1
    assert any("not an activity" in note for note in notes)


def test_parse_fit_zip_without_fit_files_errors():
    with pytest.raises(GarminFitError):
        parse_fit_zip(_zip_of({"readme.txt": b"hello"}))


def test_parse_fit_zip_rejects_garbage():
    with pytest.raises(GarminFitError):
        parse_fit_zip(b"not a zip at all")


def test_dateonly_csv_merges_with_timed_fit(temp_db):
    # CSV export with a date but no time-of-day (some exports do this).
    dateonly_csv = (
        b"Activity Type,Date,Title,Distance,Time,Avg HR\n"
        b"Running,2026-07-04,Two Mile Benchmark,2.00,00:18:24,171\n"
    )
    [csv_activity] = parse_garmin_csv(dateonly_csv)
    insert_activities([csv_activity])

    [fit_activity] = parse_fit(_run_fit())  # same run with a precise 08:05 start
    inserted, merged = insert_activities([fit_activity])
    assert (inserted, merged) == (0, 1)

    [row] = fetch_all_activities()
    assert row["title"] == "Two Mile Benchmark"
    assert row["start_time"].startswith("2026-07-04T08:05")  # timestamp upgraded
    assert row["max_hr"] == 187


def test_two_similar_dateonly_rows_stay_distinct(temp_db):
    # Same day, same distance, but different runs — title/duration differ.
    csv = (
        b"Activity Type,Date,Title,Distance,Time\n"
        b"Running,2026-07-04,Morning Run,3.00,00:30:00\n"
        b"Running,2026-07-04,Evening Run,3.00,00:27:00\n"
    )
    activities = parse_garmin_csv(csv)
    inserted, merged = insert_activities(activities)
    assert (inserted, merged) == (2, 0)
