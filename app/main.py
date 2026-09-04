"""FastAPI entry point for the IFP Repair Evaluation web app.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 6969
or:   python -m app.main

Storage: Forge.RepairEval (see sql/001_repaireval_schema.sql). Photo bytes live
in Forge too; data/photos is only a local cache.
"""
import asyncio
import re
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import forge, p21
from .config import (
    ALLOWED_IMAGE_EXT,
    APP_NAME,
    APP_VERSION,
    ASSETS,
    STATIC,
    SYMBOLS,
    TECHNICIANS,
    ensure_dirs,
)
from .images import cache_photo, make_thumbnail, optimize_uploaded_bytes, photo_path
from .pdf_builder import build_pdf
from .schemas import PHOTO_FILE_RE, Report, ReportSummary, RevisionSummary, UploadedPhoto, clean_text

ensure_dirs()

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")


def _who(request: Request) -> Optional[str]:
    """Best available identity for saved_by until the app has real auth."""
    for header in ("x-forwarded-user", "remote-user"):
        if request.headers.get(header):
            return clean_text(request.headers[header], 100) or None
    return request.client.host if request.client else None


_REPAIR_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/\-]{0,49}$")


def _check_repair_no(repair_no: str) -> str:
    repair_no = clean_text(repair_no, 50)
    if not _REPAIR_NO_RE.fullmatch(repair_no):
        raise HTTPException(status_code=400, detail="Repair # may only contain letters, digits, space, . _ / -")
    return repair_no


def _forge_error(exc: Exception) -> HTTPException:
    if isinstance(exc, forge.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, forge.ForgeUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Storage error: {exc}")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/mobile", include_in_schema=False)
async def mobile_page() -> FileResponse:
    """Phone-friendly capture page: repair number + camera, straight into the library."""
    return FileResponse(STATIC / "mobile.html")


@app.get("/api/config")
async def get_config() -> dict:
    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "technicians": TECHNICIANS,
        "symbols": SYMBOLS,
    }


@app.get("/api/storage/status")
async def api_storage_status() -> dict:
    try:
        return {"available": True, **(await forge.ping())}
    except forge.ForgeUnavailable as exc:
        return {"available": False, "reason": str(exc)}
    except Exception as exc:  # schema missing etc.
        return {"available": False, "reason": str(exc)[:200]}


# --------------------------------------------------------------------------
# Evaluations (one per repair number, revision per save)
# --------------------------------------------------------------------------
@app.get("/api/evaluations", response_model=list[ReportSummary])
async def api_list_evaluations(
    q: str = Query("", max_length=100), limit: int = Query(200, ge=1, le=500)
) -> list[ReportSummary]:
    try:
        q = q.strip()
        rows = await (forge.search_evaluations(q, limit) if q else forge.list_evaluations(limit))
        return [ReportSummary(**r) for r in rows]
    except Exception as exc:
        raise _forge_error(exc) from exc


@app.get("/api/evaluations/{repair_no}", response_model=Report)
async def api_get_evaluation(repair_no: str, revision: Optional[int] = Query(None, ge=1)) -> Report:
    try:
        return Report(**(await forge.load_evaluation(repair_no, revision)))
    except Exception as exc:
        raise _forge_error(exc) from exc


@app.get("/api/evaluations/{repair_no}/revisions", response_model=list[RevisionSummary])
async def api_list_revisions(repair_no: str) -> list[RevisionSummary]:
    try:
        return [RevisionSummary(**r) for r in await forge.list_revisions(repair_no)]
    except Exception as exc:
        raise _forge_error(exc) from exc


@app.post("/api/evaluations", response_model=Report)
async def api_save_evaluation(report: Report, request: Request) -> Report:
    """Save = append a new revision for this repair number."""
    if not report.repair_no.strip():
        raise HTTPException(status_code=400, detail="Repair # is required to save")
    report.repair_no = _check_repair_no(report.repair_no)
    try:
        for photo in report.photos:
            if not photo_path(photo.file).exists() and not await forge.photo_exists(photo.file):
                raise HTTPException(status_code=400, detail=f"Photo missing on server: {photo.file}")
        saved = await forge.save_evaluation(report.model_dump(), _who(request))
        return Report(**saved)
    except HTTPException:
        raise
    except Exception as exc:
        raise _forge_error(exc) from exc


@app.delete("/api/evaluations/{repair_no}")
async def api_delete_evaluation(repair_no: str) -> JSONResponse:
    """Delete an evaluation and every revision of it."""
    try:
        if not await forge.delete_evaluation(repair_no):
            raise HTTPException(status_code=404, detail="Evaluation not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise _forge_error(exc) from exc
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------
# Photos (bytes in Forge, cached on local disk)
# --------------------------------------------------------------------------
async def _store_uploads(files: list[UploadFile], who: Optional[str], repair_no: Optional[str],
                         source: str) -> list[UploadedPhoto]:
    """Normalise each upload, store it in Forge and, when a repair number is
    given, register it in that repair's photo library."""
    uploaded: list[UploadedPhoto] = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_IMAGE_EXT:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {f.filename}")
        raw = await f.read()
        try:
            name, jpeg, w, h = optimize_uploaded_bytes(raw)
        except Exception as exc:  # corrupt / unreadable image
            raise HTTPException(status_code=400, detail=f"Unable to read {f.filename}: {exc}") from exc
        display = clean_text(Path(f.filename or name).name, 260) or name
        try:
            await forge.photo_put(name, display, jpeg, w, h, who)
            if repair_no:
                await forge.library_add(repair_no, name, display, source, who)
        except Exception as exc:
            raise _forge_error(exc) from exc
        cache_photo(name, jpeg)
        uploaded.append(UploadedPhoto(file=name, name=display))
    return uploaded


@app.post("/api/photos", response_model=list[UploadedPhoto])
async def api_upload_photos(
    request: Request, files: list[UploadFile] = File(...), repair_no: str = Form("")
) -> list[UploadedPhoto]:
    """Desktop upload. If the form already has a Repair #, the photos also land in its library."""
    rn = _check_repair_no(repair_no) if repair_no.strip() else None
    return await _store_uploads(files, _who(request), rn, "web")


# --------------------------------------------------------------------------
# Photo library per repair number (+ mobile capture)
# --------------------------------------------------------------------------
@app.post("/api/mobile/photos", response_model=list[UploadedPhoto])
async def api_mobile_upload(
    request: Request, repair_no: str = Form(...), files: list[UploadFile] = File(...)
) -> list[UploadedPhoto]:
    """Phone capture: repair number + one or more photos -> library."""
    rn = _check_repair_no(repair_no)
    return await _store_uploads(files, _who(request), rn, "mobile")


@app.get("/api/repairs/{repair_no}/photos")
async def api_library_list(repair_no: str) -> list[dict]:
    rn = _check_repair_no(repair_no)
    try:
        return await forge.library_list(rn)
    except Exception as exc:
        raise _forge_error(exc) from exc


@app.delete("/api/repairs/{repair_no}/photos/{file_name}")
async def api_library_remove(repair_no: str, file_name: str) -> JSONResponse:
    """Remove a photo from the repair's library (soft delete). Revisions that use it are untouched."""
    rn = _check_repair_no(repair_no)
    if not PHOTO_FILE_RE.fullmatch(file_name.lower()):
        raise HTTPException(status_code=404, detail="Photo not found")
    try:
        if not await forge.library_remove(rn, file_name.lower()):
            raise HTTPException(status_code=404, detail="Photo not in library")
    except HTTPException:
        raise
    except Exception as exc:
        raise _forge_error(exc) from exc
    return JSONResponse({"ok": True})


@app.get("/api/repairs/recent")
async def api_recent_repairs(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    try:
        return await forge.library_recent_repairs(limit)
    except Exception as exc:
        raise _forge_error(exc) from exc


async def _ensure_cached(file_name: str) -> Optional[Path]:
    p = photo_path(file_name)
    if p.exists():
        return p
    content = await forge.photo_get(Path(file_name).name)
    if content is None:
        return None
    return cache_photo(file_name, content)


@app.get("/photos/{file_name}", include_in_schema=False)
async def api_photo(file_name: str, thumb: bool = False) -> FileResponse:
    """Serve a stored photo (or a small thumbnail with ?thumb=1) from the local cache."""
    if not PHOTO_FILE_RE.fullmatch(file_name.lower()):
        raise HTTPException(status_code=404, detail="Photo not found")
    try:
        p = await _ensure_cached(file_name)
    except Exception as exc:
        raise _forge_error(exc) from exc
    if p is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    if thumb:
        try:
            p = await asyncio.to_thread(make_thumbnail, file_name)
        except Exception:
            pass  # fall back to the full image
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
async def _pdf_response(report: Report, download: bool) -> Response:
    data = report.model_dump()
    for photo in report.photos:
        try:
            await _ensure_cached(photo.file)
        except Exception as exc:
            raise _forge_error(exc) from exc
    with tempfile.TemporaryDirectory(prefix="ifp_repair_out_") as tmp:
        out = Path(tmp) / "report.pdf"
        try:
            build_pdf(data, out)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Unable to create PDF: {exc}") from exc
        pdf_bytes = out.read_bytes()

    filename = (report.repair_no.strip() or "RepairEvaluation") + ".pdf"
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@app.post("/api/pdf")
async def api_pdf(report: Report, download: bool = False) -> Response:
    """Build a PDF from the report currently in the browser (unsaved data allowed)."""
    return await _pdf_response(report, download)


@app.get("/api/evaluations/{repair_no}/pdf")
async def api_evaluation_pdf(
    repair_no: str, revision: Optional[int] = Query(None, ge=1), download: bool = False
) -> Response:
    try:
        report = Report(**(await forge.load_evaluation(repair_no, revision)))
    except Exception as exc:
        raise _forge_error(exc) from exc
    return await _pdf_response(report, download)


# --------------------------------------------------------------------------
# Prophet 21 lookups (read-only)
# --------------------------------------------------------------------------
@app.get("/api/p21/status")
async def api_p21_status() -> dict:
    try:
        info = await p21.ping()
        return {"available": True, **info}
    except p21.P21Unavailable as exc:
        return {"available": False, "reason": str(exc)}


@app.get("/api/p21/customers")
async def api_p21_customers(
    q: str = Query("", min_length=0, max_length=100), limit: int = Query(25, ge=1, le=100)
) -> list[dict]:
    q = q.strip()
    if len(q) < 2:
        return []
    try:
        return await p21.search_customers(q, limit)
    except p21.P21Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/p21/customers/{customer_id}/contacts")
async def api_p21_contacts(customer_id: str) -> list[dict]:
    try:
        return await p21.customer_contacts(customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except p21.P21Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=6969, reload=False)
