# Bulk Certificate Generator (FastAPI)

Backend API that accepts a list of recipients in **one request**, generates a PDF
certificate for each from a single predefined template, tracks progress, and lets
the client download results individually or as a ZIP.

**Stack:** Python 3.10+, FastAPI, SQLAlchemy 2 + SQLite (relational DB), ReportLab (PDF), pytest.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run
```bash
uvicorn app.main:app --reload
```
- API: http://127.0.0.1:8000  |  Interactive docs: http://127.0.0.1:8000/docs
- SQLite DB `certgen.db` and PDFs in `generated_certificates/` are created automatically.
- Config via env vars: `DATABASE_URL` (default `sqlite:///./certgen.db`), `CERT_DIR`, `MAX_RECIPIENTS` (default 1000).

## Run tests
```bash
python -m pytest -v
```

## API usage

### 1. Submit a request  `POST /jobs`  -> `202 Accepted`
```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{
  "title": "Python Bootcamp 2026",
  "issuer": "Acme Academy",
  "issue_date": "2026-10-01",
  "recipients": [
    {"name": "Asha Rao",   "email": "asha@example.com"},
    {"name": "Ravi Kumar", "email": "ravi@example.com"}
  ]
}'
```
Response contains the job `id` and a `status_url`. (`issue_date` is optional, defaults to today.)

### 2. Check progress  `GET /jobs/{job_id}`
```bash
curl http://127.0.0.1:8000/jobs/<job_id>
```
Returns `status`, `total / succeeded / failed / pending`, `progress_percent`, and a
per-recipient list with `status`, `error` (if any) and `download_url` (if successful).

Job statuses: `pending` -> `processing` -> `completed` | `completed_with_errors` | `failed`.

### 3. Retrieve certificates
- One certificate: `GET /jobs/{job_id}/certificates/{certificate_id}/download` (PDF)
- All successful ones: `GET /jobs/{job_id}/download` (ZIP)
```bash
curl -OJ http://127.0.0.1:8000/jobs/<job_id>/download
```
Returns `409` if the certificate/ZIP isn't available (still pending, or failed).

Also: `GET /jobs` (list, paginated), `GET /health`.

## Design decisions

**Async via background task (202 + polling).** A request may hold hundreds of
recipients, so doing the work inside the HTTP request would risk timeouts. `POST /jobs`
validates, stores the job and returns `202` immediately; generation runs in a FastAPI
`BackgroundTask` and the client polls `GET /jobs/{id}`. It needs no extra infrastructure
(no Redis/Celery), which keeps setup simple. *Trade-off:* if the server dies mid-job,
the job stays `processing`; for production I'd move to a durable queue (Celery/RQ) with
a worker and a startup sweep for stuck jobs.

**Two layers of validation.**
1. *Request-level* (Pydantic): missing/empty title or issuer, empty recipient list,
   more than `MAX_RECIPIENTS` -> `422`, nothing is created.
2. *Per-recipient* (service layer): blank/too-long name, invalid email, duplicate email
   (case-insensitive) in the same request. Bad rows are **not** rejected as a whole; they are
   stored as `failed` with a clear error and the valid rows are still generated. This
   satisfies "one bad record shouldn't block the others" and tells the client exactly
   which row failed (`row_index` = position in the submitted list).

**Failure isolation.** Each certificate is generated in its own `try/except` and
committed individually. One failure marks only that row failed; progress is visible
live to pollers. A final safety net guarantees a job is never left stuck in `processing`.

**Job outcome.** `completed` (all ok), `completed_with_errors` (mixed), `failed` (none ok).

**Data model.** `jobs` (1) -> (N) `certificates`. Counts/progress are computed with a
`GROUP BY` on certificate status rather than stored counters, so they can never drift.

**Storage.** PDFs live on disk under `generated_certificates/<job_id>/<certificate_id>.pdf`;
the DB stores the path. File names use UUIDs, never user input (no path-traversal risk).
Downloads verify the certificate belongs to the job in the URL.

**Template.** One hard-coded landscape A4 template in `app/certificate.py`.

## Known limitations / possible improvements
- Built-in PDF font is Helvetica: names in non-Latin scripts (e.g. Tamil) need a TTF font registered.
- No authentication or rate limiting.
- Processing is sequential within a job; a worker pool could parallelise large jobs.
- SQLite is used for easy setup; set `DATABASE_URL` to switch to PostgreSQL (add the driver).

## Project layout
```
app/
  main.py         # routes
  schemas.py      # request/response models
  models.py       # Job, Certificate tables + status constants
  service.py      # validation, job creation, background processing
  certificate.py  # PDF template rendering
  database.py, config.py
tests/            # pytest suite (13 tests)
```
