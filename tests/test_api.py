import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_CSV = b"Activity Type,Date,Title,Distance,Time,Avg HR,Avg Pace\nRunning,2026-07-04,Two Mile,2.00,00:18:24,171,09:12\n"


@pytest.fixture()
def client(temp_db):
    with TestClient(app) as test_client:
        yield test_client


def test_index_serves_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Garmin Progress Coach" in response.text


def test_upload_and_summary_roundtrip(client):
    response = client.post(
        "/api/upload/garmin-csv",
        files={"file": ("export.csv", SAMPLE_CSV, "text/csv")},
    )
    assert response.status_code == 200
    assert response.json()["inserted"] == 1

    summary = client.get("/api/summary/latest").json()
    assert summary["activity_count_total"] == 1
    assert summary["recent_runs"] == 1
    assert summary["recent_cardio_sessions"] == 1


def test_upload_rejects_non_csv_extension(client):
    response = client.post(
        "/api/upload/garmin-csv",
        files={"file": ("export.fit", b"binary", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_upload_rejects_unrecognized_columns_with_helpful_message(client):
    response = client.post(
        "/api/upload/garmin-csv",
        files={"file": ("export.csv", b"foo,bar\n1,2\n", "text/csv")},
    )
    assert response.status_code == 400
    assert "Activity Type" in response.json()["detail"]


def test_progress_entry_roundtrip(client):
    response = client.post("/api/progress/entry", json={"entry_date": "2026-07-04", "two_mile_seconds": 1104})
    assert response.status_code == 200
    assert response.json()["message"] == "Progress entry saved."
    entries = client.get("/api/progress/entries").json()["entries"]
    assert entries[0]["two_mile_seconds"] == 1104


def test_legacy_acft_entry_roundtrip_still_works(client):
    response = client.post("/api/acft/entry", json={"entry_date": "2026-07-04", "two_mile_seconds": 1104})
    assert response.status_code == 200
    entries = client.get("/api/acft/entries").json()["entries"]
    assert entries[0]["two_mile_seconds"] == 1104


def test_training_projection_endpoint(client):
    response = client.get("/api/training/projection")
    assert response.status_code == 200
    assert "recommendation" in response.json()


def test_coach_works_without_openai_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/api/coach/ask", json={"question": "What should I run tomorrow?"})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "built_in_fallback"
    assert body["answer"]


def test_token_protection_when_configured(client, monkeypatch):
    monkeypatch.setenv("APP_SECRET_TOKEN", "test-token")
    assert client.get("/api/summary/latest").status_code == 401
    assert client.get("/api/summary/latest", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.get("/api/summary/latest", headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_activity_category_filter_includes_strength(client):
    csv_data = b"Activity Type,Date,Title,Distance,Time,Avg HR\nStrength Training,2026-07-04,Upper Body Lift,,00:45:00,118\nCycling,2026-07-05,Easy Bike,8.0,00:35:00,132\n"
    response = client.post(
        "/api/upload/garmin-csv",
        files={"file": ("mixed.csv", csv_data, "text/csv")},
    )
    assert response.status_code == 200

    summary = client.get("/api/summary/latest").json()
    assert summary["recent_strength_sessions"] == 1
    assert summary["recent_cardio_sessions"] == 1

    strength = client.get("/api/activities?category=strength").json()["activities"]
    assert len(strength) == 1
    assert strength[0]["activity_type"] == "Strength Training"


def test_multi_file_upload_endpoint(client):
    import io
    import zipfile
    from datetime import datetime, timezone

    from tests.fit_fixture import make_fit_bytes

    fit_bytes = make_fit_bytes(
        start_utc=datetime(2026, 7, 4, 12, 5, tzinfo=timezone.utc), utc_offset_hours=-4
    )
    # Same run as fit_bytes, as a CSV row (local time 08:05 at UTC-4).
    matching_csv = (
        b"Activity Type,Date,Title,Distance,Time,Avg HR,Avg Pace\n"
        b"Running,2026-07-04 08:05:12,Two Mile,2.00,00:18:24,171,09:12\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other_activity.fit", make_fit_bytes(
            start_utc=datetime(2026, 7, 2, 22, 25, tzinfo=timezone.utc),
            sport="cycling", distance_meters=16093.4, timer_seconds=2400,
        ))

    response = client.post(
        "/api/upload/garmin",
        files=[
            ("files", ("export.csv", matching_csv, "text/csv")),
            ("files", ("run.fit", fit_bytes, "application/octet-stream")),
            ("files", ("original.zip", buffer.getvalue(), "application/zip")),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    # CSV run and FIT run are the same workout, so one of them merges.
    assert body["inserted"] == 2
    assert body["merged_duplicates"] == 1
    assert all(f["status"] == "ok" for f in body["files"])


def test_multi_file_upload_reports_partial_failures(client):
    response = client.post(
        "/api/upload/garmin",
        files=[
            ("files", ("export.csv", SAMPLE_CSV, "text/csv")),
            ("files", ("junk.xyz", b"garbage", "application/octet-stream")),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    statuses = {f["filename"]: f["status"] for f in body["files"]}
    assert statuses["export.csv"] == "ok"
    assert statuses["junk.xyz"] == "error"
    assert "couldn't be read" in body["message"]


def test_multi_file_upload_all_bad_files_is_400(client):
    response = client.post(
        "/api/upload/garmin",
        files=[("files", ("junk.xyz", b"garbage", "application/octet-stream"))],
    )
    assert response.status_code == 400
