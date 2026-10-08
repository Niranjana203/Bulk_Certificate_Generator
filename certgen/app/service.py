"""Business logic: validating recipients, creating jobs, processing jobs."""
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .certificate import render_certificate
from .config import settings
from .database import SessionLocal

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME_LEN = 100


def validate_recipient(raw, seen_emails: set[str]) -> tuple[dict | None, str | None]:
    """Return (clean_recipient, None) or (None, error_message)."""
    if not isinstance(raw, dict):
        return None, "Recipient must be an object with 'name' and 'email'"
    name = raw.get("name")
    email = raw.get("email")
    if not isinstance(name, str) or not name.strip():
        return None, "'name' is required and must be a non-empty string"
    name = " ".join(name.split())  # collapse stray whitespace
    if len(name) > MAX_NAME_LEN:
        return None, f"'name' must be at most {MAX_NAME_LEN} characters"
    if not isinstance(email, str) or not EMAIL_RE.match(email.strip()):
        return None, "'email' is required and must be a valid email address"
    email = email.strip().lower()
    if email in seen_emails:
        return None, f"Duplicate email in this request: {email}"
    seen_emails.add(email)
    return {"name": name, "email": email}, None


def create_job(db: Session, *, title: str, issuer: str, issue_date, recipients: list) -> models.Job:
    """Persist the job and one row per recipient. Invalid rows are stored as
    already-failed so the client sees exactly which input rows were rejected."""
    job = models.Job(title=title.strip(), issuer=issuer.strip(), issue_date=issue_date)
    seen: set[str] = set()
    for i, raw in enumerate(recipients):
        clean, error = validate_recipient(raw, seen)
        if clean:
            cert = models.Certificate(row_index=i, recipient_name=clean["name"],
                                      recipient_email=clean["email"])
        else:
            cert = models.Certificate(
                row_index=i,
                recipient_name=raw.get("name") if isinstance(raw, dict) and isinstance(raw.get("name"), str) else None,
                recipient_email=raw.get("email") if isinstance(raw, dict) and isinstance(raw.get("email"), str) else None,
                status=models.CERT_FAILED, error=error)
        job.certificates.append(cert)
    # Nothing valid -> nothing to process.
    if all(c.status == models.CERT_FAILED for c in job.certificates):
        job.status = models.FAILED
        job.completed_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def job_counts(db: Session, job_id: str) -> dict:
    rows = db.execute(
        select(models.Certificate.status, func.count())
        .where(models.Certificate.job_id == job_id)
        .group_by(models.Certificate.status)
    ).all()
    by_status = {status: n for status, n in rows}
    total = sum(by_status.values())
    succeeded = by_status.get(models.CERT_SUCCESS, 0)
    failed = by_status.get(models.CERT_FAILED, 0)
    pending = by_status.get(models.CERT_PENDING, 0)
    done = succeeded + failed
    return {
        "total": total, "succeeded": succeeded, "failed": failed, "pending": pending,
        "progress_percent": round(100 * done / total, 1) if total else 100.0,
    }


def process_job(job_id: str) -> None:
    """Generate every pending certificate in a job.

    Runs in a background task with its OWN DB session (the request's session is
    closed by then). Each certificate is committed independently, so progress is
    visible to polling clients and one failure never affects the others.
    """
    db = SessionLocal()
    try:
        job = db.get(models.Job, job_id)
        if job is None or job.status not in (models.PENDING, models.PROCESSING):
            return
        job.status = models.PROCESSING
        db.commit()

        pending = db.scalars(
            select(models.Certificate)
            .where(models.Certificate.job_id == job_id,
                   models.Certificate.status == models.CERT_PENDING)
            .order_by(models.Certificate.row_index)
        ).all()

        for cert in pending:
            try:
                path = os.path.join(settings.cert_dir, job_id, f"{cert.id}.pdf")
                render_certificate(path, recipient_name=cert.recipient_name, title=job.title,
                                   issuer=job.issuer, issue_date=job.issue_date,
                                   certificate_id=cert.id)
                cert.file_path = path
                cert.status = models.CERT_SUCCESS
            except Exception as exc:  # isolate per-certificate failures
                log.exception("Certificate %s failed", cert.id)
                cert.status = models.CERT_FAILED
                cert.error = f"Generation failed: {exc}"
            db.commit()

        _finalize(db, job)
    except Exception:
        # Last-resort safety net so a job is never stuck in 'processing'.
        log.exception("Job %s crashed", job_id)
        db.rollback()
        job = db.get(models.Job, job_id)
        if job:
            _finalize(db, job)
    finally:
        db.close()


def _finalize(db: Session, job: models.Job) -> None:
    c = job_counts(db, job.id)
    if c["pending"]:  # anything left unprocessed after a crash counts as failed
        for cert in db.scalars(select(models.Certificate).where(
                models.Certificate.job_id == job.id,
                models.Certificate.status == models.CERT_PENDING)):
            cert.status, cert.error = models.CERT_FAILED, "Job aborted before processing"
        db.flush()
        c = job_counts(db, job.id)
    if c["failed"] == 0:
        job.status = models.COMPLETED
    elif c["succeeded"] == 0:
        job.status = models.FAILED
    else:
        job.status = models.COMPLETED_WITH_ERRORS
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
