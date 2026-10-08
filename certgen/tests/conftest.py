import os
import tempfile

# Must be set BEFORE the app is imported (settings are read at import time).
_tmp = tempfile.mkdtemp(prefix="certgen_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["CERT_DIR"] = f"{_tmp}/certs"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    # TestClient runs BackgroundTasks before returning, so a job is already
    # finished when the POST response comes back -> deterministic tests.
    return TestClient(app)


@pytest.fixture
def payload():
    return {
        "title": "Python Bootcamp",
        "issuer": "Acme Academy",
        "issue_date": "2026-10-01",
        "recipients": [
            {"name": "Asha Rao", "email": "asha@example.com"},
            {"name": "Ravi Kumar", "email": "ravi@example.com"},
            {"name": "Meena S", "email": "meena@example.com"},
        ],
    }
