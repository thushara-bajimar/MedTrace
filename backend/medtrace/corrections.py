"""Human review: verify, correct or reject findings; correct page text and document type.

Invariants
* Version 1 of every finding is the machine extraction and is never modified.
* ``findings.source_passage`` / ``original_text`` (the verbatim evidence) are immutable.
* A correction appends a new version (origin=human) with reviewer, timestamp and reason,
  and updates the typed detail row so timeline / QA reflect it immediately.
"""
from __future__ import annotations

import json
import re
import sqlite3

from fastapi import HTTPException

from .db import new_id, now_iso, one, rows
from .store import EDITABLE, get_finding, write_details

RX_ISO_PARTIAL = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
ENUMS = {
    "status": {"prescribed", "documented_ongoing", "documented_stopped", "documented_changed", "historical", "uncertain", "mentioned_only", "unknown"},
    "status_as_documented": {"confirmed_as_documented", "suspected", "possible", "ruled_out", "history_of", "known_case", "explicitly_denied"},
    "assertion": {"documented_allergy", "explicitly_denied_specific", "explicitly_denied_general", "status_not_recorded"},
    "category": {"laboratory", "imaging", "other"},
    "event_type": {"admission", "discharge", "surgery", "procedure", "consultation", "investigation", "follow_up", "documented_event"},
}
DOC_TYPES = {"lab_report", "prescription", "discharge_summary", "consultation_note", "imaging_report", "unclassified"}


def _latest_data(conn: sqlite3.Connection, finding_id: str) -> tuple[int, dict]:
    v = one(conn, "SELECT version, data_json FROM finding_versions WHERE finding_id=? ORDER BY version DESC LIMIT 1", (finding_id,))
    return v["version"], json.loads(v["data_json"])


def review_finding(conn: sqlite3.Connection, patient_id: str, finding_id: str, user_id: str, action: str,
                   changes: dict | None, reason: str | None) -> dict:
    f = get_finding(conn, patient_id, finding_id)
    if f is None:
        raise HTTPException(404, "Finding not found.")
    version, data = _latest_data(conn, finding_id)
    reason = (reason or "").strip()[:500] or None
    if action == "verify":
        conn.execute("UPDATE findings SET verification_status='human_verified' WHERE id=?", (finding_id,))
        _append_version(conn, f, version + 1, data, f["date_text"], f["date_iso"], f"verified as matching source{': ' + reason if reason else ''}", user_id)
    elif action == "reject":
        if not reason:
            raise HTTPException(400, "A reason is required to reject a finding.")
        conn.execute("UPDATE findings SET verification_status='rejected' WHERE id=?", (finding_id,))
        _append_version(conn, f, version + 1, data, f["date_text"], f["date_iso"], f"rejected: {reason}", user_id)
    elif action == "correct":
        changes = changes or {}
        allowed = set(EDITABLE[f["finding_type"]]) | {"date_text", "date_iso"}
        bad = set(changes) - allowed
        if bad:
            raise HTTPException(400, f"Fields not editable for {f['finding_type']}: {', '.join(sorted(bad))}")
        if not changes:
            raise HTTPException(400, "No changes supplied.")
        new = dict(data)
        for k, v in changes.items():
            if k in ("date_text", "date_iso"):
                continue
            if isinstance(v, str):
                v = v.strip()[:300] or None
            if k in ENUMS and v is not None and v not in ENUMS[k]:
                raise HTTPException(400, f"Invalid value for {k}.")
            if k == "value_numeric" and v is not None:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(400, "value_numeric must be a number.")
            new[k] = v
        date_text = changes.get("date_text", f["date_text"])
        date_iso = changes.get("date_iso", f["date_iso"])
        if date_iso is not None and date_iso != "" and not RX_ISO_PARTIAL.match(str(date_iso)):
            raise HTTPException(400, "date_iso must be YYYY, YYYY-MM or YYYY-MM-DD.")
        date_iso = date_iso or None
        if not reason:
            raise HTTPException(400, "A correction reason is required.")
        date_status = f["date_status"]
        if "date_iso" in changes or "date_text" in changes:
            if date_iso:
                date_status = "parsed" if len(date_iso) == 10 else "partial"
            elif date_text:
                date_status = f["date_status"] if date_text == f["date_text"] and f["date_status"] == "ambiguous" else "unparsed"
            else:
                date_status = "missing"
        conn.execute(
            """UPDATE findings SET verification_status='corrected', provenance_type='human_correction', current_version=?,
               date_text=?, date_iso=?, date_status=?, date_precision=? WHERE id=?""",
            (version + 1, date_text, date_iso, date_status,
             ("day" if date_iso and len(date_iso) == 10 else "month" if date_iso and len(date_iso) == 7 else "year" if date_iso else None),
             finding_id),
        )
        write_details(conn, finding_id, f["finding_type"], new)
        _append_version(conn, f, version + 1, new, date_text, date_iso, reason, user_id)
    else:
        raise HTTPException(400, "action must be verify, correct or reject.")
    return get_finding(conn, patient_id, finding_id)


def _append_version(conn, f, version, data, date_text, date_iso, reason, user_id):
    conn.execute(
        "INSERT INTO finding_versions (id, finding_id, patient_id, version, origin, data_json, date_text, date_iso, reason, created_by, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("fv"), f["id"], f["patient_id"], version, "human", json.dumps(data), date_text, date_iso, reason, user_id, now_iso()),
    )
    conn.execute("UPDATE findings SET current_version=? WHERE id=?", (version, f["id"]))


def finding_history(conn: sqlite3.Connection, patient_id: str, finding_id: str) -> list[dict]:
    out = rows(conn, """SELECT v.version, v.origin, v.data_json, v.date_text, v.date_iso, v.reason, v.created_at, u.username AS reviewer
                        FROM finding_versions v LEFT JOIN users u ON u.id = v.created_by
                        WHERE v.finding_id=? AND v.patient_id=? ORDER BY v.version""", (finding_id, patient_id), json_fields=("data_json",))
    return out


def correct_page_text(conn, patient_id: str, document_id: str, page_number: int, text: str, reason: str | None, user_id: str) -> None:
    page = one(conn, "SELECT * FROM document_pages WHERE document_id=? AND patient_id=? AND page_number=?", (document_id, patient_id, page_number))
    if page is None:
        raise HTTPException(404, "Page not found.")
    if not reason:
        raise HTTPException(400, "A correction reason is required.")
    text = text[:100_000]
    conn.execute("INSERT INTO page_text_corrections (id, page_id, patient_id, previous_text, corrected_text, reason, corrected_by, corrected_at)"
                 " VALUES (?,?,?,?,?,?,?,?)", (new_id("ptc"), page["id"], patient_id, page["text"], text, reason[:500], user_id, now_iso()))
    conn.execute("UPDATE document_pages SET text=?, text_source='human_corrected' WHERE id=?", (text, page["id"]))
    conn.execute("UPDATE documents SET text_source_summary='human_corrected' WHERE id=?", (document_id,))


def set_document_type(conn, patient_id: str, document_id: str, doc_type: str) -> None:
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, "Unknown document type.")
    d = one(conn, "SELECT * FROM documents WHERE id=? AND patient_id=?", (document_id, patient_id))
    if d is None:
        raise HTTPException(404, "Document not found.")
    conn.execute("UPDATE documents SET doc_type=?, doc_type_source='human', doc_type_original=COALESCE(doc_type_original, ?) WHERE id=?",
                 (doc_type, d["doc_type"], document_id))
