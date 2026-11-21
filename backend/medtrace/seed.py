"""Load the SYNTHETIC dataset into a local MedTrace database.

Usage (from ./backend):   python -m medtrace.seed [--reset] [--no-holdout]

* Creates the bootstrap administrator from MEDTRACE_ADMIN_USERNAME / MEDTRACE_ADMIN_PASSWORD.
* Optionally creates a demo reviewer if MEDTRACE_DEMO_REVIEWER_PASSWORD is set; the reviewer is
  granted access to patients A-C only, which demonstrates patient isolation.
* Uploads every synthetic document through the same validation + processing pipeline used
  by the API.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from .config import get_settings
from .db import init_db, new_id, now_iso, one, transaction
from .ingest.validation import validate_upload
from .pipeline import process_document, register_upload
from .security import bootstrap_admin, create_user

DATASET = Path(__file__).resolve().parents[2] / "dataset"


def seed(reset: bool = False, include_holdout: bool = True, verbose: bool = True) -> dict[str, str]:
    s = get_settings()
    if reset and s.data_dir.exists():
        for child in (s.db_path, s.db_path.with_suffix(".db-wal"), s.db_path.with_suffix(".db-shm")):
            if child.exists():
                child.unlink()
        shutil.rmtree(s.upload_dir, ignore_errors=True)
        shutil.rmtree(s.cache_dir, ignore_errors=True)
        s.ensure_dirs()
    init_db()
    generated = bootstrap_admin()
    if generated and verbose:
        print(f"[seed] Generated admin password for '{s.admin_username}': {generated}")
    gt = json.loads((DATASET / "ground_truth.json").read_text(encoding="utf-8"))
    with transaction() as conn:
        admin = one(conn, "SELECT id FROM users WHERE role='admin' ORDER BY created_at LIMIT 1")
    admin_id = admin["id"]

    patient_ids: dict[str, str] = {}
    with transaction() as conn:
        for key, p in gt["patients"].items():
            if key in gt["holdout_patients"] and not include_holdout:
                continue
            existing = one(conn, "SELECT id FROM patients WHERE display_name=?", (p["display_name"],))
            if existing:
                patient_ids[key] = existing["id"]
                continue
            pid = new_id("pat")
            conn.execute("""INSERT INTO patients (id, display_name, synthetic_label, date_of_birth_text, sex, notes, is_synthetic, created_by, created_at, updated_at)
                            VALUES (?,?,?,?,?,?,1,?,?,?)""",
                         (pid, p["display_name"], p["synthetic_label"], p["dob"], p["sex"], "Synthetic evaluation patient.", admin_id, now_iso(), now_iso()))
            patient_ids[key] = pid
        demo_pw = os.environ.get("MEDTRACE_DEMO_REVIEWER_PASSWORD")
        if demo_pw and not one(conn, "SELECT id FROM users WHERE username='reviewer'"):
            rid = create_user(conn, "reviewer", demo_pw, "reviewer")
            for key in ("A", "B", "C"):
                if key in patient_ids:
                    conn.execute("INSERT OR IGNORE INTO patient_access (user_id, patient_id, permission, granted_at) VALUES (?,?,?,?)",
                                 (rid, patient_ids[key], "write", now_iso()))

    for d in gt["documents"]:
        if d["patient"] not in patient_ids:
            continue
        pid = patient_ids[d["patient"]]
        with transaction() as conn:
            if one(conn, "SELECT id FROM documents WHERE patient_id=? AND original_filename=?", (pid, d["filename"])):
                continue
        data = (DATASET / d["path"]).read_bytes()
        up = validate_upload(d["filename"], data, s.max_upload_bytes, s.max_pdf_pages)
        t0 = time.perf_counter()
        doc_id = register_upload(pid, up, admin_id)
        process_document(doc_id)
        if verbose:
            with transaction() as conn:
                r = one(conn, "SELECT extraction_status, doc_type, ocr_status FROM documents WHERE id=?", (doc_id,))
                n = conn.execute("SELECT COUNT(*) FROM findings WHERE document_id=?", (doc_id,)).fetchone()[0]
            print(f"[seed] {d['key']:>3} {d['filename']:<45} {r['extraction_status']:<10} {r['doc_type']:<18} ocr={r['ocr_status']:<12} "
                  f"findings={n:<3} {time.perf_counter() - t0:.1f}s")
    return patient_ids


def main() -> None:
    ap = argparse.ArgumentParser(description="Load the synthetic MedTrace dataset")
    ap.add_argument("--reset", action="store_true", help="delete the local database and uploads first")
    ap.add_argument("--no-holdout", action="store_true", help="skip the hold-out patient F")
    a = ap.parse_args()
    seed(reset=a.reset, include_holdout=not a.no_holdout)
    print("[seed] done.")


if __name__ == "__main__":
    main()
