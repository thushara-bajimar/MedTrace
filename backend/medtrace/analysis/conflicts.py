"""Contradiction detection. Conflicts are surfaced for human review and never resolved
automatically. Detection is idempotent: a deterministic key prevents duplicates, and a
conflict that stops being detected (e.g. after a correction) keeps its history with
``still_detected = 0``.

Rules (all across *different* documents of the same patient):
* medication_dosage  - same medication, same documented day, different strength.
* medication_status  - same medication, same documented day, one record says stopped and
                       another says prescribed / ongoing.
* allergy            - a documented allergy to substance S vs. an explicit general negative
                       (e.g. NKDA) or an explicit negative for S.
* event_date         - same surgery/procedure documented with different dates, or an
                       admission/discharge documented with dates <= 7 days apart (likely the
                       same stay) that disagree.
* investigation_value- same test, same day, same unit, different value.
Different-day dose differences are treated as documented *changes*, not contradictions.
"""
from __future__ import annotations

import json
import re
from datetime import date
from itertools import combinations

from ..config import DETECTOR_VERSION
from ..db import new_id, now_iso, rows, transaction
from ..extract.lexicon import normalise_unit_key
from ..store import get_findings

ACTIVE_MED = {"prescribed", "documented_ongoing", "documented_changed"}


def _strength(s):
    return re.sub(r"\s+", "", s.lower()) if s else None


def _day(f):
    return f["date_iso"] if f["date_iso"] and len(f["date_iso"]) == 10 else None


def _evidence(f, value: str) -> dict:
    return {"finding_id": f["id"], "document_id": f["document_id"], "document_filename": f["document_filename"],
            "document_type": f["document_type"], "page": f["page_number"], "line": f["line_start"], "passage": f["source_passage"],
            "date_text": f["date_text"], "date_iso": f["date_iso"], "value": value}


def _years_or_days_differ(a: dict, b: dict) -> bool:
    ia, ib = a["date_iso"], b["date_iso"]
    if not ia or not ib:
        return False
    n = min(len(ia), len(ib))
    return ia[:n] != ib[:n]


def _days_apart(a: str, b: str) -> int | None:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return None


def _surgery_key(desc: str) -> str:
    words = re.findall(r"[a-z]+", desc.lower())
    stop = {"laparoscopic", "open", "elective", "emergency", "the", "of", "a", "an", "and", "with", "performed", "done", "under", "anaesthesia", "general"}
    return " ".join(w for w in words if w not in stop and len(w) > 2)


def find_conflicts(findings: list[dict]) -> list[dict]:
    out = []
    meds = [f for f in findings if f["finding_type"] == "medication"]
    by_med: dict[str, list[dict]] = {}
    for f in meds:
        name = f["details"].get("normalized_name") or (f["details"].get("name_as_written") or "").lower()
        by_med.setdefault(name, []).append(f)
    for name, group in by_med.items():
        for a, b in combinations(group, 2):
            if a["document_id"] == b["document_id"] or _day(a) is None or _day(a) != _day(b):
                continue
            sa, sb = a["details"].get("status"), b["details"].get("status")
            if sa in ACTIVE_MED and sb in ACTIVE_MED:
                xa, xb = _strength(a["details"].get("strength")), _strength(b["details"].get("strength"))
                if xa and xb and xa != xb:
                    out.append({"category": "medication_dosage", "findings": [a, b],
                                "explanation": f"{name}: different strengths documented for the same date ({a['date_text']}): "
                                               f"{a['details'].get('strength')} vs {b['details'].get('strength')}.",
                                "values": [a["details"].get("strength"), b["details"].get("strength")]})
            stopped = {"documented_stopped"}
            if (sa in stopped and sb in ACTIVE_MED) or (sb in stopped and sa in ACTIVE_MED):
                out.append({"category": "medication_status", "findings": [a, b],
                            "explanation": f"{name}: one record documents it as stopped and another as {sb if sa in stopped else sa} "
                                           f"for the same date ({a['date_text']}).", "values": [sa, sb]})

    allergies = [f for f in findings if f["finding_type"] == "allergy"]
    positives = [f for f in allergies if f["details"].get("assertion") == "documented_allergy"]
    negatives = [f for f in allergies if f["details"].get("assertion") in ("explicitly_denied_general", "explicitly_denied_specific")]
    for p in positives:
        ps = p["details"].get("normalized_substance") or (p["details"].get("substance") or "").lower()
        for n in negatives:
            if n["document_id"] == p["document_id"]:
                continue
            if n["details"]["assertion"] == "explicitly_denied_specific":
                ns = n["details"].get("normalized_substance") or (n["details"].get("substance") or "").lower()
                if ns != ps:
                    continue
                expl = f"Allergy to {p['details'].get('substance')} is documented in one record, while another explicitly denies an allergy to {n['details'].get('substance')}."
            else:
                expl = f"Allergy to {p['details'].get('substance')} is documented in one record, while another states '{n['original_text']}'."
            out.append({"category": "allergy", "findings": [p, n], "explanation": expl,
                        "values": [f"allergy: {p['details'].get('substance')}", n["original_text"]]})

    events = [f for f in findings if f["finding_type"] == "event" and f["date_iso"]]
    for a, b in combinations(events, 2):
        if a["document_id"] == b["document_id"]:
            continue
        ta, tb = a["details"]["event_type"], b["details"]["event_type"]
        if ta != tb:
            continue
        if ta in ("surgery", "procedure"):
            ka, kb = _surgery_key(a["details"]["description"]), _surgery_key(b["details"]["description"])
            if ka and ka == kb and _years_or_days_differ(a, b):
                out.append({"category": "event_date", "findings": [a, b],
                            "explanation": f"'{a['details']['description']}' is documented with different dates: {a['date_text']} vs {b['date_text']}.",
                            "values": [a["date_text"], b["date_text"]]})
        elif ta in ("admission", "discharge") and _day(a) and _day(b) and _day(a) != _day(b):
            gap = _days_apart(_day(a), _day(b))
            if gap is not None and gap <= 7:
                out.append({"category": "event_date", "findings": [a, b],
                            "explanation": f"{ta.title()} date differs between records ({a['date_text']} vs {b['date_text']}, {gap} days apart); "
                                           f"they may describe the same stay.", "values": [a["date_text"], b["date_text"]]})

    inv = [f for f in findings if f["finding_type"] == "investigation" and f["details"].get("category") == "laboratory"]
    for a, b in combinations(inv, 2):
        if a["document_id"] == b["document_id"] or _day(a) is None or _day(a) != _day(b):
            continue
        da, db_ = a["details"], b["details"]
        if da.get("normalized_test") != db_.get("normalized_test") or not da.get("unit") or not db_.get("unit"):
            continue
        if normalise_unit_key(da["unit"]) == normalise_unit_key(db_["unit"]) and da.get("value_text") != db_.get("value_text"):
            out.append({"category": "investigation_value", "findings": [a, b],
                        "explanation": f"{da.get('test_name')} on {a['date_text']}: {da.get('value_text')} {da.get('unit')} vs "
                                       f"{db_.get('value_text')} {db_.get('unit')} in another record.",
                        "values": [f"{da.get('value_text')} {da.get('unit')}", f"{db_.get('value_text')} {db_.get('unit')}"]})
    return out


def detect_for_patient(patient_id: str) -> None:
    with transaction() as conn:
        findings = get_findings(conn, patient_id, "f.verification_status != 'rejected'")
        detected = find_conflicts(findings)
        keys = set()
        for c in detected:
            ids = sorted(f["id"] for f in c["findings"])
            key = c["category"] + "|" + "|".join(ids)
            keys.add(key)
            evidence = [_evidence(f, v) for f, v in zip(c["findings"], c["values"])]
            existing = conn.execute("SELECT id FROM conflicts WHERE patient_id=? AND conflict_key=?", (patient_id, key)).fetchone()
            if existing:
                conn.execute("UPDATE conflicts SET explanation=?, evidence_json=?, still_detected=1, updated_at=? WHERE id=?",
                             (c["explanation"], json.dumps(evidence), now_iso(), existing[0]))
                continue
            cid = new_id("cfl")
            conn.execute(
                """INSERT INTO conflicts (id, patient_id, conflict_key, category, explanation, evidence_json, status, still_detected,
                   detector_version, detected_at, updated_at) VALUES (?,?,?,?,?,?, 'unresolved', 1, ?,?,?)""",
                (cid, patient_id, key, c["category"], c["explanation"], json.dumps(evidence), DETECTOR_VERSION, now_iso(), now_iso()),
            )
            for fid in ids:
                conn.execute("INSERT OR IGNORE INTO conflict_findings (conflict_id, finding_id) VALUES (?,?)", (cid, fid))
        for r in rows(conn, "SELECT id, conflict_key FROM conflicts WHERE patient_id=? AND still_detected=1", (patient_id,)):
            if r["conflict_key"] not in keys:
                conn.execute("UPDATE conflicts SET still_detected=0, updated_at=? WHERE id=?", (now_iso(), r["id"]))
