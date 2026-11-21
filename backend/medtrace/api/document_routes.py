"""Document upload, listing, text, page rendering, reprocessing, correction and deletion."""
from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..analysis import conflicts as conflict_mod, duplicates as dup_mod, gaps as gap_mod
from ..config import get_settings
from ..corrections import correct_page_text, set_document_type
from ..db import connection, one, rows, transaction
from ..ingest.text_extraction import render_page_png
from ..ingest.validation import UploadRejected, validate_upload
from ..pipeline import process_document, register_upload, stored_path
from ..security import User, audit, current_user, require_patient

router = APIRouter(prefix="/api/patients/{pid}/documents", tags=["documents"])


class DocPatch(BaseModel):
    doc_type: str = Field(max_length=40)


class PageTextIn(BaseModel):
    text: str = Field(max_length=100_000)
    reason: str = Field(min_length=3, max_length=500)


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"File exceeds the {limit // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", status_code=202)
async def upload(pid: str, background: BackgroundTasks, file: UploadFile = File(...), user: User = Depends(current_user)):
    s = get_settings()
    with connection() as conn:
        require_patient(conn, user, pid, write=True)
    data = await _read_limited(file, s.max_upload_bytes)
    try:
        up = validate_upload(file.filename or "document", data, s.max_upload_bytes, s.max_pdf_pages)
    except UploadRejected as exc:
        with transaction() as conn:
            audit(conn, user.id, "document_upload", patient_id=pid, outcome="rejected")
        raise HTTPException(400, str(exc))
    with connection() as conn:
        exact = one(conn, "SELECT id, original_filename FROM documents WHERE patient_id=? AND sha256=?", (pid, up.sha256))
    doc_id = register_upload(pid, up, user.id)
    with transaction() as conn:
        audit(conn, user.id, "document_upload", patient_id=pid, resource_id=doc_id)
    background.add_task(process_document, doc_id)
    return {"id": doc_id, "status": "pending", "exact_duplicate_of": exact,
            "note": "Processing started. An identical file already exists for this patient; both are kept and flagged." if exact else "Processing started."}


def _doc_list(conn, pid):
    docs = rows(conn, "SELECT * FROM documents WHERE patient_id=? ORDER BY COALESCE(document_date_iso, '9999'), upload_date", (pid,),
                json_fields=("injection_flags",))
    for d in docs:
        d.pop("stored_filename", None)
        d["findings_count"] = conn.execute("SELECT COUNT(*) FROM findings WHERE document_id=? AND is_active=1 AND verification_status!='rejected'", (d["id"],)).fetchone()[0]
        d["findings_by_type"] = {r["finding_type"]: r["n"] for r in rows(conn, "SELECT finding_type, COUNT(*) n FROM findings WHERE document_id=? AND is_active=1 AND verification_status!='rejected' GROUP BY finding_type", (d["id"],))}
        d["conflicts_count"] = conn.execute("""SELECT COUNT(DISTINCT c.id) FROM conflicts c JOIN conflict_findings cf ON cf.conflict_id=c.id
                                               JOIN findings f ON f.id=cf.finding_id WHERE f.document_id=? AND c.still_detected=1""", (d["id"],)).fetchone()[0]
        d["duplicate_flags"] = rows(conn, """SELECT id, kind, similarity, review_status, CASE WHEN item_a=? THEN item_b ELSE item_a END AS other_document_id
                                             FROM duplicate_candidates WHERE level='document' AND patient_id=? AND (item_a=? OR item_b=?)""", (d["id"], pid, d["id"], d["id"]))
        d["preview"] = (one(conn, "SELECT substr(text, 1, 240) AS t FROM document_pages WHERE document_id=? AND page_number=1", (d["id"],)) or {}).get("t")
    return docs


@router.get("")
def list_documents(pid: str, q: str | None = None, doc_type: str | None = None, status: str | None = None, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        docs = _doc_list(conn, pid)
        if doc_type:
            docs = [d for d in docs if d["doc_type"] == doc_type]
        if status:
            docs = [d for d in docs if d["extraction_status"] == status]
        if q:
            ql = q.lower()
            ids = {r[0] for r in conn.execute("SELECT DISTINCT document_id FROM document_pages WHERE patient_id=? AND lower(text) LIKE ?", (pid, f"%{ql}%"))}
            docs = [d for d in docs if d["id"] in ids or ql in d["original_filename"].lower()]
        return docs


def _doc_or_404(conn, pid, did):
    d = one(conn, "SELECT * FROM documents WHERE id=? AND patient_id=?", (did, pid), json_fields=("injection_flags",))
    if d is None:
        raise HTTPException(404, "Document not found.")
    return d


@router.get("/{did}")
def get_document(pid: str, did: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        _doc_or_404(conn, pid, did)
        return next(d for d in _doc_list(conn, pid) if d["id"] == did)


@router.get("/{did}/text")
def get_text(pid: str, did: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        _doc_or_404(conn, pid, did)
        pages = rows(conn, """SELECT page_number, text, original_text, text_source, original_text_source, ocr_confidence, width, height
                              FROM document_pages WHERE document_id=? AND patient_id=? ORDER BY page_number""", (did, pid))
        for p in pages:
            p["lines"] = rows(conn, """SELECT line_index, text, x0, y0, x1, y1, confidence, source FROM page_lines
                                       WHERE document_id=? AND page_number=? ORDER BY line_index""", (did, p["page_number"]))
            p["corrections"] = rows(conn, """SELECT c.previous_text, c.corrected_text, c.reason, c.corrected_at, u.username AS reviewer
                                             FROM page_text_corrections c JOIN document_pages dp ON dp.id=c.page_id
                                             LEFT JOIN users u ON u.id=c.corrected_by WHERE dp.document_id=? AND dp.page_number=?""",
                                    (did, p["page_number"]))
        return {"document_id": did, "pages": pages}


@router.get("/{did}/status")
def get_status(pid: str, did: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        d = _doc_or_404(conn, pid, did)
        runs = rows(conn, "SELECT id, extractor_version, started_at, finished_at, duration_ms, status, stages_json FROM processing_runs WHERE document_id=? ORDER BY started_at DESC",
                    (did,), json_fields=("stages_json",))
        return {"extraction_status": d["extraction_status"], "ocr_status": d["ocr_status"], "error_message": d["error_message"], "runs": runs}


@router.get("/{did}/pages/{page}/image")
def page_image(pid: str, did: str, page: int, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        d = _doc_or_404(conn, pid, did)
    cache = get_settings().cache_dir / pid
    cache.mkdir(parents=True, exist_ok=True)
    cpath = cache / f"{did}_p{int(page)}.png"
    if not cpath.is_file():
        try:
            png = render_page_png(stored_path(pid, d["stored_filename"]).read_bytes(), d["file_format"], int(page))
        except ValueError:
            raise HTTPException(404, "Page not found.")
        cpath.write_bytes(png)
    return Response(cpath.read_bytes(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{did}/file")
def original_file(pid: str, did: str, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid)
        d = _doc_or_404(conn, pid, did)
        audit(conn, user.id, "document_download", patient_id=pid, resource_id=did)
    data = stored_path(pid, d["stored_filename"]).read_bytes()
    safe = d["original_filename"].replace('"', "")
    return Response(data, media_type=d["mime_type"], headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.post("/{did}/reprocess", status_code=202)
def reprocess(pid: str, did: str, background: BackgroundTasks, user: User = Depends(current_user)):
    with connection() as conn:
        require_patient(conn, user, pid, write=True)
        _doc_or_404(conn, pid, did)
    background.add_task(process_document, did)
    return {"id": did, "status": "pending",
            "note": "Unverified machine findings from earlier runs are marked inactive (kept, not deleted); human-reviewed findings are retained."}


@router.patch("/{did}")
def patch_document(pid: str, did: str, body: DocPatch, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        set_document_type(conn, pid, did, body.doc_type)
        audit(conn, user.id, "document_reclassify", patient_id=pid, resource_id=did)
    return {"ok": True, "note": "Document type corrected. Reprocess the document to re-run extraction with the new type."}


@router.put("/{did}/pages/{page}/text")
def put_page_text(pid: str, did: str, page: int, body: PageTextIn, user: User = Depends(current_user)):
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        _doc_or_404(conn, pid, did)
        correct_page_text(conn, pid, did, page, body.text, body.reason, user.id)
        audit(conn, user.id, "page_text_correct", patient_id=pid, resource_id=did)
    return {"ok": True, "note": "Original machine text is preserved. Reprocess the document to extract from the corrected text."}


@router.delete("/{did}")
def delete_document(pid: str, did: str, user: User = Depends(current_user)):
    """Retention rule (MVP): deletion removes the stored file, its pages, findings, versions and any
    conflict/duplicate records that quote it. Access-log entries (identifiers only) are retained."""
    with transaction() as conn:
        require_patient(conn, user, pid, write=True)
        d = _doc_or_404(conn, pid, did)
        for c in rows(conn, "SELECT id, evidence_json FROM conflicts WHERE patient_id=?", (pid,)):
            if any(e.get("document_id") == did for e in json.loads(c["evidence_json"])):
                conn.execute("DELETE FROM conflicts WHERE id=?", (c["id"],))
        fids = [r[0] for r in conn.execute("SELECT id FROM findings WHERE document_id=?", (did,))]
        conn.execute("DELETE FROM duplicate_candidates WHERE patient_id=? AND (item_a=? OR item_b=?)", (pid, did, did))
        for fid in fids:
            conn.execute("DELETE FROM duplicate_candidates WHERE patient_id=? AND (item_a=? OR item_b=?)", (pid, fid, fid))
        conn.execute("DELETE FROM documents WHERE id=?", (did,))
        audit(conn, user.id, "document_delete", patient_id=pid, resource_id=did)
    try:
        stored_path(pid, d["stored_filename"]).unlink(missing_ok=True)
        for c in (get_settings().cache_dir / pid).glob(f"{did}_p*.png"):
            c.unlink(missing_ok=True)
    except OSError:
        pass
    dup_mod.detect_for_patient(pid)
    conflict_mod.detect_for_patient(pid)
    gap_mod.detect_for_patient(pid)
    return {"ok": True}
