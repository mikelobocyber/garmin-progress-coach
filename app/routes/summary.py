from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.database import fetch_activities
from app.security import require_token
from app.services.summary import activity_category, build_latest_summary, build_training_projection

router = APIRouter(prefix="/api", tags=["summary"])


@router.get("/summary/latest")
def latest_summary(_: None = Depends(require_token)):
    return build_latest_summary()


@router.get("/runs/recent")
def recent_runs(limit: int = Query(default=20, ge=1, le=100), _: None = Depends(require_token)):
    runs = fetch_activities(limit=limit, activity_type="run")
    return {"runs": runs}


@router.get("/activities")
def activities(
    limit: int = Query(default=50, ge=1, le=200),
    category: str | None = Query(default=None, description="Optional broad category such as running, strength, cardio, cycling, mobility, walking_hiking, or other."),
    _: None = Depends(require_token),
):
    items = fetch_activities(limit=limit)
    if category:
        wanted = category.strip().lower()
        items = [item for item in items if activity_category(item) == wanted]
    return {"activities": items}


@router.get("/training/projection", operation_id="trainingProjection")
def training_projection(_: None = Depends(require_token)):
    return build_training_projection()


# Backward-compatible ACFT path; the projection itself is general training-first.
@router.get("/acft/projection", operation_id="acftProjection")
def acft_projection(_: None = Depends(require_token)):
    return build_training_projection()
