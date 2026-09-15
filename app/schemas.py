"""Pydantic models = the input boundary. Everything the browser sends passes
through here before it reaches SQL, the file share or ReportLab:

- free text is scrubbed (control characters removed, whitespace trimmed,
  CRLF normalised) and length-capped to the Forge column sizes
- photo references must be 'live:<file name>' or 'archive:<sha256>'
- P21 ids must be plain digits; enumerations (symbol, colour, rotation) validated

SQL itself is always parameterised (pyodbc '?' placeholders); nothing here
is ever concatenated into a statement.
"""
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .config import COLORS as _COLORS

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PHOTO_REF_RE = re.compile(r"^(live:[^\\/:*?\"<>|\x00-\x1f]{1,200}|archive:[0-9a-f]{64})$")
COLOR_VALUES = {c["value"] for c in _COLORS}
SYMBOLS = {"arrow_up", "arrow_right", "arrow_down", "arrow_left", "circle", "square", "rectangle", "x", "check"}


def clean_text(value: Optional[str], max_len: int, multiline: bool = False) -> str:
    """Strip control characters, normalise newlines, trim and cap length."""
    if value is None:
        return ""
    s = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if not multiline:
        s = s.replace("\n", " ").replace("\t", " ")
    s = _CONTROL.sub("", s)
    s = s.strip()
    return s[:max_len]


def clean_id(value: Optional[str], max_len: int = 20) -> Optional[str]:
    """P21 ids: digits only (customer_id is DECIMAL(19,0), contacts.id is numeric text)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not re.fullmatch(r"\d{1,%d}" % max_len, s):
        raise ValueError("id must be numeric")
    return s


class Annotation(BaseModel):
    symbol: str = "arrow_up"
    x: float = Field(0.5, ge=0.0, le=1.0)
    y: float = Field(0.5, ge=0.0, le=1.0)
    size: int = Field(100, ge=25, le=300)
    color: str = "#ff0000"

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in COLOR_VALUES:
            raise ValueError(f"unknown colour {v!r}")
        return v

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in SYMBOLS:
            raise ValueError(f"unknown symbol {v!r}")
        return v


class Photo(BaseModel):
    """A photo on a report. `ref` is 'live:<name>' while editing (a file in the
    repair's Photos folder) and 'archive:<sha256>' once saved (a frozen snapshot).
    `name` is the file name shown to people."""
    ref: str
    name: str = ""
    description: str = ""
    rotation: int = 0
    annotations: list[Annotation] = Field(default_factory=list, max_length=200)

    @field_validator("ref")
    @classmethod
    def _ref(cls, v: str) -> str:
        v = (v or "").strip()
        if v.startswith("archive:"):
            v = v.lower()
        if not PHOTO_REF_RE.fullmatch(v) or v.split(":", 1)[1].startswith("."):
            raise ValueError("invalid photo reference")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return clean_text(v, 260)

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        return clean_text(v, 4000, multiline=True)

    @field_validator("rotation")
    @classmethod
    def _rotation(cls, v: int) -> int:
        v = int(v) % 360
        if v not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180 or 270")
        return v


class Report(BaseModel):
    """One revision of an evaluation, as edited in the browser."""
    repair_no: str = ""
    # Revision bookkeeping (server-assigned; ignored on save)
    revision_no: Optional[int] = None
    current_revision_no: Optional[int] = None
    saved_at: Optional[str] = None
    saved_by: Optional[str] = None
    deleted_at: Optional[str] = None
    # Stale-save protection: the revision the browser loaded (0/None = new).
    # Save is refused with 409 if someone else saved since, unless force=True.
    base_revision_no: Optional[int] = None
    force: bool = False

    date: str = ""
    technician: str = ""
    customer: str = ""
    customer_id: Optional[str] = None       # P21 customer_id when picked from P21
    customer_contact: str = ""
    contact_id: Optional[str] = None        # P21 contacts.id when picked from P21
    customer_email: str = ""
    email_override: bool = False            # user replaced the P21 email manually
    model: str = ""
    serial: str = ""
    customer_po: str = ""
    material: str = ""
    customer_request: str = ""
    findings: str = ""
    photos: list[Photo] = Field(default_factory=list, max_length=200)

    @field_validator("repair_no")
    @classmethod
    def _repair_no(cls, v: str) -> str:
        return clean_text(v, 50)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        v = clean_text(v, 10)
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("date must be YYYY-MM-DD")
        return v

    @field_validator("technician")
    @classmethod
    def _technician(cls, v: str) -> str:
        return clean_text(v, 100)

    @field_validator("customer", "customer_contact", "customer_email", "model", "serial", "material")
    @classmethod
    def _short(cls, v: str) -> str:
        return clean_text(v, 255)

    @field_validator("customer_po")
    @classmethod
    def _po(cls, v: str) -> str:
        return clean_text(v, 100)

    @field_validator("customer_request", "findings")
    @classmethod
    def _long(cls, v: str) -> str:
        return clean_text(v, 20000, multiline=True)

    @field_validator("customer_id", "contact_id")
    @classmethod
    def _ids(cls, v: Optional[str]) -> Optional[str]:
        return clean_id(v)


class ReportSummary(BaseModel):
    repair_no: str
    customer: str = ""
    date: str = ""
    technician: str = ""
    photo_count: int = 0
    revision_count: int = 0
    updated_at: Optional[str] = None
    saved_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


class RevisionSummary(BaseModel):
    revision_no: int
    saved_at: Optional[str] = None
    saved_by: Optional[str] = None
    technician: str = ""
    customer: str = ""
    date: str = ""
    photo_count: int = 0


class UploadedPhoto(BaseModel):
    ref: str
    name: str
    width: int = 0
    height: int = 0


class LibraryPhoto(BaseModel):
    ref: str
    name: str
    size: int
    modified: str
    sha256: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    in_latest: bool = False
