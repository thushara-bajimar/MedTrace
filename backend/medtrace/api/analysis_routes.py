"""Conflicts, duplicates, gaps, human review and records-only question answering."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import views
from ..analysis import conflicts as conflict_mod, duplicates as dup_mod, gaps as gap_mod
from ..corrections import review_finding
from ..db import connection, new_id, now_iso, one, rows, transaction
from ..qa.engine import MAX_QUESTION_CHARS, answer_question
from ..security import User, audit, current_user, require_patient
from ..store import get_findings

router = APIRouter(prefix="/api/patients/{pid}", tags=["analysis"])

CONFLICT_STATUSES = ("unresolved", "reviewed", "resolved_by_documented_evidence", "not_a_contradiction", "insufficient_information")


class ConflictReviewIn(BaseModel):
    status: Literal["unresolved", "reviewed", "resolved_by_documented_evidence", "not_a_contradiction", "insufficient_information"]
    note: str | None = Field(default=None, max_length=1000)


class DuplicateReviewIn(BaseModel):
    decision: Literal["confirmed_duplicate", "not_duplicate", "pending"]


class FindingReviewIn(BaseModel):
    action: Literal["verify", "correct", "reject"]
    changes: dict | None = None
    reason: str | None = Field(default=None, max_length=500)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


# ---------------------------------------------------------------- conflicts
@router.get("/conflicts")
def list_conflicts(pid: str, status: str | None = None, include_stale: bool = False, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        sql = "SELECT * FROM conflicts WHERE patient_id=?" + ("" if include_stale else " AND still_detected=1")
        params: list = [pid]
        if status:
            sql += " AND status=?"
            params.append(status)
        out = rows(conn, sql + " ORDER BY detected_at", params, json_fields=("evidence_json",))
        for c in out:
            c["resolutions"] = rows(conn, """SELECT r.previous_status, r.new_status, r.note, r.created_at, u.username AS reviewer
                                             FROM conflict_resolutions r LEFT JOIN users u ON u.id=r.reviewer_id WHERE r.conflict_id=? ORDER BY r.created_at""", (c["id"],))
        return out


@router.post("/conflicts/detect")
def detect_conflicts(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid, write=True)
    conflict_mod.detect_for_patient(pid)
    return list_conflicts(pid, user=user)


@router.get("/conflicts/{cid}")
def get_conflict(pid: str, cid: str, user: User = Depends(current_user)):
    for c in list_conflicts(pid, include_stale=True, user=user):
        if c["id"] == cid:
            return c
    raise HTTPException(404, "Conflict not found.")


@router.post("/conflicts/{cid}/review")
def review_conflict(pid: str, cid: str, body: ConflictReviewIn, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        c = one(conn, "SELECT * FROM conflicts WHERE id=? AND patient_id=?", (cid, pid))
        if c is None:
            raise HTTPException(404, "Conflict not found.")
        if body.status in ("resolved_by_documented_evidence", "not_a_contradiction") and not (body.note or "").strip():
            raise HTTPException(400, "Explain the resolution (which documented evidence supports it).")
        conn.execute("INSERT INTO conflict_resolutions (id, conflict_id, patient_id, previous_status, new_status, note, reviewer_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (new_id("res"), cid, pid, c["status"], body.status, body.note, user.id, now_iso()))
        conn.execute("UPDATE conflicts SET status=?, updated_at=? WHERE id=?", (body.status, now_iso(), cid))
        audit(conn, user.id, "conflict_review", patient_id=pid, resource_id=cid)
    return get_conflict(pid, cid, user)


# ---------------------------------------------------------------- duplicates
@router.get("/duplicates")
def list_duplicates(pid: str, level: str | None = None, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        sql = "SELECT * FROM duplicate_candidates WHERE patient_id=?" + (" AND level=?" if level else "")
        out = rows(conn, sql + " ORDER BY level, similarity DESC", (pid, level) if level else (pid,), json_fields=("details_json",))
        docs = {d["id"]: d for d in rows(conn, "SELECT id, original_filename, doc_type, document_date_text FROM documents WHERE patient_id=?", (pid,))}
        findings = {f["id"]: f for f in get_findings(conn, pid)} if any(o["level"] == "finding" for o in out) else {}
        for o in out:
            if o["level"] == "document":
                o["a"], o["b"] = docs.get(o["item_a"]), docs.get(o["item_b"])
            else:
                for side, key in (("a", "item_a"), ("b", "item_b")):
                    f = findings.get(o[key])
                    o[side] = {"id": f["id"], "summary": views.summarise(f), "document_filename": f["document_filename"], "page": f["page_number"],
                               "passage": f["source_passage"], "date_text": f["date_text"], "document_id": f["document_id"]} if f else None
        return out


@router.post("/duplicates/{dup_id}/review")
def review_duplicate(pid: str, dup_id: str, body: DuplicateReviewIn, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        if not one(conn, "SELECT id FROM duplicate_candidates WHERE id=? AND patient_id=?", (dup_id, pid)):
            raise HTTPException(404, "Duplicate candidate not found.")
        conn.execute("UPDATE duplicate_candidates SET review_status=?, reviewed_by=?, reviewed_at=? WHERE id=?", (body.decision, user.id, now_iso(), dup_id))
        audit(conn, user.id, "duplicate_review", patient_id=pid, resource_id=dup_id)
    return {"ok": True, "note": "Review recorded. Documents and findings are never merged or deleted automatically."}


# ---------------------------------------------------------------- gaps + review
@router.get("/gaps")
def list_gaps(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return rows(conn, """SELECT g.*, d.original_filename AS document_filename FROM gaps g LEFT JOIN documents d ON d.id=g.document_id
                             WHERE g.patient_id=? ORDER BY g.gap_type""", (pid,))


@router.get("/review")
def review_queue(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        findings = get_findings(conn, pid, include_inactive=False)
        for f in findings:
            f["summary"] = views.summarise(f)
        slim = lambda f: {k: f[k] for k in ("id", "finding_type", "summary", "document_id", "document_filename", "page_number", "line_start",  # noqa: E731
                                            "source_passage", "date_text", "date_status", "confidence_label", "confidence_score",
                                            "confidence_reasons", "verification_status", "provenance_type", "extraction_method")}
        corrections = rows(conn, """SELECT v.finding_id, v.version, v.reason, v.created_at, u.username AS reviewer, f.finding_type
                                    FROM finding_versions v JOIN findings f ON f.id=v.finding_id LEFT JOIN users u ON u.id=v.created_by
                                    WHERE v.patient_id=? AND v.origin='human' ORDER BY v.created_at DESC LIMIT 100""", (pid,))
        return {
            "unverified": [slim(f) for f in findings if f["verification_status"] == "unverified"],
            "low_confidence": [slim(f) for f in findings if f["confidence_label"] == "low" and f["verification_status"] == "unverified"],
            "date_ambiguities": [slim(f) for f in findings if f["date_status"] == "ambiguous"],
            "duplicates_pending": [d for d in list_duplicates(pid, "document", user) if d["review_status"] == "pending"],
            "conflicts_open": [c for c in list_conflicts(pid, user=user) if c["status"] == "unresolved"],
            "human_reviews": corrections,
        }


@router.post("/findings/{fid}/review")
def post_review(pid: str, fid: str, body: FindingReviewIn, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        result = review_finding(conn, pid, fid, user.id, body.action, body.changes, body.reason)
        audit(conn, user.id, f"finding_{body.action}", patient_id=pid, resource_id=fid)
    # downstream derived data is refreshed so timeline / conflicts reflect the correction
    dup_mod.detect_for_patient(pid)
    conflict_mod.detect_for_patient(pid)
    gap_mod.detect_for_patient(pid)
    result["summary"] = views.summarise(result)
    return result


# ---------------------------------------------------------------- records-only QA
@router.post("/ask")
def ask(pid: str, body: AskIn, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, pid)
        ans = answer_question(conn, pid, body.question)
        qid = new_id("qa")
        conn.execute("INSERT INTO qa_logs (id, patient_id, user_id, question, retrieval_status, answer_json, created_at) VALUES (?,?,?,?,?,?,?)",
                     (qid, pid, user.id, body.question, ans["retrieval_status"], json.dumps(ans), now_iso()))
        audit(conn, user.id, "records_question", patient_id=pid, resource_id=qid)
    ans["id"] = qid
    return ans


@router.get("/ask/history")
def ask_history(pid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        return rows(conn, "SELECT id, question, retrieval_status, created_at FROM qa_logs WHERE patient_id=? AND user_id=? ORDER BY created_at DESC, rowid DESC LIMIT 50",
                    (pid, user.id))


@router.get("/ask/{qid}")
def ask_get(pid: str, qid: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        r = one(conn, "SELECT * FROM qa_logs WHERE id=? AND patient_id=?", (qid, pid), json_fields=("answer_json",))
        if r is None:
            raise HTTPException(404, "Answer not found.")
        return dict(r["answer_json"], id=qid)


@router.get("/ask/{qid}/evidence")
def ask_evidence(pid: str, qid: str, user: User = Depends(current_user)):
    a = ask_get(pid, qid, user)
    return {"citations": a["citations"], "facts": a["facts"]}


@router.get("/ask/{qid}/uncertainty")
def ask_uncertainty(pid: str, qid: str, user: User = Depends(current_user)):
    a = ask_get(pid, qid, user)
    return {"retrieval_status": a["retrieval_status"], "uncertainty": a["uncertainty"], "conflicts": a["conflicts"]}
