"""Gap (missing / uncertain information) detection.

A gap is a statement about the *documentation*, never about the patient: "dosage not
documented" does not mean "no dosage". Gaps are derived data and are recomputed after
each document is processed or corrected."""
from __future__ import annotations

import json

from ..db import new_id, now_iso, rows, transaction
from ..extract.lexicon import normalise_unit_key
from ..store import get_findings

ALLERGY_EXPECTED_DOCS = {"discharge_summary", "consultation_note", "prescription"}


def compute_gaps(docs: list[dict], findings: list[dict]) -> list[dict]:
    gaps = []

    def add(gtype, desc, doc_id=None, fid=None):
        gaps.append({"gap_type": gtype, "description": desc, "document_id": doc_id, "finding_id": fid})

    for d in docs:
        if d["extraction_status"] != "completed":
            continue
        if d["document_date_status"] == "missing":
            add("document_date_missing", "No document date could be found in this document.", d["id"])
        elif d["document_date_status"] == "ambiguous":
            add("date_ambiguous", f"Document date '{d['document_date_text']}' is ambiguous (DD/MM vs MM/DD); it was not interpreted.", d["id"])
        if d["ocr_mean_confidence"] is not None and d["ocr_mean_confidence"] < 0.85:
            add("ocr_low_confidence", f"OCR mean confidence {d['ocr_mean_confidence']:.2f}; verify extracted values against the image.", d["id"])
        if d["injection_flags"]:
            n = len(json.loads(d["injection_flags"]))
            add("instruction_like_text", f"{n} instruction-like passage(s) found. They were treated as document data and ignored for extraction.", d["id"])
        doc_allergy = [f for f in findings if f["document_id"] == d["id"] and f["finding_type"] == "allergy"]
        if d["doc_type"] in ALLERGY_EXPECTED_DOCS and not doc_allergy:
            add("allergy_status_not_documented", "This document contains no allergy statement. This is NOT evidence of no allergies.", d["id"])

    for f in findings:
        det, t = f["details"], f["finding_type"]
        label = det.get("name_as_written") or det.get("test_name") or det.get("substance") or det.get("description") or t
        if f["date_status"] == "ambiguous":
            add("date_ambiguous", f"{t.title()} '{label}': date '{f['date_text']}' is ambiguous and was not interpreted.", f["document_id"], f["id"])
        if t == "medication":
            if not det.get("strength"):
                add("medication_dosage_not_documented", f"{label}: strength/dose not documented.", f["document_id"], f["id"])
            if not det.get("frequency") and det.get("status") in ("prescribed", "documented_ongoing", "documented_changed"):
                add("medication_frequency_not_documented", f"{label}: frequency not documented.", f["document_id"], f["id"])
            if det.get("status") in ("uncertain", "mentioned_only", "unknown"):
                add("medication_status_uncertain", f"{label}: status documented as '{det.get('status')}'; whether it is being taken is not established.",
                    f["document_id"], f["id"])
            if f["date_status"] == "missing":
                add("finding_date_missing", f"{label}: no date documented for this medication mention.", f["document_id"], f["id"])
        elif t == "allergy":
            if det.get("assertion") == "documented_allergy" and not det.get("reaction"):
                add("allergy_reaction_not_documented", f"Allergy to {label}: reaction not documented.", f["document_id"], f["id"])
            if det.get("assertion") == "status_not_recorded":
                add("allergy_status_not_recorded", "Document explicitly states allergy status was not recorded.", f["document_id"], f["id"])
        elif t == "investigation":
            if det.get("category") == "laboratory" and not det.get("reference_range"):
                add("reference_range_missing", f"{label}: reference range not documented.", f["document_id"], f["id"])
            if f["date_status"] == "missing":
                add("finding_date_missing", f"{label}: test date not documented.", f["document_id"], f["id"])
        elif t == "event":
            if f["date_status"] == "missing" and det.get("event_type") != "follow_up":
                add("event_date_missing", f"Event '{label}': date not documented; chronology is uncertain.", f["document_id"], f["id"])

    # same test documented in different units across records (preserved, not converted)
    units: dict[str, set[str]] = {}
    for f in findings:
        if f["finding_type"] == "investigation" and f["details"].get("unit"):
            units.setdefault(f["details"].get("normalized_test") or "", set()).add(normalise_unit_key(f["details"]["unit"]))
    for test, us in units.items():
        if len(us) > 1:
            add("unit_difference", f"{test}: documented in different units across records ({', '.join(sorted(us))}). Original units are preserved; "
                                   "values are not compared without an explicit conversion.")
    return gaps


def detect_for_patient(patient_id: str) -> None:
    with transaction() as conn:
        docs = rows(conn, "SELECT * FROM documents WHERE patient_id=?", (patient_id,))
        findings = get_findings(conn, patient_id, "f.verification_status != 'rejected'")
        gaps = compute_gaps(docs, findings)
        conn.execute("DELETE FROM gaps WHERE patient_id=?", (patient_id,))
        for g in gaps:
            conn.execute("INSERT INTO gaps (id, patient_id, document_id, finding_id, gap_type, description, detected_at) VALUES (?,?,?,?,?,?,?)",
                         (new_id("gap"), patient_id, g["document_id"], g["finding_id"], g["gap_type"], g["description"], now_iso()))
