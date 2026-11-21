"""Document processing pipeline.

Upload -> Validation -> Patient association -> Classification -> OCR/Text extraction ->
Structured extraction -> Evidence verification -> Duplicate detection -> Conflict detection
-> Timeline integration (timeline is derived on read from the current finding versions).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .analysis import conflicts as conflict_mod
from .analysis import duplicates as dup_mod
from .analysis import gaps as gap_mod
from .config import EXTRACTOR_VERSION, get_settings
from .db import new_id, now_iso, one, transaction
from .extract.extractor import SrcLine, extract_document, label_for
from .ingest.classify import classify_document
from .ingest.text_extraction import Line, extract_text
from .ingest.validation import ValidatedUpload
from .store import insert_finding

log = logging.getLogger("medtrace.pipeline")


def stored_path(patient_id: str, stored_filename: str) -> Path:
    base = get_settings().upload_dir.resolve()
    p = (base / patient_id / stored_filename).resolve()
    if base not in p.parents:  # defence in depth against path traversal
        raise ValueError("invalid storage path")
    return p


def register_upload(patient_id: str, up: ValidatedUpload, user_id: str | None) -> str:
    doc_id = new_id("doc")
    ext = {"pdf": "pdf", "png": "png", "jpeg": "jpg"}[up.file_format]
    stored = f"{doc_id}.{ext}"
    path = stored_path(patient_id, stored)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(up.data)
    with transaction() as conn:
        conn.execute(
            """INSERT INTO documents (id, patient_id, original_filename, stored_filename, file_format, mime_type, size_bytes, sha256,
               page_count, upload_date, uploaded_by, extraction_status) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'pending')""",
            (doc_id, patient_id, up.display_name, stored, up.file_format, up.mime_type, len(up.data), up.sha256, up.page_count,
             now_iso(), user_id),
        )
    return doc_id


def _verify_evidence(finding, lines_by_key: dict) -> bool:
    """Evidence verification: the verbatim span must occur in the referenced source line."""
    src = lines_by_key.get((finding.page, finding.line_start))
    return src is not None and finding.original_text.strip()[:40] in src.text


def process_document(document_id: str) -> None:
    t0 = time.perf_counter()
    stages: list[dict] = []
    with transaction() as conn:
        doc = one(conn, "SELECT * FROM documents WHERE id = ?", (document_id,))
        if doc is None:
            return
        run_id = new_id("run")
        # Re-processing never deletes earlier findings: they are marked inactive (superseded).
        conn.execute("UPDATE findings SET is_active = 0 WHERE document_id = ? AND verification_status = 'unverified'", (document_id,))
        conn.execute("UPDATE documents SET extraction_status='processing', error_message=NULL WHERE id=?", (document_id,))
        conn.execute("INSERT INTO processing_runs (id, document_id, patient_id, extractor_version, started_at, status) VALUES (?,?,?,?,?, 'running')",
                     (run_id, document_id, doc["patient_id"], EXTRACTOR_VERSION, now_iso()))
    patient_id = doc["patient_id"]

    def stage(name, fn):
        s = time.perf_counter()
        out = fn()
        stages.append({"stage": name, "ms": round((time.perf_counter() - s) * 1000, 1)})
        return out

    try:
        data = stored_path(patient_id, doc["stored_filename"]).read_bytes()
        result = stage("text_extraction_ocr", lambda: extract_text(data, doc["file_format"]))
        # Human-corrected page text takes precedence over machine text on re-processing.
        with transaction() as conn:
            corrected = {r["page_number"]: r["text"] for r in conn.execute(
                "SELECT page_number, text FROM document_pages WHERE document_id=? AND text_source='human_corrected'", (document_id,)).fetchall()}
        for p in result.pages:
            if p.page_number in corrected:
                p.lines = [Line(t, (0.0, 0.0, p.width, p.height), None, "human_corrected")
                           for t in corrected[p.page_number].splitlines() if t.strip()]
                p.source = "human_corrected"
        src_lines: list[SrcLine] = []
        for p in result.pages:
            for i, l in enumerate(p.lines):
                src_lines.append(SrcLine(p.page_number, i, l.text, l.source, l.confidence))
        full_text = "\n".join(l.text for l in src_lines)
        if doc["doc_type_source"] == "human":
            dtype, dconf = doc["doc_type"], doc["doc_type_confidence"]
        else:
            dtype, dconf, _scores = stage("classification", lambda: classify_document(full_text))
        meta, raw_findings = stage("structured_extraction", lambda: extract_document(src_lines, dtype))
        lines_by_key = {(l.page, l.index): l for l in src_lines}
        verified = [f for f in raw_findings if _verify_evidence(f, lines_by_key)]
        stages.append({"stage": "evidence_verification", "kept": len(verified), "dropped": len(raw_findings) - len(verified)})

        with transaction() as conn:
            conn.execute("DELETE FROM page_lines WHERE document_id=?", (document_id,))
            existing_pages = {r["page_number"]: r for r in conn.execute("SELECT * FROM document_pages WHERE document_id=?", (document_id,)).fetchall()}
            for p in result.pages:
                if p.page_number not in existing_pages:
                    conn.execute(
                        """INSERT INTO document_pages (id, document_id, patient_id, page_number, text, original_text, text_source,
                           original_text_source, ocr_confidence, width, height) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (new_id("pg"), document_id, patient_id, p.page_number, p.text, p.text, p.source, p.source, p.ocr_confidence, p.width, p.height),
                    )
                for i, l in enumerate(p.lines):
                    conn.execute(
                        "INSERT INTO page_lines (document_id, patient_id, page_number, line_index, text, x0, y0, x1, y1, confidence, source)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (document_id, patient_id, p.page_number, i, l.text, *l.bbox, l.confidence, l.source),
                    )
            dd = meta.doc_date
            if dd is None:
                date_status = "missing"
            else:
                date_status = dd.status
            conn.execute(
                """UPDATE documents SET doc_type=?, doc_type_confidence=?, doc_type_original=COALESCE(doc_type_original, ?),
                   document_date_text=?, document_date_iso=?, document_date_status=?, provider=?, page_count=?, ocr_status=?,
                   text_source_summary=?, ocr_mean_confidence=?, injection_flags=? WHERE id=?""",
                (dtype, dconf, dtype, dd.text if dd else None, dd.iso if dd and dd.status in ("parsed", "partial") else None, date_status,
                 meta.provider, len(result.pages), result.ocr_status, result.text_source_summary, result.ocr_mean_confidence,
                 json.dumps(meta.injection_flags) if meta.injection_flags else None, document_id),
            )
            for f in verified:
                insert_finding(conn, patient_id, document_id, run_id, f, label_for(f.confidence))

        stage("duplicate_detection", lambda: dup_mod.detect_for_patient(patient_id))
        stage("conflict_detection", lambda: conflict_mod.detect_for_patient(patient_id))
        stage("gap_detection", lambda: gap_mod.detect_for_patient(patient_id))
        status = "completed" if result.text_source_summary != "empty" else "failed"
        err = None if status == "completed" else "No text could be extracted (OCR unavailable or blank document)."
        total = round((time.perf_counter() - t0) * 1000, 1)
        with transaction() as conn:
            conn.execute("UPDATE documents SET extraction_status=?, error_message=? WHERE id=?", (status, err, document_id))
            conn.execute("UPDATE processing_runs SET finished_at=?, duration_ms=?, status=?, stages_json=? WHERE id=?",
                         (now_iso(), total, status, json.dumps(stages), run_id))
    except Exception as exc:  # noqa: BLE001
        log.exception("processing failed for %s", document_id)
        with transaction() as conn:
            conn.execute("UPDATE documents SET extraction_status='failed', error_message=? WHERE id=?",
                         (f"Processing error: {type(exc).__name__}", document_id))
            conn.execute("UPDATE processing_runs SET finished_at=?, status='failed', stages_json=? WHERE id=?",
                         (now_iso(), json.dumps(stages + [{"stage": "error", "error": type(exc).__name__}]), run_id))
