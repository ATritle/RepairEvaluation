from typing import Optional

from pydantic import BaseModel, Field


class Annotation(BaseModel):
    symbol: str = "arrow_up"
    x: float = 0.5
    y: float = 0.5
    size: int = 100


class Photo(BaseModel):
    file: str
    name: str = ""
    description: str = ""
    rotation: int = 0
    annotations: list[Annotation] = Field(default_factory=list)


class Report(BaseModel):
    id: Optional[str] = None
    date: str = ""
    repair_no: str = ""
    technician: str = ""
    customer: str = ""
    customer_contact: str = ""
    customer_email: str = ""
    model: str = ""
    serial: str = ""
    customer_po: str = ""
    material: str = ""
    customer_request: str = ""
    received_condition: str = ""
    findings: str = ""
    photos: list[Photo] = Field(default_factory=list)
    updated_at: Optional[str] = None


class ReportSummary(BaseModel):
    id: str
    repair_no: str
    customer: str
    date: str
    technician: str
    photo_count: int
    updated_at: Optional[str] = None


class UploadedPhoto(BaseModel):
    file: str
    name: str
