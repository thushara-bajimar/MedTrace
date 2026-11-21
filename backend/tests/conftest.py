"""Test configuration: an isolated temporary data directory, seeded once with the synthetic dataset."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="medtrace_test_")
os.environ["MEDTRACE_DATA_DIR"] = _TMP
os.environ["MEDTRACE_ADMIN_USERNAME"] = "admin"
os.environ["MEDTRACE_ADMIN_PASSWORD"] = "Test-admin-pass-1"
os.environ["MEDTRACE_DEMO_REVIEWER_PASSWORD"] = "Test-reviewer-pass-1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ADMIN = ("admin", "Test-admin-pass-1")
REVIEWER = ("reviewer", "Test-reviewer-pass-1")
CSRF = {"X-MedTrace-CSRF": "1"}


@pytest.fixture(scope="session")
def seeded():
    from medtrace.seed import seed

    return seed(reset=False, include_holdout=True, verbose=False)


@pytest.fixture(scope="session")
def app(seeded):
    from medtrace.main import app as _app

    return _app


def _login(app, creds):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": creds[0], "password": creds[1]}, headers=CSRF)
    assert r.status_code == 200, r.text
    c.headers.update(CSRF)
    return c


@pytest.fixture(scope="session")
def admin_client(app):
    return _login(app, ADMIN)


@pytest.fixture(scope="session")
def reviewer_client(app):
    return _login(app, REVIEWER)


@pytest.fixture(scope="session")
def anon_client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture(scope="session")
def pid(seeded):
    """Map patient letter -> patient id."""
    return seeded


def doc_id(client, patient_id, prefix):
    docs = client.get(f"/api/patients/{patient_id}/documents").json()
    return next(d["id"] for d in docs if d["original_filename"].startswith(prefix))
