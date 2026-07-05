import pytest

from app.services.garmin_parser import (
    GarminCsvError,
    parse_distance_miles,
    parse_duration_seconds,
    parse_float,
    parse_garmin_csv,
    parse_pace_seconds_per_mile,
)


def test_parse_duration_formats():
    assert parse_duration_seconds("00:18:24") == 1104
    assert parse_duration_seconds("18:24") == 1104
    assert parse_duration_seconds("1:02:33.5") == 3753
    assert parse_duration_seconds("1h 2m 3s") == 3723
    assert parse_duration_seconds("1104") == 1104
    assert parse_duration_seconds("--") is None
    assert parse_duration_seconds(None) is None


def test_parse_pace_units():
    assert parse_pace_seconds_per_mile("09:12") == 552
    # 5:43 min/km ≈ 9:12 min/mi
    assert parse_pace_seconds_per_mile("5:43 /km") == pytest.approx(552, abs=1)
    assert parse_pace_seconds_per_mile("5:43", column_name="avg_pace_min_km") == pytest.approx(552, abs=1)
    assert parse_pace_seconds_per_mile("--") is None


def test_parse_numbers_with_locale_commas():
    assert parse_float("1,024.5") == 1024.5   # thousands separator
    assert parse_float("2,20") == 2.20        # European decimal comma


def test_parse_distance_km_conversion():
    assert parse_distance_miles("3.22", column_name="distance_km") == pytest.approx(2.0, abs=0.01)
    assert parse_distance_miles("2.00") == 2.0
    assert parse_distance_miles("-1") is None


def test_parse_garmin_csv_basic():
    content = b"Activity Type,Date,Title,Distance,Time,Avg HR,Max HR,Avg Pace\nRunning,2026-07-04,Two Mile,2.00,00:18:24,171,187,09:12\n"
    rows = parse_garmin_csv(content, "sample.csv")
    assert len(rows) == 1
    assert rows[0]["activity_type"] == "Running"
    assert rows[0]["distance_miles"] == 2.0
    assert rows[0]["duration_seconds"] == 1104
    assert rows[0]["avg_pace_seconds_per_mile"] == 552


def test_parse_garmin_csv_semicolon_delimiter():
    content = b"Activity Type;Date;Distance;Time\nRunning;2026-07-04;2,00;00:18:24\n"
    rows = parse_garmin_csv(content)
    assert len(rows) == 1
    assert rows[0]["distance_miles"] == 2.0


def test_parse_garmin_csv_missing_markers_and_derived_pace():
    content = b"Activity Type,Date,Distance,Time,Avg HR,Avg Pace\nRunning,2026-07-04,2.00,00:18:24,--,--\n"
    rows = parse_garmin_csv(content)
    assert rows[0]["avg_hr"] is None
    # Pace derived from distance/time when the column is missing.
    assert rows[0]["avg_pace_seconds_per_mile"] == 552


def test_parse_garmin_csv_dedupe_fingerprint_is_stable():
    content = b"Activity Type,Date,Distance,Time\nRunning,2026-07-04,2.00,00:18:24\n"
    a = parse_garmin_csv(content, "a.csv")[0]
    b = parse_garmin_csv(content, "b.csv")[0]
    # Same activity from two differently named exports must dedupe.
    assert a["fingerprint"] == b["fingerprint"]


def test_parse_garmin_csv_rejects_empty_file():
    with pytest.raises(GarminCsvError):
        parse_garmin_csv(b"")


def test_parse_garmin_csv_rejects_unrelated_columns():
    with pytest.raises(GarminCsvError) as excinfo:
        parse_garmin_csv(b"foo,bar\n1,2\n")
    assert "Activity Type" in str(excinfo.value)


def test_parse_garmin_csv_skips_blank_rows():
    content = b"Activity Type,Date,Distance,Time\nRunning,2026-07-04,2.00,00:18:24\n,,,\n"
    rows = parse_garmin_csv(content)
    assert len(rows) == 1
