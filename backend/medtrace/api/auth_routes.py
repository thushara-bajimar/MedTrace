"""Authentication and user/access administration endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import connection, now_iso, one, rows, transaction
from ..security import (SESSION_COOKIE, User, audit, create_user, current_user, login, logout, require_admin,
                        validate_new_password, visible_patient_ids)

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: Literal["admin", "reviewer", "viewer"]


class AccessIn(BaseModel):
    patient_id: str = Field(max_length=64)
    permission: Literal["read", "write"]


@router.post("/auth/login")
def do_login(body: LoginIn, response: Response):
    token, user = login(body.username, body.password)
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=s.cookie_secure,
                        max_age=s.session_hours * 3600, path="/")
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/auth/logout")
def do_logout(request: Request, response: Response):
    logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/users")
def list_users(_: User = Depends(require_admin)):
    with connection() as conn:
        users = rows(conn, "SELECT id, username, role, created_at FROM users ORDER BY username")
        for u in users:
            u["access"] = rows(conn, "SELECT patient_id, permission FROM patient_access WHERE user_id=?", (u["id"],))
        return users


@router.post("/users", status_code=201)
def add_user(body: UserIn, admin: User = Depends(require_admin)):
    validate_new_password(body.password)
    with transaction() as conn:
        if one(conn, "SELECT id FROM users WHERE username=?", (body.username,)):
            raise HTTPException(409, "Username already exists.")
        uid = create_user(conn, body.username, body.password, body.role)
        audit(conn, admin.id, "user_create", resource_id=uid)
    return {"id": uid, "username": body.username, "role": body.role}


@router.post("/users/{user_id}/access")
def grant_access(user_id: str, body: AccessIn, admin: User = Depends(require_admin)):
    with transaction() as conn:
        if not one(conn, "SELECT id FROM users WHERE id=?", (user_id,)) or not one(conn, "SELECT id FROM patients WHERE id=?", (body.patient_id,)):
            raise HTTPException(404, "User or patient not found.")
        conn.execute("INSERT INTO patient_access (user_id, patient_id, permission, granted_at) VALUES (?,?,?,?) "
                     "ON CONFLICT(user_id, patient_id) DO UPDATE SET permission=excluded.permission", (user_id, body.patient_id, body.permission, now_iso()))
        audit(conn, admin.id, "access_grant", patient_id=body.patient_id, resource_id=user_id)
    return {"ok": True}


@router.delete("/users/{user_id}/access/{patient_id}")
def revoke_access(user_id: str, patient_id: str, admin: User = Depends(require_admin)):
    with transaction() as conn:
        conn.execute("DELETE FROM patient_access WHERE user_id=? AND patient_id=?", (user_id, patient_id))
        audit(conn, admin.id, "access_revoke", patient_id=patient_id, resource_id=user_id)
    return {"ok": True}


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user)):
    with connection() as conn:
        pids = visible_patient_ids(conn, user)
        if not pids:
            return {"patients": 0, "documents": 0, "documents_by_status": {}, "timeline_events": 0, "unverified_findings": 0,
                    "conflicts_unresolved": 0, "duplicates_pending": 0, "gaps": 0, "recent_uploads": [], "findings_by_type": {}}
        ph = ",".join("?" * len(pids))
        q = lambda sql: conn.execute(sql.format(ph=ph), pids).fetchone()[0]  # noqa: E731
        by_status = {r["extraction_status"]: r["n"] for r in rows(conn, f"SELECT extraction_status, COUNT(*) n FROM documents WHERE patient_id IN ({ph}) GROUP BY extraction_status", pids)}
        by_type = {r["finding_type"]: r["n"] for r in rows(conn, f"SELECT finding_type, COUNT(*) n FROM findings WHERE is_active=1 AND verification_status!='rejected' AND patient_id IN ({ph}) GROUP BY finding_type", pids)}
        recent = rows(conn, f"""SELECT d.id, d.patient_id, p.display_name AS patient_name, d.original_filename, d.doc_type, d.upload_date,
                                d.extraction_status, d.ocr_status FROM documents d JOIN patients p ON p.id=d.patient_id
                                WHERE d.patient_id IN ({ph}) ORDER BY d.upload_date DESC, d.id LIMIT 8""", pids)
        return {
            "patients": len(pids),
            "documents": q("SELECT COUNT(*) FROM documents WHERE patient_id IN ({ph})"),
            "documents_by_status": by_status,
            "timeline_events": q("SELECT COUNT(*) FROM findings WHERE is_active=1 AND verification_status!='rejected' AND patient_id IN ({ph})"),
            "unverified_findings": q("SELECT COUNT(*) FROM findings WHERE is_active=1 AND verification_status='unverified' AND patient_id IN ({ph})"),
            "conflicts_unresolved": q("SELECT COUNT(*) FROM conflicts WHERE still_detected=1 AND status='unresolved' AND patient_id IN ({ph})"),
            "duplicates_pending": q("SELECT COUNT(*) FROM duplicate_candidates WHERE review_status='pending' AND level='document' AND patient_id IN ({ph})"),
            "gaps": q("SELECT COUNT(*) FROM gaps WHERE patient_id IN ({ph})"),
            "findings_by_type": by_type,
            "recent_uploads": recent,
        }
