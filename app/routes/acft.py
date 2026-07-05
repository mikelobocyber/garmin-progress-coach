from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.database import fetch_acft_entries, insert_acft_entry, set_setting
from app.security import require_token

router = APIRouter(tags=["progress"])


class ProgressEntry(BaseModel):
    entry_date: date = Field(default_factory=date.today)
    body_weight_lbs: Optional[float] = None
    deadlift_lbs: Optional[int] = None
    sprint_drag_carry_seconds: Optional[int] = None
    plank_seconds: Optional[int] = None
    pushups: Optional[int] = None
    two_mile_seconds: Optional[int] = None
    notes: Optional[str] = None


# Backward-compatible name for users who already saw the old API/docs.
AcftEntry = ProgressEntry


class SettingsPayload(BaseModel):
    goal_two_mile_seconds: Optional[int] = Field(default=None, ge=600, le=1800)


def _save_progress_entry(entry: ProgressEntry):
    payload = entry.model_dump()
    payload["entry_date"] = entry.entry_date.isoformat()
    entry_id = insert_acft_entry(payload)
    return {"id": entry_id, "message": "Progress entry saved."}


@router.post("/api/progress/entry", operation_id="createProgressEntry")
def create_progress_entry(entry: ProgressEntry, _: None = Depends(require_token)):
    return _save_progress_entry(entry)


@router.get("/api/progress/entries", operation_id="listProgressEntries")
def list_progress_entries(_: None = Depends(require_token)):
    return {"entries": fetch_acft_entries()}


@router.post("/api/progress/settings", operation_id="updateProgressSettings")
def update_progress_settings(payload: SettingsPayload, _: None = Depends(require_token)):
    if payload.goal_two_mile_seconds is not None:
        set_setting("goal_two_mile_seconds", str(payload.goal_two_mile_seconds))
    return {"message": "Settings updated."}


# Legacy ACFT routes kept so older Custom GPT Actions and tests do not break.
@router.post("/api/acft/entry", operation_id="createAcftEntry")
def create_entry(entry: ProgressEntry, _: None = Depends(require_token)):
    return _save_progress_entry(entry)


@router.get("/api/acft/entries", operation_id="listAcftEntries")
def list_entries(_: None = Depends(require_token)):
    return {"entries": fetch_acft_entries()}


@router.post("/api/acft/settings", operation_id="updateAcftSettings")
def update_settings(payload: SettingsPayload, _: None = Depends(require_token)):
    if payload.goal_two_mile_seconds is not None:
        set_setting("goal_two_mile_seconds", str(payload.goal_two_mile_seconds))
    return {"message": "Settings updated."}
