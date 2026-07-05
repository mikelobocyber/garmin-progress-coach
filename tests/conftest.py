import pytest


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point the app at a throwaway SQLite file so tests never touch data/."""
    db_file = tmp_path / "test.sqlite3"
    monkeypatch.setenv("GARMIN_AI_COACH_DB", str(db_file))
    from app.database import init_db

    init_db()
    return db_file
