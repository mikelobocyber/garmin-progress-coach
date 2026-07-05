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
    assert "Garmin AI Coach" in response.text


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
