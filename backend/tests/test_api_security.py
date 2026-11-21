"""Authentication, authorization, patient isolation, secure upload, prompt injection."""
import io

from conftest import CSRF, doc_id


def test_unauthenticated_requests_rejected(anon_client, pid):
    assert anon_client.get("/api/patients").status_code == 401
    assert anon_client.get(f"/api/patients/{pid['A']}/timeline").status_code == 401


def test_csrf_header_required_for_state_changes(app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "Test-admin-pass-1"})
    assert r.status_code == 403 and "CSRF" in r.text


def test_wrong_password_and_lockout(app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    for _ in range(5):
        r = c.post("/api/auth/login", json={"username": "lockme", "password": "nope"}, headers=CSRF)
        assert r.status_code == 401          # unknown user: same generic error
    assert c.post("/api/auth/login", json={"username": "admin", "password": "wrong"}, headers=CSRF).status_code == 401


def test_session_cookie_flags(app):
    from fastapi.testclient import TestClient

    r = TestClient(app).post("/api/auth/login", json={"username": "admin", "password": "Test-admin-pass-1"}, headers=CSRF)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_security_headers(admin_client):
    r = admin_client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_reviewer_sees_only_granted_patients(reviewer_client, pid):
    visible = {p["id"] for p in reviewer_client.get("/api/patients").json()}
    assert visible == {pid["A"], pid["B"], pid["C"]}


def test_cross_patient_access_returns_404(reviewer_client, admin_client, pid):
    d_doc = doc_id(admin_client, pid["D"], "D1")
    for url in (f"/api/patients/{pid['D']}", f"/api/patients/{pid['D']}/timeline", f"/api/patients/{pid['D']}/documents",
                f"/api/patients/{pid['D']}/documents/{d_doc}/file", f"/api/patients/{pid['D']}/documents/{d_doc}/pages/1/image"):
        assert reviewer_client.get(url).status_code == 404, url
    assert reviewer_client.post(f"/api/patients/{pid['D']}/ask", json={"question": "Which medications are documented?"}).status_code == 404


def test_object_ids_cannot_be_mixed_across_patients(admin_client, pid):
    """A document of patient D requested under patient A's URL must not be served (backend scoping)."""
    d_doc = doc_id(admin_client, pid["D"], "D1")
    assert admin_client.get(f"/api/patients/{pid['A']}/documents/{d_doc}").status_code == 404
    assert admin_client.get(f"/api/patients/{pid['A']}/documents/{d_doc}/text").status_code == 404
    d_finding = admin_client.get(f"/api/patients/{pid['D']}/findings").json()[0]["id"]
    assert admin_client.get(f"/api/patients/{pid['A']}/findings/{d_finding}").status_code == 404
    r = admin_client.post(f"/api/patients/{pid['A']}/findings/{d_finding}/review", json={"action": "verify"})
    assert r.status_code == 404


def test_qa_never_cites_other_patients(admin_client, pid):
    a = admin_client.post(f"/api/patients/{pid['A']}/ask", json={"question": "Which allergy statements appear in the records?"}).json()
    a_docs = {d["id"] for d in admin_client.get(f"/api/patients/{pid['A']}/documents").json()}
    assert a["citations"] and all(c["document_id"] in a_docs for c in a["citations"])
    # penicillin is documented only for patient B; patient A's records must not surface it
    assert "penicillin" not in " ".join(f["statement"].lower() for f in a["facts"])


def test_viewer_is_read_only(admin_client, app, pid):
    from fastapi.testclient import TestClient

    r = admin_client.post("/api/users", json={"username": "viewer1", "password": "Viewer-pass-123", "role": "viewer"})
    assert r.status_code in (201, 409)
    uid = next(u["id"] for u in admin_client.get("/api/users").json() if u["username"] == "viewer1")
    admin_client.post(f"/api/users/{uid}/access", json={"patient_id": pid["C"], "permission": "write"})
    v = TestClient(app)
    v.post("/api/auth/login", json={"username": "viewer1", "password": "Viewer-pass-123"}, headers=CSRF)
    v.headers.update(CSRF)
    assert v.get(f"/api/patients/{pid['C']}/timeline").status_code == 200
    f = v.get(f"/api/patients/{pid['C']}/findings").json()[0]["id"]
    assert v.post(f"/api/patients/{pid['C']}/findings/{f}/review", json={"action": "verify"}).status_code == 403
    assert v.post("/api/patients", json={"display_name": "X"}).status_code == 403
    assert v.get("/api/users").status_code == 403                       # admin-only


def test_weak_password_rejected(admin_client):
    assert admin_client.post("/api/users", json={"username": "weak", "password": "aaaaaaaaaaaa", "role": "viewer"}).status_code == 400


def test_upload_rejects_malicious_files(admin_client, pid):
    url = f"/api/patients/{pid['C']}/documents"
    r = admin_client.post(url, files={"file": ("evil.pdf", io.BytesIO(b"MZ\x90\x00 not a pdf"), "application/pdf")})
    assert r.status_code == 400
    r = admin_client.post(url, files={"file": ("../../../evil.sh", io.BytesIO(b"#!/bin/sh"), "text/plain")})
    assert r.status_code == 400
    import pymupdf as fitz

    d = fitz.open(); d.new_page().insert_text((72, 72), "x")
    js = d.tobytes().replace(b"%%EOF", b"<< /S /Launch /F (cmd.exe) >>\n%%EOF")
    assert admin_client.post(url, files={"file": ("launch.pdf", io.BytesIO(js), "application/pdf")}).status_code == 400


def test_page_route_rejects_out_of_range_and_traversal(admin_client, pid):
    did = doc_id(admin_client, pid["A"], "A1")
    assert admin_client.get(f"/api/patients/{pid['A']}/documents/{did}/pages/99/image").status_code == 404
    assert admin_client.get(f"/api/patients/{pid['A']}/documents/..%2F..%2Fmedtrace.db/file").status_code == 404


def test_prompt_injection_in_document_is_inert(admin_client, pid):
    docs = admin_client.get(f"/api/patients/{pid['E']}/documents").json()
    e1 = next(d for d in docs if d["original_filename"].startswith("E1"))
    assert e1["injection_flags"]                                   # flagged for the reviewer
    a = admin_client.post(f"/api/patients/{pid['E']}/ask", json={"question": "Which allergy statements appear in the records?"}).json()
    text = (a["answer"] + " ".join(f["statement"] for f in a["facts"])).lower()
    assert "not recorded" in text                                   # the documented statement is reported
    assert "no known" not in text and "no allergies" not in text   # the injected claim is not
    me = admin_client.get("/api/auth/me").json()
    assert me["role"] == "admin"                                     # nothing about permissions changed
    gaps = admin_client.get(f"/api/patients/{pid['E']}/gaps").json()
    assert any(g["gap_type"] == "instruction_like_text" for g in gaps)


def test_access_log_contains_identifiers_only(pid):
    from medtrace.db import connection, rows

    with connection() as c:
        cols = rows(c, "PRAGMA table_info(access_logs)")
    assert {x["name"] for x in cols} == {"id", "ts", "user_id", "action", "patient_id", "resource_id", "outcome"}
