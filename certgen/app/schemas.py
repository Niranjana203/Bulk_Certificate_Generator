from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from .config import settings


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200, examples=["Python Bootcamp 2026"])
    issuer: str = Field(min_length=1, max_length=200, examples=["Acme Academy"])
    issue_date: date = Field(default_factory=date.today)
    # Kept as loose dicts on purpose: each recipient is validated individually
    # in the service layer, so one bad row doesn't reject the whole request.
    recipients: list[Any] = Field(min_length=1, max_length=settings.max_recipients)


class CertificateOut(BaseModel):
    id: str
    row_index: int
    recipient_name: str | None
    recipient_email: str | None
    status: str
    error: str | None
    download_url: str | None = None


class JobSummary(BaseModel):
    id: str
    title: str
    issuer: str
    issue_date: date
    status: str
    total: int
    succeeded: int
    failed: int
    pending: int
    progress_percent: float
    created_at: datetime
    completed_at: datetime | None
    status_url: str
    download_all_url: str | None = None


class JobDetail(JobSummary):
    certificates: list[CertificateOut]
