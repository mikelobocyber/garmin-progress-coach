from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.database import insert_activities
from app.security import require_token
from app.services.garmin_parser import GarminCsvError, parse_garmin_csv

router = APIRouter(prefix="/api/upload", tags=["upload"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # Garmin activity exports are tiny; 10 MB is generous.


@router.post("/garmin-csv")
async def upload_garmin_csv(file: UploadFile = File(...), _: None = Depends(require_token)):
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="That doesn't look like a CSV file. Export activities from Garmin Connect as CSV. (FIT/TCX/GPX support is planned.)")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB. Garmin activity CSV exports are normally well under that — check you exported the right file.")

    try:
        activities = parse_garmin_csv(content, filename=filename)
    except GarminCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not activities:
        raise HTTPException(status_code=400, detail="The header looks right, but no activity rows were found. Check that the export contains activities.")

    inserted, skipped = insert_activities(activities)
    return {
        "filename": filename,
        "parsed": len(activities),
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "message": f"Imported {inserted} activities. Skipped {skipped} duplicates.",
    }
