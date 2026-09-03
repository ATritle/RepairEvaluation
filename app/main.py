"""FastAPI entry point for the IFP Repair Evaluation web app.

Run:  uvicorn app.main:app --reload --port 8000
or:   python -m app.main
"""
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import storage
from .config import (
    ALLOWED_IMAGE_EXT,
    APP_NAME,
    APP_VERSION,
    ASSETS,
    PHOTOS_DIR,
    STATIC,
    SYMBOLS,
    TECHNICIANS,
    ensure_dirs,
)
from .images import optimize_uploaded_bytes, photo_path
from .pdf_builder import build_pdf
from .schemas import Report, ReportSummary, UploadedPhoto

ensure_dirs()

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")
app.mount("/photos", StaticFiles(directory=str(PHOTOS_DIR)), name="photos")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
async def get_config() -> dict:
    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "technicians": TECHNICIANS,
        "symbols": SYMBOLS,
    }


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@app.get("/api/reports", response_model=list[ReportSummary])
async def api_list_reports() -> list[ReportSummary]:
    return storage.list_reports()


@app.get("/api/reports/{report_id}", response_model=Report)
async def api_get_report(report_id: str) -> Report:
    report = storage.load_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@app.post("/api/reports", response_model=Report)
async def api_save_report(report: Report) -> Report:
    for photo in report.photos:
        if not photo_path(photo.file).exists():
            raise HTTPException(status_code=400, detail=f"Photo missing on server: {photo.file}")
    return storage.save_report(report)


@app.delete("/api/reports/{report_id}")
async def api_delete_report(report_id: str) -> JSONResponse:
    if not storage.delete_report(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------
# Photos
# --------------------------------------------------------------------------
@app.post("/api/photos", response_model=list[UploadedPhoto])
async def api_upload_photos(files: list[UploadFile] = File(...)) -> list[UploadedPhoto]:
    uploaded: list[UploadedPhoto] = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_IMAGE_EXT:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {f.filename}")
        raw = await f.read()
        try:
            stored = optimize_uploaded_bytes(raw)
        except Exception as exc:  # corrupt / unreadable image
            raise HTTPException(status_code=400, detail=f"Unable to read {f.filename}: {exc}") from exc
        uploaded.append(UploadedPhoto(file=stored, name=f.filename or stored))
    return uploaded


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def _pdf_response(report: Report, download: bool) -> Response:
    data = report.model_dump()
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
    return _pdf_response(report, download)


@app.get("/api/reports/{report_id}/pdf")
async def api_report_pdf(report_id: str, download: bool = False) -> Response:
    report = storage.load_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _pdf_response(report, download)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
