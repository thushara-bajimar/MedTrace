"""Authentication, sessions, patient-scoped authorization and privacy-conscious audit logging.

Design:
* Passwords: scrypt (stdlib hashlib) with per-user random salt.
* Sessions: 32-byte random token in an HttpOnly, SameSite=Strict cookie. Only the SHA-256
  of the token is stored, so a database leak does not reveal live session tokens.
* CSRF: state-changing requests must carry the custom header ``X-MedTrace-CSRF: 1``.
  Browsers cannot send custom headers cross-origin without a CORS preflight, and CORS is
  restricted to configured origins.
* Authorization: admins see every patient. Reviewers/viewers see only patients they were
  granted in ``patient_access``. Every patient-scoped route calls ``require_patient`` on the
  backend - the frontend is never trusted for isolation.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status

from .config import get_settings
from .db import connection, new_id, now_iso, one, transaction

SESSION_COOKIE = "medtrace_session"
CSRF_HEADER = "x-medtrace-csrf"
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(dk.hex(), dk_hex)


def validate_new_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(400, "Password must be at least 10 characters.")
    if password.isalpha() or password.isdigit():
        raise HTTPException(400, "Password must mix letters with digits or symbols.")


# ---------------------------------------------------------------- users
@dataclass
class User:
    id: str
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def create_user(conn: sqlite3.Connection, username: str, password: str, role: str) -> str:
    uid = new_id("usr")
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?,?,?,?,?)",
        (uid, username, hash_password(password), role, now_iso()),
    )
    return uid


def bootstrap_admin() -> str | None:
    """Create the first administrator from the environment. Returns a generated password
    (to print once) when MEDTRACE_ADMIN_PASSWORD was not configured."""
    s = get_settings()
    with transaction() as conn:
        if one(conn, "SELECT id FROM users LIMIT 1"):
            return None
        password = s.admin_password
        generated = None
        if not password:
            password = secrets.token_urlsafe(12) + "9!"
            generated = password
        create_user(conn, s.admin_username, password, "admin")
        return generated


# ---------------------------------------------------------------- sessions
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def login(username: str, password: str) -> tuple[str, User]:
    s = get_settings()
    with transaction() as conn:
        u = one(conn, "SELECT * FROM users WHERE username = ?", (username,))
        generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")
        if u is None:
            # Constant-ish work to reduce username enumeration via timing.
            verify_password(password, "scrypt$" + "00" * 16 + "$" + "00" * 32)
            raise generic
        if u["locked_until"] and u["locked_until"] > now_iso():
            raise HTTPException(429, "Account temporarily locked after repeated failures.")
        if not verify_password(password, u["password_hash"]):
            failures = u["failed_logins"] + 1
            locked = None
            if failures >= s.login_max_failures:
                locked = (datetime.now(timezone.utc) + timedelta(seconds=s.login_lockout_seconds)).replace(microsecond=0).isoformat()
                failures = 0
            conn.execute("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?", (failures, locked, u["id"]))
            audit(conn, u["id"], "login", outcome="denied")
            raise generic
        conn.execute("UPDATE users SET failed_logins=0, locked_until=NULL WHERE id=?", (u["id"],))
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?,?,?,?,?)",
            (_token_hash(token), u["id"], now.isoformat(), (now + timedelta(hours=s.session_hours)).isoformat(), now.isoformat()),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
        audit(conn, u["id"], "login", outcome="ok")
        return token, User(u["id"], u["username"], u["role"])


def logout(token: str | None) -> None:
    if not token:
        return
    with transaction() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def current_user(request: Request) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    with connection() as conn:
        row = one(
            conn,
            "SELECT u.id, u.username, u.role, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (_token_hash(token),),
        )
        if row is None or row["expires_at"] < now_iso():
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid.")
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now_iso(), _token_hash(token)))
    return User(row["id"], row["username"], row["role"])


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required.")
    return user


# ---------------------------------------------------------------- patient scoping
def patient_permission(conn: sqlite3.Connection, user: User, patient_id: str) -> str | None:
    if not one(conn, "SELECT id FROM patients WHERE id = ?", (patient_id,)):
        return None
    if user.is_admin:
        return "write"
    row = one(conn, "SELECT permission FROM patient_access WHERE user_id=? AND patient_id=?", (user.id, patient_id))
    if row is None:
        return None
    if user.role == "viewer":
        return "read"
    return row["permission"]


def require_patient(conn: sqlite3.Connection, user: User, patient_id: str, write: bool = False) -> None:
    """Raise 404 (not 403) when the patient is not visible, so the existence of other
    patients' records is not disclosed."""
    perm = patient_permission(conn, user, patient_id)
    if perm is None:
        audit(conn, user.id, "patient_access", patient_id=patient_id, outcome="denied")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")
    if write and perm != "write":
        audit(conn, user.id, "patient_write", patient_id=patient_id, outcome="denied")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Write permission required for this patient.")


def visible_patient_ids(conn: sqlite3.Connection, user: User) -> list[str]:
    if user.is_admin:
        return [r[0] for r in conn.execute("SELECT id FROM patients").fetchall()]
    return [r[0] for r in conn.execute("SELECT patient_id FROM patient_access WHERE user_id=?", (user.id,)).fetchall()]


# ---------------------------------------------------------------- audit
def audit(conn: sqlite3.Connection, user_id: str | None, action: str, patient_id: str | None = None,
          resource_id: str | None = None, outcome: str = "ok") -> None:
    """Identifiers only: never write document text, questions or names into the audit log."""
    conn.execute(
        "INSERT INTO access_logs (ts, user_id, action, patient_id, resource_id, outcome) VALUES (?,?,?,?,?,?)",
        (now_iso(), user_id, action, patient_id, resource_id, outcome),
    )
