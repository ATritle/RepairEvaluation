"""FastAPI entry point for the IFP Repair Evaluation web app.

Run:  .venv\\Scripts\\python -m uvicorn app.main:app --host 0.0.0.0 --port 6969
or:   python -m app.main

Storage: report data in Forge.RepairEval (sql/*.sql); photos in the repair's
drawing folder on the N drive (app/photos.py). Sign-in: Windows AD (app/auth.py).
"""
import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, forge, p21, photos
from .config import (
    ALLOWED_IMAGE_EXT,
    APP_NAME,
    APP_VERSION,
    ASSETS,
    COLORS,
    STATIC,
    SYMBOLS,
    TECHNICIANS,
    ensure_dirs,
)
from .pdf_builder import build_pdf
from .schemas import LibraryPhoto, Report, ReportSummary, RevisionSummary, UploadedPhoto, clean_text
from .settings import get_settings

log = logging.getLogger("repaireval")
ensure_dirs()

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")


@app.middleware("http")
async def lowercase_page_paths(request: Request, call_next):
    """Windows users type /Mobile or /R/36169; route matching is case-sensitive,
    so lower-case the first path segment for the page routes. API and file paths
    are left alone (repair numbers are normalised separately)."""
    path = request.scope.get("path", "")
    first = path.split("/", 2)[1].lower() if path.count("/") >= 1 else ""
    if first in ("mobile", "r", "health", "logout", "static", "assets") and not path.startswith("/" + first):
        request.scope["path"] = "/" + first + path[len(first) + 1:]
        request.scope["raw_path"] = request.scope["path"].encode()
    return await call_next(request)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    """Pages and our own JS/CSS must revalidate on every load so a deploy is
    picked up immediately (phones cache aggressively when no header is sent).
    Logos may be cached; photos set their own header."""
    response = await call_next(request)
    path = request.url.path
    if "cache-control" not in response.headers:
        if path.startswith("/static/") or response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=86400"
    return response


def _page(name: str) -> FileResponse:
    return FileResponse(STATIC / name, headers={"Cache-Control": "no-cache"})


# Windows AD sign-in + group gate + /health, /api/me, /logout. Added after the
# cache middleware above so it wraps everything (middleware runs outermost-last-added).
auth.install(app)


def _who(request: Request, declared: Optional[str] = None) -> Optional[str]:
    """Identity recorded on saved_by / uploaded_by.

    Precedence: the signed-in Windows account ('jsmith (John Smith)') >
    a user header from an authenticating proxy > the technician picked in the
    UI (self-declared, must be on the configured list, kept with the client
    address so it is still traceable) > the client address."""
    signed_in = auth.identity_label(request)
    if signed_in:
        return clean_text(signed_in, 100)
    for header in ("x-forwarded-user", "remote-user"):
        if request.headers.get(header):
            return clean_text(request.headers[header], 100) or None
    ip = request.client.host if request.client else ""
    name = clean_text(declared, 100)
    if name and name.upper() in {t.upper() for t in TECHNICIANS}:
        return f"{name.upper()} @{ip}"[:100] if ip else name.upper()
    return ip or None


_REPAIR_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/\-]{0,49}$")


def _check_repair_no(repair_no: str) -> str:
    """Validate and normalise a repair number: upper-cased, and a bare number
    gets its R prefix, so the phone page, the desktop form and the API all
    agree on the key."""
    repair_no = clean_text(repair_no, 50).upper()
    if re.fullmatch(r"\d{4,7}", repair_no):
        repair_no = "R" + repair_no          # "36169" -> "R36169"
    if not _REPAIR_NO_RE.fullmatch(repair_no):
        raise HTTPException(status_code=400, detail="Repair # may only contain letters, digits, space, . _ / -")
    return repair_no


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, photos.PhotoLocationError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, photos.PhotoNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, forge.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, forge.ForgeUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    log.exception("unexpected error")
    return HTTPException(status_code=500, detail=f"Server error: {exc}")


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return _page("index.html")


@app.get("/r/{repair_no}", include_in_schema=False)
@app.get("/r/{repair_no}/latest", include_in_schema=False)
@app.get("/r/{repair_no}/v{revision:int}", include_in_schema=False)
async def deep_link(repair_no: str, revision: Optional[int] = None) -> FileResponse:
    """Deep links into the form: /r/R123456 (latest), /r/R123456/v2."""
    return _page("index.html")


@app.get("/mobile", include_in_schema=False)
@app.get("/mobile/{repair_no}", include_in_schema=False)
async def mobile_page(repair_no: Optional[str] = None) -> FileResponse:
    """Phone capture page. /mobile/R123456 opens pre-filled; the address follows the field."""
    return _page("mobile.html")


@app.get("/api/config")
async def get_config() -> dict:
    return {"app_name": APP_NAME, "version": APP_VERSION, "technicians": TECHNICIANS, "symbols": SYMBOLS, "colors": COLORS}


@app.get("/api/storage/status")
async def api_storage_status() -> dict:
    try:
        return {"available": True, **(await forge.ping()), "photo_root": str(photos.fs_root())}
    except forge.ForgeUnavailable as exc:
        return {"available": False, "reason": str(exc)}
    except Exception as exc:  # schema missing etc.
        return {"available": False, "reason": str(exc)[:200]}


# --------------------------------------------------------------------------
# Evaluations (one per repair number, revision per save)
# --------------------------------------------------------------------------
@app.get("/api/evaluations", response_model=list[ReportSummary])
async def api_list_evaluations(
    q: str = Query("", max_length=100), limit: int = Query(200, ge=1, le=500), include_deleted: bool = False
) -> list[ReportSummary]:
    try:
        q = q.strip()
        rows = await (forge.search_evaluations(q, limit, include_deleted) if q else forge.list_evaluations(limit, include_deleted))
        return [ReportSummary(**r) for r in rows]
    except Exception as exc:
        raise _error(exc) from exc


async def _load(repair_no: str, revision: Optional[int]) -> Report:
    try:
        return Report(**(await forge.load_evaluation(_check_repair_no(repair_no), revision)))
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/evaluations/{repair_no}", response_model=Report)
async def api_get_evaluation(repair_no: str, revision: Optional[int] = Query(None, ge=1)) -> Report:
    """Latest revision by default; ?revision=n still accepted for compatibility."""
    return await _load(repair_no, revision)


@app.get("/api/evaluations/{repair_no}/latest", response_model=Report)
async def api_get_latest(repair_no: str) -> Report:
    return await _load(repair_no, None)


@app.get("/api/evaluations/{repair_no}/v{revision}", response_model=Report)
async def api_get_revision(repair_no: str, revision: int) -> Report:
    """A specific revision: /api/evaluations/R123456/v2"""
    if revision < 1:
        raise HTTPException(status_code=404, detail="Revision numbers start at 1")
    return await _load(repair_no, revision)


@app.get("/api/evaluations/{repair_no}/revisions", response_model=list[RevisionSummary])
async def api_list_revisions(repair_no: str) -> list[RevisionSummary]:
    try:
        return [RevisionSummary(**r) for r in await forge.list_revisions(_check_repair_no(repair_no))]
    except Exception as exc:
        raise _error(exc) from exc


async def _freeze_photos(repair_no: str, report: Report) -> list[dict]:
    """Turn the report's photo references into immutable snapshots.

    live:<name>    -> normalise + hash + copy into Photos\\.archive (idempotent)
    archive:<sha>  -> already frozen; verify the snapshot still exists"""
    out: list[dict] = []
    for p in report.photos:
        kind, _, val = p.ref.partition(":")
        try:
            if kind == "live":
                sha, rel = await photos.archive_live(repair_no, val)
                source_name = p.name or val
            else:
                path = await photos.path_for_ref(repair_no, p.ref)
                sha, rel = val, photos.rel_to_root(path)
                source_name = p.name
        except photos.PhotoNotFound as exc:
            raise HTTPException(status_code=400, detail=f"Photo '{p.name or val}': {exc}") from exc
        out.append({
            "sha256": sha, "archive_path": rel, "source_name": source_name,
            "description": p.description, "rotation": p.rotation,
            "annotations": [a.model_dump() for a in p.annotations],
        })
    return out


async def _write_report_pdf(report: Report) -> None:
    """Drop '<R> rev<N>.pdf' into the job's Reports folder. Failure is logged, never fatal."""
    try:
        pdf = await _render_pdf(report)
        d = await photos.reports_dir(report.repair_no)
        target = d / f"{report.repair_no} rev{report.revision_no}.pdf"
        await asyncio.to_thread(target.write_bytes, pdf)
    except Exception as exc:
        log.warning("could not write report PDF for %s rev %s: %s", report.repair_no, report.revision_no, exc)


@app.post("/api/evaluations", response_model=Report)
async def api_save_evaluation(report: Report, request: Request) -> Report:
    """Save = append a new revision. Photos referenced as live files are frozen
    into the archive first. 409 if someone saved since base_revision_no (unless force)."""
    if not report.repair_no.strip():
        raise HTTPException(status_code=400, detail="Repair # is required to save")
    report.repair_no = _check_repair_no(report.repair_no)
    try:
        if report.photos:
            await photos.photos_dir_checked(report.repair_no)     # folder must exist before we freeze anything
        snapshots = await _freeze_photos(report.repair_no, report)
        saved = await forge.save_evaluation(report.model_dump(), _who(request, report.technician), snapshots,
                                            report.base_revision_no, report.force)
    except forge.StaleSave as exc:
        raise HTTPException(status_code=409, detail={
            "stale": True, "current_revision_no": exc.current_revision_no,
            "saved_at": exc.saved_at, "saved_by": exc.saved_by,
            "message": f"Revision {exc.current_revision_no} was saved by {exc.saved_by or 'someone else'} while you were editing.",
        }) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc
    result = Report(**saved)
    asyncio.create_task(_write_report_pdf(result))
    return result


@app.delete("/api/evaluations/{repair_no}")
async def api_delete_evaluation(repair_no: str, request: Request) -> JSONResponse:
    """Soft delete: hidden from lists and lookups, all revisions kept, restorable."""
    try:
        if not await forge.soft_delete_evaluation(_check_repair_no(repair_no), _who(request)):
            raise HTTPException(status_code=404, detail="Evaluation not found or already deleted")
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc
    return JSONResponse({"ok": True})


@app.post("/api/evaluations/{repair_no}/restore")
async def api_restore_evaluation(repair_no: str) -> JSONResponse:
    try:
        if not await forge.restore_evaluation(_check_repair_no(repair_no)):
            raise HTTPException(status_code=404, detail="Evaluation not found or not deleted")
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------
# Photos: the repair's Photos folder is the library
# --------------------------------------------------------------------------
@app.get("/api/repairs/recent")
async def api_recent_repairs(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    try:
        return await forge.recent_repairs(limit)
    except Exception as exc:
        raise _error(exc) from exc


@app.get("/api/repairs/{repair_no}/folder")
async def api_repair_folder(repair_no: str) -> dict:
    """Where photos for this repair live, and whether the job folder exists."""
    rn = _check_repair_no(repair_no)
    try:
        p = await photos.photos_dir_checked(rn)
        return {"ok": True, "repair_no": rn, "location": str(p)}
    except photos.PhotoLocationError as exc:
        return {"ok": False, "repair_no": rn, "reason": str(exc)}


@app.get("/api/repairs/{repair_no}/photos", response_model=list[LibraryPhoto])
async def api_library_list(repair_no: str) -> list[LibraryPhoto]:
    """Everything in <job>\\Photos, newest first, flagged if already on the latest report."""
    rn = _check_repair_no(repair_no)
    try:
        items, on_report = await asyncio.gather(photos.list_library(rn), forge.latest_snapshot_hashes(rn))
    except photos.PhotoLocationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except forge.ForgeUnavailable:
        items, on_report = await photos.list_library(rn), set()
    except Exception as exc:
        raise _error(exc) from exc
    return [
        LibraryPhoto(ref=f"live:{i.name}", name=i.name, size=i.size, modified=i.modified, sha256=i.sha256,
                     width=i.width, height=i.height, in_latest=bool(i.sha256 and i.sha256 in on_report))
        for i in items
    ]


async def _store_uploads(repair_no: str, files: list[UploadFile]) -> list[UploadedPhoto]:
    """Normalise each upload and write it into the repair's Photos folder.
    The folder is checked once first so a missing folder fails the whole batch."""
    try:
        await photos.photos_dir_checked(repair_no)
    except photos.PhotoLocationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out: list[UploadedPhoto] = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_IMAGE_EXT:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {f.filename}")
        raw = await f.read()
        try:
            name, w, h = await photos.save_upload(repair_no, f.filename or "photo.jpg", raw)
        except photos.PhotoLocationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:  # corrupt / unreadable image
            raise HTTPException(status_code=400, detail=f"Unable to read {f.filename}: {exc}") from exc
        out.append(UploadedPhoto(ref=f"live:{name}", name=name, width=w, height=h))
    return out


@app.post("/api/photos", response_model=list[UploadedPhoto])
async def api_upload_photos(request: Request, files: list[UploadFile] = File(...), repair_no: str = Form("")) -> list[UploadedPhoto]:
    """Desktop upload into the Repair #'s Photos folder."""
    if not repair_no.strip():
        raise HTTPException(status_code=400, detail="Enter the Repair # before adding photos")
    return await _store_uploads(_check_repair_no(repair_no), files)


@app.post("/api/mobile/photos", response_model=list[UploadedPhoto])
async def api_mobile_upload(
    request: Request, repair_no: str = Form(...), files: list[UploadFile] = File(...), uploaded_by: str = Form("")
) -> list[UploadedPhoto]:
    """Phone capture: repair number + photos -> the repair's Photos folder."""
    rn = _check_repair_no(repair_no)
    if not auth.current_login(request) and not clean_text(uploaded_by, 100):
        raise HTTPException(status_code=400, detail="Pick who you are before uploading")
    result = await _store_uploads(rn, files)
    log.info("mobile upload %s: %d photo(s) by %s", rn, len(result), _who(request, uploaded_by))
    return result


@app.delete("/api/repairs/{repair_no}/photos/{name}")
async def api_library_remove(repair_no: str, name: str) -> JSONResponse:
    """Remove a photo from the library: moved into Photos\\.removed, never deleted.
    Saved revisions are untouched (they use archived snapshots)."""
    rn = _check_repair_no(repair_no)
    try:
        await photos.remove_live(rn, name)
    except Exception as exc:
        raise _error(exc) from exc
    return JSONResponse({"ok": True})


async def _serve(repair_no: str, ref: str, thumb: bool) -> FileResponse:
    rn = _check_repair_no(repair_no)
    try:
        p = await photos.path_for_ref(rn, ref)
        if thumb:
            p = await photos.thumb_for(p)
    except Exception as exc:
        raise _error(exc) from exc
    headers = {"Cache-Control": "private, max-age=31536000, immutable" if ref.startswith("archive:") else "private, no-cache"}
    return FileResponse(p, media_type="image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else None, headers=headers)


@app.get("/repairs/{repair_no}/photos/{name}", include_in_schema=False)
async def serve_live_photo(repair_no: str, name: str, thumb: bool = False) -> FileResponse:
    return await _serve(repair_no, f"live:{name}", thumb)


@app.get("/repairs/{repair_no}/archive/{sha}", include_in_schema=False)
async def serve_archived_photo(repair_no: str, sha: str, thumb: bool = False) -> FileResponse:
    return await _serve(repair_no, f"archive:{sha.lower()}", thumb)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
async def _render_pdf(report: Report) -> bytes:
    data = report.model_dump()
    rn = _check_repair_no(report.repair_no) if report.repair_no.strip() else ""
    for photo in data["photos"]:
        try:
            photo["local_path"] = str(await photos.path_for_ref(rn, photo["ref"])) if rn else ""
        except Exception:
            photo["local_path"] = ""            # "Image unavailable" in the PDF
    with tempfile.TemporaryDirectory(prefix="ifp_repair_out_") as tmp:
        out = Path(tmp) / "report.pdf"
        await asyncio.to_thread(build_pdf, data, out)
        return out.read_bytes()


async def _pdf_response(report: Report, download: bool) -> Response:
    try:
        pdf_bytes = await _render_pdf(report)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to create PDF: {exc}") from exc
    filename = (report.repair_no.strip() or "RepairEvaluation") + (f" rev{report.revision_no}" if report.revision_no else "") + ".pdf"
    disposition = "attachment" if download else "inline"
    return Response(content=pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    })


@app.post("/api/pdf")
async def api_pdf(report: Report, download: bool = False) -> Response:
    """Build a PDF from the report currently in the browser (unsaved data allowed)."""
    return await _pdf_response(report, download)


@app.get("/api/evaluations/{repair_no}/pdf")
@app.get("/api/evaluations/{repair_no}/latest/pdf")
async def api_evaluation_pdf(repair_no: str, revision: Optional[int] = Query(None, ge=1), download: bool = False) -> Response:
    """PDF of the latest revision (or ?revision=n). Add ?download=1 for an attachment."""
    return await _pdf_response(await _load(repair_no, revision), download)


@app.get("/api/evaluations/{repair_no}/v{revision}/pdf")
async def api_revision_pdf(repair_no: str, revision: int, download: bool = False) -> Response:
    if revision < 1:
        raise HTTPException(status_code=404, detail="Revision numbers start at 1")
    return await _pdf_response(await _load(repair_no, revision), download)


# --------------------------------------------------------------------------
# Prophet 21 lookups (read-only)
# --------------------------------------------------------------------------
@app.get("/api/p21/status")
async def api_p21_status() -> dict:
    try:
        return {"available": True, **(await p21.ping())}
    except p21.P21Unavailable as exc:
        return {"available": False, "reason": str(exc)}


@app.get("/api/p21/customers")
async def api_p21_customers(q: str = Query("", min_length=0, max_length=100), limit: int = Query(25, ge=1, le=100)) -> list[dict]:
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
