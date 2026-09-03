"""JSON file storage for saved evaluations (data/reports/<id>.json)."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import REPORTS_DIR
from .schemas import Report, ReportSummary


def _path(report_id: str) -> Path:
    safe = Path(report_id).name
    return REPORTS_DIR / f"{safe}.json"


def list_reports() -> list[ReportSummary]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[ReportSummary] = []
    for p in REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append(ReportSummary(
            id=data.get("id") or p.stem,
            repair_no=data.get("repair_no", ""),
            customer=data.get("customer", ""),
            date=data.get("date", ""),
            technician=data.get("technician", ""),
            photo_count=len(data.get("photos", []) or []),
            updated_at=data.get("updated_at"),
        ))
    out.sort(key=lambda r: r.updated_at or "", reverse=True)
    return out


def load_report(report_id: str) -> Optional[Report]:
    p = _path(report_id)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("id", report_id)
    return Report.model_validate(data)


def save_report(report: Report) -> Report:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if not report.id:
        report.id = uuid.uuid4().hex
    report.updated_at = datetime.now().isoformat(timespec="seconds")
    _path(report.id).write_text(
        json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def delete_report(report_id: str) -> bool:
    p = _path(report_id)
    if p.exists():
        p.unlink()
        return True
    return False
