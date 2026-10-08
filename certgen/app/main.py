import io
import os
import zipfile

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, service
from .database import Base, engine, get_db
from .schemas import CertificateOut, JobCreate, JobDetail, JobSummary

Base.metadata.create_all(engine)

app = FastAPI(title="Bulk Certificate Generator", version="1.0.0")


# ---------- helpers ----------
def _get_job_or_404(db: Session, job_id: str) -> models.Job:
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _summary(db: Session, job: models.Job) -> dict:
    counts = service.job_counts(db, job.id)
    return {
        "id": job.id, "title": job.title, "issuer": job.issuer, "issue_date": job.issue_date,
        "status": job.status, "created_at": job.created_at, "completed_at": job.completed_at,
        "status_url": f"/jobs/{job.id}",
        "download_all_url": f"/jobs/{job.id}/download" if counts["succeeded"] else None,
        **counts,
    }


def _cert_out(cert: models.Certificate) -> CertificateOut:
    ok = cert.status == models.CERT_SUCCESS
    return CertificateOut(
        id=cert.id, row_index=cert.row_index, recipient_name=cert.recipient_name,
        recipient_email=cert.recipient_email, status=cert.status, error=cert.error,
        download_url=f"/jobs/{cert.job_id}/certificates/{cert.id}/download" if ok else None)


# ---------- endpoints ----------
@app.post("/jobs", response_model=JobSummary, status_code=202)
def create_job(payload: JobCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Submit a bulk request. Returns 202 immediately; poll GET /jobs/{id}."""
    job = service.create_job(db, title=payload.title, issuer=payload.issuer,
                             issue_date=payload.issue_date, recipients=payload.recipients)
    if job.status == models.PENDING:
        background.add_task(service.process_job, job.id)
    return _summary(db, job)


@app.get("/jobs", response_model=list[JobSummary])
def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db)):
    jobs = db.scalars(select(models.Job).order_by(models.Job.created_at.desc())
                      .limit(limit).offset(offset)).all()
    return [_summary(db, j) for j in jobs]


@app.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Status, progress counts and a per-recipient result (including errors)."""
    job = _get_job_or_404(db, job_id)
    return {**_summary(db, job), "certificates": [_cert_out(c) for c in job.certificates]}


@app.get("/jobs/{job_id}/certificates/{certificate_id}/download")
def download_certificate(job_id: str, certificate_id: str, db: Session = Depends(get_db)):
    cert = db.get(models.Certificate, certificate_id)
    if not cert or cert.job_id != job_id:
        raise HTTPException(404, "Certificate not found")
    if cert.status != models.CERT_SUCCESS or not cert.file_path or not os.path.exists(cert.file_path):
        raise HTTPException(409, f"Certificate is not available (status: {cert.status})")
    return FileResponse(cert.file_path, media_type="application/pdf",
                        filename=f"certificate_{cert.id}.pdf")


@app.get("/jobs/{job_id}/download")
def download_all(job_id: str, db: Session = Depends(get_db)):
    """ZIP of every successfully generated certificate in the job."""
    job = _get_job_or_404(db, job_id)
    certs = [c for c in job.certificates if c.status == models.CERT_SUCCESS
             and c.file_path and os.path.exists(c.file_path)]
    if not certs:
        raise HTTPException(409, f"No certificates available yet (job status: {job.status})")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in certs:
            safe = "".join(ch if ch.isalnum() else "_" for ch in (c.recipient_name or "recipient"))
            zf.write(c.file_path, arcname=f"{c.row_index + 1:04d}_{safe}.pdf")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="job_{job.id}.zip"'})


@app.get("/health")
def health():
    return {"status": "ok"}
