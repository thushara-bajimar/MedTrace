"""Read-side reconstruction: chronological timeline, medication history and allergy summary.

Everything here is *derived on read* from the current finding versions, so corrections
and new documents are reflected immediately and no derived state can drift from evidence."""
from __future__ import annotations

import sqlite3

from .db import rows
from .extract.dates import sort_key
from .store import get_findings

MED_STATUS_LABEL = {
    "prescribed": "Prescribed (as of record date)",
    "documented_ongoing": "Documented as ongoing",
    "documented_stopped": "Documented as stopped",
    "documented_changed": "Documented as changed",
    "historical": "Historical mention",
    "uncertain": "Uncertain (as documented)",
    "mentioned_only": "Mentioned only",
    "unknown": "Unknown",
}
COND_STATUS_LABEL = {
    "confirmed_as_documented": "documented diagnosis", "suspected": "suspected", "possible": "possible", "ruled_out": "ruled out",
    "history_of": "history of", "known_case": "known case", "explicitly_denied": "explicitly denied",
}
ALLERGY_LABEL = {
    "documented_allergy": "Allergy documented", "explicitly_denied_specific": "Explicitly denied (specific substance)",
    "explicitly_denied_general": "Explicit negative (no known allergies)", "status_not_recorded": "Allergy status explicitly not recorded",
}


def summarise(f: dict) -> str:
    d, t = f["details"], f["finding_type"]
    if t == "medication":
        parts = [d.get("name_as_written"), d.get("strength"), d.get("dosage"), d.get("route"), d.get("frequency"), d.get("duration")]
        txt = " ".join(p for p in parts if p)
        return f"{txt} - {MED_STATUS_LABEL.get(d.get('status'), d.get('status'))}"
    if t == "condition":
        return f"{d.get('name_as_written')} ({COND_STATUS_LABEL.get(d.get('status_as_documented'), d.get('status_as_documented'))})"
    if t == "allergy":
        a = d.get("assertion")
        if a == "documented_allergy":
            extra = ", ".join(x for x in [d.get("reaction"), d.get("severity")] if x)
            return f"Allergy documented: {d.get('substance')}" + (f" ({extra})" if extra else " (reaction not documented)")
        if a == "explicitly_denied_specific":
            return f"Explicitly denied allergy to {d.get('substance')} (this record)"
        if a == "explicitly_denied_general":
            return f"Explicit negative: '{f['original_text']}' (this record)"
        return "Allergy status explicitly not recorded in this record"
    if t == "investigation":
        if d.get("category") == "imaging":
            return f"{d.get('test_name')}: {d.get('value_text') or 'result not documented'}"
        s = f"{d.get('test_name')}: {d.get('value_text')} {d.get('unit') or ''}".strip()
        if d.get("reference_range"):
            s += f" (ref {d['reference_range']})"
        if d.get("flag_as_written"):
            s += f" [{d['flag_as_written']} as printed]"
        return s
    if t == "event":
        return d.get("description", "")
    return ""


def _conflicted_ids(conn: sqlite3.Connection, patient_id: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in rows(conn, """SELECT cf.finding_id, c.id FROM conflict_findings cf JOIN conflicts c ON c.id = cf.conflict_id
                           WHERE c.patient_id=? AND c.still_detected=1 AND c.status IN ('unresolved','reviewed','insufficient_information')""",
                  (patient_id,)):
        out.setdefault(r["finding_id"], []).append(r["id"])
    return out


def date_kind(f: dict) -> str:
    s = f["date_status"]
    if s in ("parsed", "partial") and f.get("date_role") not in ("documented_in_record_dated",):
        return "event_date"
    if s in ("document_date",) or f.get("date_role") == "documented_in_record_dated":
        return "document_date"
    if s == "ambiguous":
        return "ambiguous"
    return "unknown"


def timeline(conn: sqlite3.Connection, patient_id: str, types: list[str] | None = None, date_from: str | None = None,
             date_to: str | None = None, document_id: str | None = None, verification: str | None = None,
             q: str | None = None) -> dict:
    findings = get_findings(conn, patient_id, "f.verification_status != 'rejected'")
    conflicted = _conflicted_ids(conn, patient_id)
    entries = []
    for f in findings:
        etype = f["details"].get("event_type") if f["finding_type"] == "event" else f["finding_type"]
        e = {
            "id": f["id"], "finding_type": f["finding_type"], "event_type": etype, "summary": summarise(f),
            "date_text": f["date_text"], "date_iso": f["date_iso"], "date_status": f["date_status"], "date_kind": date_kind(f),
            "date_role": f["date_role"], "date_candidates": f["date_candidates"], "temporal_status": f["temporal_status"],
            "document_id": f["document_id"], "document_filename": f["document_filename"], "document_type": f["document_type"],
            "document_date_text": f["document_date_text"], "upload_date": f["document_upload_date"],
            "page": f["page_number"], "line": f["line_start"], "passage": f["source_passage"],
            "confidence_label": f["confidence_label"], "confidence_score": f["confidence_score"],
            "verification_status": f["verification_status"], "provenance_type": f["provenance_type"],
            "conflict_ids": conflicted.get(f["id"], []),
        }
        entries.append(e)
    if types:
        entries = [e for e in entries if e["finding_type"] in types or e["event_type"] in types]
    if document_id:
        entries = [e for e in entries if e["document_id"] == document_id]
    if verification:
        entries = [e for e in entries if e["verification_status"] == verification]
    if q:
        ql = q.lower()
        entries = [e for e in entries if ql in e["summary"].lower() or ql in e["passage"].lower()]
    if date_from:
        entries = [e for e in entries if e["date_iso"] and sort_key(e["date_iso"]) >= date_from]
    if date_to:
        entries = [e for e in entries if e["date_iso"] and sort_key(e["date_iso"]) <= date_to + "-99"]
    dated = sorted([e for e in entries if e["date_iso"]], key=lambda e: (sort_key(e["date_iso"]), e["document_id"], e["page"], e["line"]))
    undated = [e for e in entries if not e["date_iso"]]
    return {"dated": dated, "undated_or_ambiguous": undated,
            "note": "Ordered by documented event dates; when a finding has no own date, the document date is used and marked as such. "
                    "Upload dates are never used as event dates. Ambiguous or missing dates are listed separately rather than guessed."}


def medication_history(conn: sqlite3.Connection, patient_id: str) -> dict:
    meds = get_findings(conn, patient_id, "f.finding_type='medication' AND f.verification_status != 'rejected'")
    conflicted = _conflicted_ids(conn, patient_id)
    by_name: dict[str, list[dict]] = {}
    for f in meds:
        key = f["details"].get("normalized_name") or (f["details"].get("name_as_written") or "").lower()
        by_name.setdefault(key, []).append(f)
    out = []
    for name, group in sorted(by_name.items()):
        group.sort(key=lambda f: (sort_key(f["date_iso"]), f["document_id"]))
        mentions, changes = [], []
        prev = None
        for f in group:
            d = f["details"]
            mentions.append({
                "finding_id": f["id"], "name_as_written": d.get("name_as_written"), "normalized_name": d.get("normalized_name"),
                "strength": d.get("strength"), "dosage": d.get("dosage"), "route": d.get("route"), "frequency": d.get("frequency"),
                "duration": d.get("duration"), "start_date_text": d.get("start_date_text"), "stop_date_text": d.get("stop_date_text"),
                "status": d.get("status"), "status_label": MED_STATUS_LABEL.get(d.get("status")),
                "date_text": f["date_text"], "date_iso": f["date_iso"], "date_status": f["date_status"], "date_kind": date_kind(f),
                "document_id": f["document_id"], "document_filename": f["document_filename"], "document_type": f["document_type"],
                "page": f["page_number"], "line": f["line_start"], "passage": f["source_passage"],
                "verification_status": f["verification_status"], "confidence_label": f["confidence_label"],
                "conflict_ids": conflicted.get(f["id"], []),
            })
            if d.get("status") in ("documented_changed", "documented_stopped"):
                changes.append({"finding_id": f["id"], "kind": d.get("status"), "date_text": f["date_text"], "passage": f["source_passage"],
                                "document_filename": f["document_filename"], "page": f["page_number"]})
            elif prev is not None and f["date_iso"] and prev["date_iso"] and f["date_iso"] != prev["date_iso"]:
                pd_ = prev["details"]
                if (pd_.get("strength") or "").replace(" ", "").lower() != (d.get("strength") or "").replace(" ", "").lower() and pd_.get("strength") and d.get("strength"):
                    changes.append({"finding_id": f["id"], "kind": "strength_differs_from_previous_record",
                                    "date_text": f["date_text"], "passage": f["source_passage"], "document_filename": f["document_filename"],
                                    "page": f["page_number"], "previous": pd_.get("strength"), "current": d.get("strength")})
            prev = f
        latest = mentions[-1] if mentions else None
        explicit_current = latest is not None and latest["status"] == "documented_ongoing"
        out.append({
            "medication": name, "mentions": mentions, "documented_changes": changes,
            "latest_documented_status": latest["status_label"] if latest else None,
            "latest_documented_date": latest["date_text"] if latest else None,
            "current_status_note": ("Latest record explicitly documents it as ongoing (as of that record's date)." if explicit_current else
                                    "Current use is NOT established by the records; only the documented statuses above are known."),
        })
    return {"medications": out}


def allergy_summary(conn: sqlite3.Connection, patient_id: str) -> dict:
    findings = get_findings(conn, patient_id, "f.finding_type='allergy' AND f.verification_status != 'rejected'")
    conflicted = _conflicted_ids(conn, patient_id)
    statements = []
    for f in findings:
        d = f["details"]
        statements.append({
            "finding_id": f["id"], "assertion": d.get("assertion"), "assertion_label": ALLERGY_LABEL.get(d.get("assertion")),
            "substance": d.get("substance"), "normalized_substance": d.get("normalized_substance"), "reaction": d.get("reaction"),
            "severity": d.get("severity"), "date_text": f["date_text"], "date_iso": f["date_iso"], "document_id": f["document_id"],
            "document_filename": f["document_filename"], "document_type": f["document_type"], "page": f["page_number"],
            "line": f["line_start"], "passage": f["source_passage"], "verification_status": f["verification_status"],
            "conflict_ids": conflicted.get(f["id"], []),
        })
    docs = rows(conn, "SELECT id, original_filename, doc_type, document_date_text FROM documents WHERE patient_id=? AND extraction_status='completed'",
                (patient_id,))
    per_doc = []
    for d in docs:
        st = [s for s in statements if s["document_id"] == d["id"]]
        if not st:
            status = "not_documented"
        elif any(s["assertion"] == "documented_allergy" for s in st):
            status = "allergy_documented"
        elif any(s["assertion"].startswith("explicitly_denied") for s in st):
            status = "explicit_negative"
        else:
            status = "status_not_recorded"
        per_doc.append({"document_id": d["id"], "document_filename": d["original_filename"], "document_type": d["doc_type"],
                        "document_date_text": d["document_date_text"], "allergy_documentation": status})
    conflicts = rows(conn, "SELECT * FROM conflicts WHERE patient_id=? AND category='allergy' AND still_detected=1", (patient_id,),
                     json_fields=("evidence_json",))
    return {"statements": statements, "per_document": per_doc, "conflicts": conflicts,
            "note": "Absence of an allergy statement in a document is shown as 'not documented' and is never treated as 'no allergies'."}
