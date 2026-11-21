"""Duplicate detection at document and finding level. Candidates are only *proposed*;
nothing is merged automatically and originals are always kept."""
from __future__ import annotations

import json
import re
from itertools import combinations

from ..db import new_id, now_iso, rows, transaction
from ..store import get_findings

NEAR_DUP = 0.90
SIMILAR = 0.60


def normalise_text(text: str) -> list[str]:
    t = text.lower()
    t = re.sub(r"[^a-z0-9./%]+", " ", t)
    return t.split()


def shingles(tokens: list[str], k: int = 3) -> set[tuple[str, ...]]:
    if len(tokens) < k:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


def char_similarity(a: str, b: str) -> float:
    """OCR-tolerant similarity of whitespace-free normalised text (difflib ratio)."""
    import difflib

    na, nb = "".join(normalise_text(a)), "".join(normalise_text(b))
    if not na and not nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()


def classify_pair(sha_a: str, sha_b: str, sim: float, same_type: bool, dates_compatible: bool = True) -> str | None:
    """exact: identical bytes. near: >= NEAR_DUP similarity AND no conflicting documented dates
    (a re-issue, amendment or re-scan of the same record). similar_distinct: same type, similar layout."""
    if sha_a == sha_b:
        return "exact_duplicate"
    if sim >= NEAR_DUP and dates_compatible:
        return "near_duplicate"
    if sim >= SIMILAR and same_type:
        return "similar_distinct"
    return None


def _norm_strength(s: str | None) -> str | None:
    return re.sub(r"\s+", "", s.lower()) if s else None


def finding_key(f: dict) -> tuple | None:
    d = f["details"]
    t = f["finding_type"]
    if t == "medication":
        return (t, d.get("normalized_name") or (d.get("name_as_written") or "").lower(), _norm_strength(d.get("strength")),
                (d.get("frequency") or "").lower(), d.get("status"), f["date_iso"])
    if t == "investigation":
        return (t, d.get("normalized_test") or d.get("test_name", "").lower(), d.get("value_text"), (d.get("unit") or "").lower(), f["date_iso"])
    if t == "event":
        return (t, d.get("event_type"), f["date_iso"]) if f["date_iso"] else None
    if t == "condition":
        return (t, d.get("normalized_name") or d.get("name_as_written", "").lower(), d.get("status_as_documented"))
    if t == "allergy":
        return (t, d.get("normalized_substance") or (d.get("substance") or "").lower(), d.get("assertion"))
    return None


def detect_for_patient(patient_id: str) -> None:
    with transaction() as conn:
        docs = rows(conn, "SELECT id, sha256, doc_type, document_date_iso FROM documents WHERE patient_id=? AND extraction_status IN ('completed','processing')", (patient_id,))
        texts = {}
        for d in docs:
            t = "\n".join(r["text"] for r in rows(conn, "SELECT text FROM document_pages WHERE document_id=? ORDER BY page_number", (d["id"],)))
            texts[d["id"]] = (t, shingles(normalise_text(t)))
        seen = set()
        for a, b in combinations(sorted(docs, key=lambda x: x["id"]), 2):
            ta, sa = texts.get(a["id"], ("", set()))
            tb, sb = texts.get(b["id"], ("", set()))
            jac = 1.0 if a["sha256"] == b["sha256"] else jaccard(sa, sb)
            chars = 1.0 if a["sha256"] == b["sha256"] else char_similarity(ta, tb)
            sim = max(jac, chars)
            da, db_ = a["document_date_iso"], b["document_date_iso"]
            kind = classify_pair(a["sha256"], b["sha256"], sim, a["doc_type"] == b["doc_type"], not (da and db_ and da != db_))
            if kind is None:
                continue
            la, lb = set(ta.splitlines()), set(tb.splitlines())
            details = {"identical_hash": a["sha256"] == b["sha256"], "shingle_jaccard": round(jac, 3), "character_similarity": round(chars, 3),
                       "document_dates": [da, db_],
                       "lines_only_in_a": sorted(la - lb)[:6], "lines_only_in_b": sorted(lb - la)[:6]}
            _upsert(conn, patient_id, "document", a["id"], b["id"], kind, sim, details)
            seen.add(("document", a["id"], b["id"]))

        findings = get_findings(conn, patient_id, "f.verification_status != 'rejected'")
        groups: dict[tuple, list[dict]] = {}
        for f in findings:
            k = finding_key(f)
            if k is not None:
                groups.setdefault(k, []).append(f)
        for k, group in groups.items():
            docs_in = {}
            for f in group:
                docs_in.setdefault(f["document_id"], f)
            if len(docs_in) < 2:
                continue
            ordered = sorted(docs_in.values(), key=lambda f: (f["date_iso"] or "", f["id"]))
            anchor = ordered[0]
            for other in ordered[1:]:
                a, b = sorted([anchor["id"], other["id"]])
                same_date = anchor["date_iso"] == other["date_iso"] and anchor["date_iso"] is not None
                kind = "duplicate_finding" if (same_date or k[0] in ("medication", "investigation")) else "related_finding"
                _upsert(conn, patient_id, "finding", a, b, kind, 1.0, {"key": [str(x) for x in k], "same_date": same_date})
                seen.add(("finding", a, b))
        # Candidates that are no longer produced (e.g. after a correction) are removed only
        # if nobody reviewed them; reviewed decisions are kept as history.
        for r in rows(conn, "SELECT id, level, item_a, item_b, review_status FROM duplicate_candidates WHERE patient_id=?", (patient_id,)):
            if (r["level"], r["item_a"], r["item_b"]) not in seen and r["review_status"] == "pending":
                conn.execute("DELETE FROM duplicate_candidates WHERE id=?", (r["id"],))


def _upsert(conn, patient_id, level, a, b, kind, sim, details):
    conn.execute(
        """INSERT INTO duplicate_candidates (id, patient_id, level, item_a, item_b, kind, similarity, details_json, detected_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(patient_id, level, item_a, item_b) DO UPDATE SET kind=excluded.kind, similarity=excluded.similarity,
           details_json=excluded.details_json""",
        (new_id("dup"), patient_id, level, a, b, kind, round(sim, 4), json.dumps(details), now_iso()),
    )
