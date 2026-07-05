from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.database import insert_activities
from app.security import require_token
from app.services.fit_parser import GarminFitError, parse_fit, parse_fit_zip
from app.services.garmin_parser import GarminCsvError, parse_garmin_csv

router = APIRouter(prefix="/api/upload", tags=["upload"])

MAX_ACTIVITY_FILE_BYTES = 25 * 1024 * 1024
MAX_ZIP_UPLOAD_BYTES = 200 * 1024 * 1024

# FIT files are usually small, but Garmin "Export Original" archives and
# watch-folder ZIPs can legitimately be bigger. The route cap now matches the
# FIT ZIP parser's decompressed total limit instead of rejecting valid ZIPs
# before the parser can apply its member/zip-bomb guards.

FIT_MAGIC_OFFSET = 8  # bytes 8-11 of a FIT header spell ".FIT"


def _looks_like(content: bytes, kind: str) -> bool:
    if kind == "zip":
        return content[:4] == b"PK\x03\x04"
    if kind == "fit":
        return content[FIT_MAGIC_OFFSET:FIT_MAGIC_OFFSET + 4] == b".FIT"
    return False


def _parse_one(filename: str, content: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Route a single file to the right parser by extension, falling back
    to magic bytes so a FIT file saved with the wrong extension still works.
    Returns (activities, notes)."""
    lower = filename.lower()
    if lower.endswith(".csv"):
        return parse_garmin_csv(content, filename=filename), []
    if lower.endswith(".zip") or _looks_like(content, "zip"):
        return parse_fit_zip(content, filename=filename)
    if lower.endswith(".fit") or _looks_like(content, "fit"):
        activities = parse_fit(content, filename=filename)
        if not activities:
            return [], [f"{filename}: skipped (a valid FIT file, but not an activity — likely watch monitoring data)"]
        return activities, []
    raise GarminCsvError(
        f"{filename}: unsupported file type. Upload a Garmin CSV export, a .fit file, or the .zip from 'Export Original'."
    )


@router.post("/garmin")
async def upload_garmin(files: list[UploadFile] = File(...), _: None = Depends(require_token)):
    """Import one or more Garmin files: activity CSV exports, raw .fit
    files (e.g. copied from a watch's GARMIN/Activity folder), or the
    .zip that Garmin Connect's 'Export Original' produces."""
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    results: list[dict[str, Any]] = []
    total_inserted = 0
    total_merged = 0
    failed_files = 0

    for file in files:
        filename = file.filename or "upload"
        content = await file.read()
        is_zip = filename.lower().endswith(".zip") or _looks_like(content, "zip")
        max_bytes = MAX_ZIP_UPLOAD_BYTES if is_zip else MAX_ACTIVITY_FILE_BYTES
        if len(content) > max_bytes:
            size_mb = max_bytes // (1024 * 1024)
            results.append({"filename": filename, "status": "error", "detail": f"File is larger than {size_mb} MB."})
            failed_files += 1
            continue
        try:
            activities, notes = _parse_one(filename, content)
        except (GarminCsvError, GarminFitError) as exc:
            results.append({"filename": filename, "status": "error", "detail": str(exc)})
            failed_files += 1
            continue

        inserted, merged = insert_activities(activities) if activities else (0, 0)
        total_inserted += inserted
        total_merged += merged
        results.append({
            "filename": filename,
            "status": "ok",
            "parsed": len(activities),
            "inserted": inserted,
            "merged_duplicates": merged,
            "notes": notes,
        })

    if failed_files == len(files):
        # Every file failed — surface the first error as the main message.
        raise HTTPException(status_code=400, detail=results[0]["detail"])

    parts = [f"Imported {total_inserted} activities"]
    if total_merged:
        parts.append(f"merged {total_merged} duplicates")
    if failed_files:
        parts.append(f"{failed_files} file(s) couldn't be read")
    skip_notes = sum(len(r.get("notes", [])) for r in results if r["status"] == "ok")
    if skip_notes:
        parts.append(f"{skip_notes} non-activity file(s) skipped")

    return {
        "files": results,
        "inserted": total_inserted,
        "merged_duplicates": total_merged,
        # Legacy key so older frontends/GPT Actions keep working.
        "skipped_duplicates": total_merged,
        "message": ", ".join(parts) + ".",
    }


# Legacy single-CSV endpoint, kept so existing Custom GPT Actions and older
# frontends don't break. New clients should use POST /api/upload/garmin.
@router.post("/garmin-csv")
async def upload_garmin_csv(file: UploadFile = File(...), _: None = Depends(require_token)):
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="This endpoint accepts CSV only. Use POST /api/upload/garmin for .fit and .zip files.")

    content = await file.read()
    if len(content) > MAX_ACTIVITY_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB. Garmin activity CSV exports are normally well under that — check you exported the right file.")

    try:
        activities = parse_garmin_csv(content, filename=filename)
    except GarminCsvError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not activities:
        raise HTTPException(status_code=400, detail="The header looks right, but no activity rows were found. Check that the export contains activities.")

    inserted, merged = insert_activities(activities)
    return {
        "filename": filename,
        "parsed": len(activities),
        "inserted": inserted,
        "skipped_duplicates": merged,
        "message": f"Imported {inserted} activities. Skipped {merged} duplicates.",
    }
