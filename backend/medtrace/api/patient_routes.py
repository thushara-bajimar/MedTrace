"""Patient management plus patient-scoped findings, timeline and reconstructed views."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import views
from ..analysis import conflicts as conflict_mod, duplicates as dup_mod, gaps as gap_mod
from ..config import get_settings
from ..corrections import finding_history
from ..db import connection, new_id, now_iso, one, rows, transaction
from ..security import User, audit, current_user, require_patient, visible_patient_ids
from ..store import get_finding, get_findings

router = APIRouter(prefix="/api/patients", tags=["patients"])


class PatientIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    synthetic_label: str | None = Field(default=None, max_length=200)
    date_of_birth_text: str | None = Field(default=None, max_length=40)
    sex: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)


class PatientPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    synthetic_label: str | None = Field(default=None, max_length=200)
    date_of_birth_text: str | None = Field(default=None, max_length=40)
    sex: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)


def _patient_row(conn, pid):
    p = one(conn, "SELECT * FROM patients WHERE id=?", (pid,))
    p["counts"] = {
        "documents": conn.execute("SELECT COUNT(*) FROM documents WHERE patient_id=?", (pid,)).fetchone()[0],
        "findings": conn.execute("SELECT COUNT(*) FROM findings WHERE patient_id=? AND is_active=1 AND verification_status!='rejected'", (pid,)).fetchone()[0],
        "unverified": conn.execute("SELECT COUNT(*) FROM findings WHERE patient_id=? AND is_active=1 AND verification_status='unverified'", (pid,)).fetchone()[0],
        "conflicts_unresolved": conn.execute("SELECT COUNT(*) FROM conflicts WHERE patient_id=? AND still_detected=1 AND status='unresolved'", (pid,)).fetchone()[0],
        "duplicates_pending": conn.execute("SELECT COUNT(*) FROM duplicate_candidates WHERE patient_id=? AND review_status='pending' AND level='document'", (pid,)).fetchone()[0],
        "gaps": conn.execute("SELECT COUNT(*) FROM gaps WHERE patient_id=?", (pid,)).fetchone()[0],
        "processing": conn.execute("SELECT COUNT(*) FROM documents WHERE patient_id=? AND extraction_status IN ('pending','processing')", (pid,)).fetchone()[0],
    }
    return p


@router.get("")
def list_patients(user: User = Depends(current_user)):
    with connection() as conn:
        pids = visible_patient_ids(conn, user)
        return [_patient_row(conn, pid) for pid in sorted(pids, key=lambda p: one(conn, "SELECT display_name FROM patients WHERE id=?", (p,))["display_name"])]


@router.post("", status_code=201)
def create_patient(body: PatientIn, user: User = Depends(current_user)):
    if user.role == "viewer":
        raise HTTPException(403, "Viewers cannot create patients.")
    pid = new_id("pat")
    with transaction() as conn:
        conn.execute("""INSERT INTO patients (id, display_name, synthetic_label, date_of_birth_text, sex, notes, is_synthetic, created_by, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,1,?,?,?)""",
                     (pid, body.display_name, body.synthetic_label, body.date_of_birth_text, body.sex, body.notes, user.id, now_iso(), now_iso()))
        if not user.is_admin:
            conn.execute("INSERT INTO patient_access (user_id, patient_id, permission, granted_at) VALUES (?,?,?,?)", (user.id, pid, "write", now_iso()))
        audit(conn, user.id, "patient_create", patient_id=pid)
        return _patient_row(conn, pid)


@router.get("/{pid}")
def get_patient(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return _patient_row(conn, pid)


@router.patch("/{pid}")
def update_patient(pid: str, body: PatientPatch, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
        if fields:
            conn.execute(f"UPDATE patients SET {', '.join(f'{k}=?' for k in fields)}, updated_at=? WHERE id=?", (*fields.values(), now_iso(), pid))
        audit(conn, user.id, "patient_update", patient_id=pid)
        return _patient_row(conn, pid)


@router.delete("/{pid}")
def delete_patient(pid: str, user: User = Depends(current_user)):
    """Deletes a synthetic patient's record space: rows cascade and stored files are removed."""
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        p = one(conn, "SELECT is_synthetic FROM patients WHERE id=?", (pid,))
        if not p["is_synthetic"]:
            raise HTTPException(400, "Only synthetic patient records can be deleted through the MVP interface.")
        conn.execute("DELETE FROM patients WHERE id=?", (pid,))
        audit(conn, user.id, "patient_delete", patient_id=pid)
    base = get_settings().upload_dir.resolve()
    target = (base / pid).resolve()
    if base in target.parents and target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    return {"ok": True}


# ---------------------------------------------------------------- findings
@router.get("/{pid}/findings")
def list_findings(pid: str, type: str | None = None, document_id: str | None = None, verification: str | None = None,
                  confidence: str | None = None, date_from: str | None = None, date_to: str | None = None,
                  include_rejected: bool = False, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        where, params = [], []
        if type:
            where.append("f.finding_type=?"); params.append(type)
        if document_id:
            where.append("f.document_id=?"); params.append(document_id)
        if verification:
            where.append("f.verification_status=?"); params.append(verification)
        elif not include_rejected:
            where.append("f.verification_status!='rejected'")
        if confidence:
            where.append("f.confidence_label=?"); params.append(confidence)
        if date_from:
            where.append("f.date_iso >= ?"); params.append(date_from)
        if date_to:
            where.append("f.date_iso <= ?"); params.append(date_to + "-99")
        items = get_findings(conn, pid, " AND ".join(where), tuple(params))
        for it in items:
            it["summary"] = views.summarise(it)
        return items


@router.get("/{pid}/findings/{fid}")
def finding_detail(pid: str, fid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        f = get_finding(conn, pid, fid)
        if f is None:
            raise HTTPException(404, "Finding not found.")
        f["summary"] = views.summarise(f)
        f["evidence"] = _evidence(conn, pid, f)
        f["history"] = finding_history(conn, pid, fid)
        f["conflicts"] = rows(conn, """SELECT c.id, c.category, c.explanation, c.status FROM conflicts c JOIN conflict_findings cf ON cf.conflict_id=c.id
                                       WHERE cf.finding_id=? AND c.patient_id=?""", (fid, pid))
        f["gaps"] = rows(conn, "SELECT gap_type, description FROM gaps WHERE finding_id=? AND patient_id=?", (fid, pid))
        return f


def _evidence(conn, pid, f):
    lines = rows(conn, """SELECT line_index, text, x0, y0, x1, y1, confidence, source FROM page_lines
                          WHERE document_id=? AND patient_id=? AND page_number=? AND line_index BETWEEN ? AND ? ORDER BY line_index""",
                 (f["document_id"], pid, f["page_number"], max(0, f["line_start"] - 2), f["line_end"] + 2))
    page = one(conn, "SELECT width, height, text_source, ocr_confidence FROM document_pages WHERE document_id=? AND page_number=?",
               (f["document_id"], f["page_number"]))
    return {"document_id": f["document_id"], "document_filename": f["document_filename"], "document_type": f["document_type"],
            "page": f["page_number"], "line_start": f["line_start"], "line_end": f["line_end"], "source_passage": f["source_passage"],
            "original_text": f["original_text"], "extraction_method": f["extraction_method"], "provenance_type": f["provenance_type"],
            "page_width": page["width"] if page else None, "page_height": page["height"] if page else None,
            "page_text_source": page["text_source"] if page else None,
            "highlight": [l for l in lines if f["line_start"] <= l["line_index"] <= f["line_end"]],
            "context_lines": lines}


@router.get("/{pid}/findings/{fid}/evidence")
def finding_evidence(pid: str, fid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        f = get_finding(conn, pid, fid)
        if f is None:
            raise HTTPException(404, "Finding not found.")
        return _evidence(conn, pid, f)


@router.get("/{pid}/findings/{fid}/history")
def finding_versions(pid: str, fid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        if get_finding(conn, pid, fid) is None:
            raise HTTPException(404, "Finding not found.")
        return finding_history(conn, pid, fid)


# ---------------------------------------------------------------- reconstructed views
@router.get("/{pid}/timeline")
def get_timeline(pid: str, types: str | None = Query(None, description="comma-separated finding or event types"),
                 date_from: str | None = None, date_to: str | None = None, document_id: str | None = None,
                 verification: str | None = None, q: str | None = None, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return views.timeline(conn, pid, types.split(",") if types else None, date_from, date_to, document_id, verification, q)


@router.get("/{pid}/timeline/{fid}")
def get_timeline_event(pid: str, fid: str, user: User = Depends(current_user)):
    return finding_detail(pid, fid, user)


@router.post("/{pid}/timeline/rebuild")
def rebuild_timeline(pid: str, user: User = Depends(current_user)):
    """Re-runs duplicate, conflict and gap detection; the timeline itself is derived on read."""
    with connection() as conn:
        require_patient(conn, user, pid, write=True)
    dup_mod.detect_for_patient(pid)
    conflict_mod.detect_for_patient(pid)
    gap_mod.detect_for_patient(pid)
    return {"ok": True}


@router.get("/{pid}/medications")
def get_medications(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return views.medication_history(conn, pid)


@router.get("/{pid}/medications/mentions")
def get_med_mentions(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return [m for g in views.medication_history(conn, pid)["medications"] for m in g["mentions"]]


@router.get("/{pid}/medications/changes")
def get_med_changes(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return [dict(c, medication=g["medication"]) for g in views.medication_history(conn, pid)["medications"] for c in g["documented_changes"]]


@router.get("/{pid}/allergies")
def get_allergies(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return views.allergy_summary(conn, pid)


@router.get("/{pid}/allergies/statements")
def get_allergy_statements(pid: str, user: User = Depends(current_user)):
    return get_allergies(pid, user)["statements"]


@router.get("/{pid}/allergies/conflicts")
def get_allergy_conflicts(pid: str, user: User = Depends(current_user)):
    return get_allergies(pid, user)["conflicts"]


def _typed(pid, user, ftype):
    with connection() as conn:
        require_patient(conn, user, pid)
        items = get_findings(conn, pid, "f.finding_type=? AND f.verification_status!='rejected'", (ftype,))
        for it in items:
            it["summary"] = views.summarise(it)
        items.sort(key=lambda f: (f["date_iso"] or "9999", f["document_id"], f["line_start"]))
        return items


@router.get("/{pid}/investigations")
def get_investigations(pid: str, user: User = Depends(current_user)):
    return _typed(pid, user, "investigation")


@router.get("/{pid}/conditions")
def get_conditions(pid: str, user: User = Depends(current_user)):
    return _typed(pid, user, "condition")


@router.get("/{pid}/events")
def get_events(pid: str, user: User = Depends(current_user)):
    return _typed(pid, user, "event")
