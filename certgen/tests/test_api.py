import io
import zipfile

from app import certificate, service
from app.config import settings


# ---------- creating a job ----------
def test_create_job_returns_202_and_job_summary(client, payload):
    r = client.post("/jobs", json=payload)
    assert r.status_code == 202
    body = r.json()
    assert body["total"] == 3
    assert body["status_url"] == f"/jobs/{body['id']}"


# ---------- input validation ----------
def test_request_level_validation_rejects_bad_payloads(client, payload):
    assert client.post("/jobs", json={**payload, "recipients": []}).status_code == 422
    assert client.post("/jobs", json={**payload, "title": ""}).status_code == 422
    missing = {k: v for k, v in payload.items() if k != "issuer"}
    assert client.post("/jobs", json=missing).status_code == 422
    too_many = {**payload, "recipients": [{"name": "x", "email": "x@y.zz"}] * (settings.max_recipients + 1)}
    assert client.post("/jobs", json=too_many).status_code == 422


def test_invalid_recipients_are_recorded_and_valid_ones_still_generate(client, payload):
    payload["recipients"] = [
        {"name": "Good One", "email": "good@example.com"},
        {"name": "   ", "email": "blank@example.com"},          # blank name
        {"name": "No Email"},                                    # missing email
        {"name": "Bad Email", "email": "not-an-email"},          # bad email
        {"name": "Dup", "email": "GOOD@example.com"},            # duplicate (case-insens.)
        "just a string",                                         # wrong type
    ]
    job = client.post("/jobs", json=payload).json()
    detail = client.get(f"/jobs/{job['id']}").json()
    assert detail["status"] == "completed_with_errors"
    assert detail["succeeded"] == 1 and detail["failed"] == 5
    statuses = [c["status"] for c in detail["certificates"]]
    assert statuses == ["success"] + ["failed"] * 5
    assert all(c["error"] for c in detail["certificates"][1:])


def test_job_with_only_invalid_recipients_is_failed(client, payload):
    payload["recipients"] = [{"name": "", "email": "x"}]
    job = client.post("/jobs", json=payload).json()
    assert job["status"] == "failed"
    assert job["progress_percent"] == 100.0


def test_validate_recipient_unit():
    seen = set()
    ok, err = service.validate_recipient({"name": "  A   B ", "email": " A@B.com "}, seen)
    assert err is None and ok == {"name": "A B", "email": "a@b.com"}
    _, err = service.validate_recipient({"name": "x" * 101, "email": "a@b.com"}, set())
    assert "at most" in err


# ---------- certificate generation ----------
def test_generated_files_are_real_pdfs(client, payload):
    job = client.post("/jobs", json=payload).json()
    detail = client.get(f"/jobs/{job['id']}").json()
    for cert in detail["certificates"]:
        r = client.get(cert["download_url"])
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")


# ---------- job status / progress ----------
def test_completed_job_status_and_progress(client, payload):
    job = client.post("/jobs", json=payload).json()
    detail = client.get(f"/jobs/{job['id']}").json()
    assert detail["status"] == "completed"
    assert (detail["total"], detail["succeeded"], detail["failed"], detail["pending"]) == (3, 3, 0, 0)
    assert detail["progress_percent"] == 100.0
    assert detail["completed_at"] is not None


def test_unknown_job_is_404(client):
    assert client.get("/jobs/does-not-exist").status_code == 404


def test_list_jobs(client, payload):
    client.post("/jobs", json=payload)
    client.post("/jobs", json=payload)
    assert len(client.get("/jobs").json()) == 2


# ---------- individual certificate failure ----------
def test_one_generation_failure_does_not_stop_the_others(client, payload, monkeypatch):
    real = certificate.render_certificate

    def flaky(path, **kw):
        if kw["recipient_name"] == "Ravi Kumar":
            raise RuntimeError("boom")
        return real(path, **kw)

    monkeypatch.setattr(service, "render_certificate", flaky)
    job = client.post("/jobs", json=payload).json()
    detail = client.get(f"/jobs/{job['id']}").json()

    assert detail["status"] == "completed_with_errors"
    assert (detail["succeeded"], detail["failed"]) == (2, 1)
    failed = [c for c in detail["certificates"] if c["status"] == "failed"]
    assert failed[0]["recipient_name"] == "Ravi Kumar"
    assert "boom" in failed[0]["error"]
    assert failed[0]["download_url"] is None
    # failed certificate can't be downloaded
    r = client.get(f"/jobs/{job['id']}/certificates/{failed[0]['id']}/download")
    assert r.status_code == 409


# ---------- retrieving certificates ----------
def test_download_all_returns_zip_of_successes_only(client, payload, monkeypatch):
    real = certificate.render_certificate
    monkeypatch.setattr(service, "render_certificate",
                        lambda p, **kw: (_ for _ in ()).throw(RuntimeError("x"))
                        if kw["recipient_name"] == "Meena S" else real(p, **kw))
    job = client.post("/jobs", json=payload).json()
    r = client.get(f"/jobs/{job['id']}/download")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2
    assert all(n.endswith(".pdf") for n in names)


def test_download_all_conflict_when_nothing_generated(client, payload):
    payload["recipients"] = [{"name": "", "email": "bad"}]
    job = client.post("/jobs", json=payload).json()
    assert client.get(f"/jobs/{job['id']}/download").status_code == 409


def test_cannot_download_certificate_through_wrong_job(client, payload):
    a = client.post("/jobs", json=payload).json()
    b = client.post("/jobs", json=payload).json()
    cert_id = client.get(f"/jobs/{a['id']}").json()["certificates"][0]["id"]
    assert client.get(f"/jobs/{b['id']}/certificates/{cert_id}/download").status_code == 404
