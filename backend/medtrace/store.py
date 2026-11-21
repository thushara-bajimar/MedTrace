"""Persistence helpers for findings: append-only versions + typed detail rows."""
from __future__ import annotations

import json
import sqlite3

from .db import new_id, now_iso, one, rows

DETAIL_TABLES = {
    "condition": ("condition_details", ["name_as_written", "normalized_name", "status_as_documented", "classification"]),
    "medication": ("medication_details", ["name_as_written", "normalized_name", "strength", "dosage", "route", "frequency",
                                           "duration", "start_date_text", "stop_date_text", "status"]),
    "allergy": ("allergy_details", ["substance", "normalized_substance", "reaction", "severity", "assertion"]),
    "investigation": ("investigation_details", ["test_name", "normalized_test", "category", "value_text", "value_numeric", "unit",
                                                 "reference_range", "flag_as_written", "converted_value", "converted_unit", "conversion_rule"]),
    "event": ("event_details", ["event_type", "description"]),
}

# Fields a reviewer may correct per type (plus date_text / date_iso on the finding itself).
EDITABLE = {t: [f for f in fields if f not in {"converted_value", "converted_unit", "conversion_rule"}] for t, (_, fields) in DETAIL_TABLES.items()}


def write_details(conn: sqlite3.Connection, finding_id: str, ftype: str, data: dict) -> None:
    table, fields = DETAIL_TABLES[ftype]
    conn.execute(f"DELETE FROM {table} WHERE finding_id = ?", (finding_id,))
    conn.execute(
        f"INSERT INTO {table} (finding_id, {', '.join(fields)}) VALUES (?{', ?' * len(fields)})",
        (finding_id, *[data.get(f) for f in fields]),
    )


def insert_finding(conn: sqlite3.Connection, patient_id: str, document_id: str, run_id: str, raw, label: str) -> str:
    fid = new_id("fnd")
    d = raw.date
    provenance = "ocr_extraction" if raw.extraction_method == "rules_ocr_text" else "direct_extraction"
    conn.execute(
        """INSERT INTO findings (id, patient_id, document_id, run_id, finding_type, section, current_version, verification_status,
           confidence_score, confidence_label, confidence_reasons, extraction_method, provenance_type, page_number, line_start, line_end,
           source_passage, original_text, date_text, date_iso, date_precision, date_status, date_candidates, date_role, temporal_status,
           is_active, created_at)
           VALUES (?,?,?,?,?,?,1,'unverified',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
        (fid, patient_id, document_id, run_id, raw.finding_type, raw.section, raw.confidence, label, json.dumps(raw.reasons),
         raw.extraction_method, provenance, raw.page, raw.line_start, raw.line_end, raw.source_passage, raw.original_text,
         d.text if d else None, d.iso if d and d.status in ("parsed", "partial") else None, d.precision if d else None,
         raw.date_status if d else "missing", json.dumps(d.candidates) if d and d.candidates else None, raw.date_role,
         raw.temporal_status, now_iso()),
    )
    conn.execute(
        "INSERT INTO finding_versions (id, finding_id, patient_id, version, origin, data_json, date_text, date_iso, reason, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (new_id("fv"), fid, patient_id, 1, "machine", json.dumps(raw.data), d.text if d else None,
         d.iso if d and d.status in ("parsed", "partial") else None, "machine extraction", now_iso()),
    )
    write_details(conn, fid, raw.finding_type, raw.data)
    return fid


FINDING_SELECT = """
SELECT f.*, d.original_filename AS document_filename, d.doc_type AS document_type, d.document_date_text, d.document_date_iso,
       d.upload_date AS document_upload_date
FROM findings f JOIN documents d ON d.id = f.document_id
"""


def attach_details(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    by_type: dict[str, list[dict]] = {}
    for it in items:
        for k in ("confidence_reasons", "date_candidates"):
            if isinstance(it.get(k), str):
                it[k] = json.loads(it[k])
        by_type.setdefault(it["finding_type"], []).append(it)
    for ftype, group in by_type.items():
        table, fields = DETAIL_TABLES[ftype]
        ids = [g["id"] for g in group]
        details = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in rows(conn, f"SELECT * FROM {table} WHERE finding_id IN ({','.join('?' * len(chunk))})", chunk):
                details[r["finding_id"]] = {k: v for k, v in r.items() if k != "finding_id"}
        for g in group:
            g["details"] = details.get(g["id"], {})
    return items


def get_findings(conn: sqlite3.Connection, patient_id: str, where: str = "", params: tuple = (), include_inactive: bool = False) -> list[dict]:
    sql = FINDING_SELECT + " WHERE f.patient_id = ?" + ("" if include_inactive else " AND f.is_active = 1") + (" AND " + where if where else "")
    items = rows(conn, sql + " ORDER BY f.document_id, f.page_number, f.line_start", (patient_id, *params))
    return attach_details(conn, items)


def get_finding(conn: sqlite3.Connection, patient_id: str, finding_id: str) -> dict | None:
    r = one(conn, FINDING_SELECT + " WHERE f.patient_id = ? AND f.id = ?", (patient_id, finding_id))
    if r is None:
        return None
    return attach_details(conn, [r])[0]
