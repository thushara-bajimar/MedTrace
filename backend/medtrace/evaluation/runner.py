"""MedTrace evaluation framework.

Loads the synthetic dataset into an *isolated temporary* database through the normal
pipeline, compares system output with the hand-written ground truth
(dataset/ground_truth.json) and reports measured metrics. Nothing here is estimated
except the clearly labelled reading-load proxy for review time.

Usage (from ./backend):  python -m medtrace.evaluation.runner [--out ../docs/evaluation]
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
import tempfile
import time
from itertools import combinations
from pathlib import Path

from ..config import EXTRACTOR_VERSION, Settings, get_settings, override_settings
from ..db import connection, new_id, now_iso, rows, transaction, init_db
from ..store import get_findings

DATASET = Path(__file__).resolve().parents[3] / "dataset"
ANSWER_PREFIX, ABSTAIN_PREFIX, DECLINE_PREFIX = "answered", "abstained", "declined"
READING_WPM = 200          # assumption for the reading-load proxy
SECONDS_PER_DOC_OPEN = 10  # assumption: locate + open + orient in one document
SECONDS_PER_FACT_CHECK = 6 # assumption: click a cited fact and glance at the highlighted source


# ---------------------------------------------------------------- normalisation
def norm(s) -> str:
    if s is None:
        return ""
    s = str(s).lower().replace("μ", "µ").replace("–", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s*<\s*", "<", s)
    s = re.sub(r"\s*>\s*", ">", s)
    return re.sub(r"\s+", " ", s).strip(" .")


def fuzzy_in(needle: str, hay: str, threshold: float = 0.8) -> bool:
    n, h = norm(needle), norm(hay)
    if not n:
        return True
    if n in h:
        return True
    if len(h) < len(n):
        return difflib.SequenceMatcher(None, n, h).ratio() >= threshold
    best = 0.0
    for i in range(0, len(h) - len(n) + 1):
        best = max(best, difflib.SequenceMatcher(None, n, h[i:i + len(n)]).ratio())
        if best >= threshold:
            return True
    return False


def category(status: str) -> str:
    if status.startswith(ANSWER_PREFIX):
        return "answer"
    if status.startswith(DECLINE_PREFIX):
        return "decline"
    return "abstain"


# ---------------------------------------------------------------- matching
def pred_key_name(f: dict) -> str:
    d = f["details"]
    t = f["finding_type"]
    if t == "condition":
        return norm(d.get("normalized_name") or d.get("name_as_written"))
    if t == "medication":
        return norm(d.get("normalized_name") or d.get("name_as_written"))
    if t == "allergy":
        return norm(d.get("normalized_substance") or d.get("substance"))
    if t == "investigation":
        return norm(d.get("normalized_test") or d.get("test_name"))
    return norm(d.get("event_type"))


def gt_key_name(g: dict) -> str:
    return norm({"condition": g.get("name"), "medication": g.get("name"), "allergy": g.get("substance"),
                 "investigation": g.get("test"), "event": g.get("event_type")}[g["type"]])


def key_compatible(g: dict, f: dict) -> bool:
    if g["type"] != f["finding_type"]:
        return False
    gk, pk = gt_key_name(g), pred_key_name(f)
    if g["type"] == "condition":
        return bool(gk) and bool(pk) and (gk == pk or gk in pk or pk in gk)
    if g["type"] == "allergy":
        if gk == "" or pk == "":
            return gk == pk and (g["assertion"] == f["details"].get("assertion") or
                                 {g["assertion"], f["details"].get("assertion")} <= {"explicitly_denied_general", "status_not_recorded"})
        return gk == pk
    return gk == pk


FIELDS = {
    "medication": [("strength", "strength"), ("frequency", "frequency"), ("status", "status"), ("date_iso", None)],
    "investigation": [("value", "value_text"), ("unit", "unit"), ("reference_range", "reference_range"), ("date_iso", None)],
    "allergy": [("assertion", "assertion"), ("reaction", "reaction")],
    "condition": [("status", "status_as_documented"), ("date_iso", None)],
    "event": [("date_iso", None)],
}


def field_value(f: dict, pred_field: str | None):
    return f["date_iso"] if pred_field is None else f["details"].get(pred_field)


def field_equal(gname: str, gval, pval) -> bool:
    if gname == "unit":
        return norm(gval).replace("umol", "µmol") == norm(pval).replace("umol", "µmol")
    if gname == "value" and gval is not None and pval is not None and not re.match(r"^[\d.<>]+$", str(gval)):
        return fuzzy_in(gval, pval, 0.85) and fuzzy_in(pval, gval, 0.85)
    return norm(gval) == norm(pval)


def match_doc(gt_items: list[dict], preds: list[dict]):
    pairs, used = [], set()
    for g in gt_items:
        best, best_score = None, -1
        for f in preds:
            if f["id"] in used or not key_compatible(g, f):
                continue
            score = sum(field_equal(gn, g.get(gn), field_value(f, pf)) for gn, pf in FIELDS[g["type"]])
            score += 0.5 * fuzzy_in(g.get("evidence") or "", f["source_passage"], 0.8)
            if score > best_score:
                best, best_score = f, score
        if best is not None:
            used.add(best["id"])
            pairs.append((g, best))
    unmatched_gt = [g for g in gt_items if not any(g is p[0] for p in pairs)]
    unmatched_pred = [f for f in preds if f["id"] not in used]
    return pairs, unmatched_gt, unmatched_pred


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _r(p), "recall": _r(r), "f1": _r(f1)}


def _r(x):
    return None if x is None else round(x, 4)


# ---------------------------------------------------------------- main evaluation
def evaluate(include_holdout_split: bool = True) -> dict:
    from ..seed import seed
    from ..qa.engine import answer_question

    gt = json.loads((DATASET / "ground_truth.json").read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    patient_ids = seed(reset=True, include_holdout=True, verbose=False)
    seed_seconds = time.perf_counter() - t0
    holdout = set(gt["holdout_patients"])

    with connection() as conn:
        docs_db = {(d["patient_id"], d["original_filename"]): d for d in rows(conn, "SELECT * FROM documents")}
        key_to_doc = {}
        for d in gt["documents"]:
            key_to_doc[d["key"]] = docs_db[(patient_ids[d["patient"]], d["filename"])]
        docid_to_key = {v["id"]: k for k, v in key_to_doc.items()}
        findings_by_doc: dict[str, list[dict]] = {}
        for pkey, pid in patient_ids.items():
            for f in get_findings(conn, pid):
                findings_by_doc.setdefault(f["document_id"], []).append(f)
        pages_text = {(r["document_id"], r["page_number"]): r["text"] for r in rows(conn, "SELECT document_id, page_number, text FROM document_pages")}
        runs = rows(conn, "SELECT r.duration_ms, d.file_format, d.text_source_summary FROM processing_runs r JOIN documents d ON d.id=r.document_id WHERE r.status='completed'")

        splits = {"development": [d for d in gt["documents"] if d["patient"] not in holdout],
                  "holdout": [d for d in gt["documents"] if d["patient"] in holdout]}
        results = {}
        all_pairs_by_split = {}
        for split, gdocs in splits.items():
            results[split], all_pairs_by_split[split] = _extraction_metrics(gdocs, key_to_doc, findings_by_doc, pages_text)
        overall, all_pairs = _extraction_metrics(gt["documents"], key_to_doc, findings_by_doc, pages_text)

        timeline = _timeline_metrics(all_pairs, gt, key_to_doc)
        dups = _duplicate_metrics(conn, gt, patient_ids, key_to_doc, docid_to_key)
        confl = _conflict_metrics(conn, gt, patient_ids, docid_to_key)
        qa = _qa_metrics(conn, gt, patient_ids, docid_to_key, answer_question, holdout)
        ocr = _ocr_metrics(gt, key_to_doc, pages_text)
        review = _review_proxy(conn, gt, patient_ids)

    lat_native = [r["duration_ms"] for r in runs if r["text_source_summary"] == "native"]
    lat_ocr = [r["duration_ms"] for r in runs if r["text_source_summary"] in ("ocr", "mixed")]
    metrics = {
        "dataset": {"version": gt["dataset_version"], "patients": len(gt["patients"]), "holdout_patients": sorted(holdout),
                    "documents": len(gt["documents"]),
                    "documents_by_type": _count(d["doc_type"] for d in gt["documents"]),
                    "documents_by_format": _count(d["format"] for d in gt["documents"]),
                    "ground_truth_findings": sum(len(d["findings"]) for d in gt["documents"]),
                    "ground_truth_by_type": _count(f["type"] for d in gt["documents"] for f in d["findings"]),
                    "questions": len(gt["questions"])},
        "extraction": overall, "extraction_by_split": results,
        "timeline": timeline, "duplicates": dups, "conflicts": confl, "qa": qa, "ocr": ocr,
        "latency": {"native_ms_median": _r(statistics.median(lat_native)) if lat_native else None,
                    "native_ms_mean": _r(statistics.mean(lat_native)) if lat_native else None,
                    "ocr_ms_median": _r(statistics.median(lat_ocr)) if lat_ocr else None,
                    "ocr_ms_mean": _r(statistics.mean(lat_ocr)) if lat_ocr else None,
                    "documents_native": len(lat_native), "documents_ocr": len(lat_ocr),
                    "total_seed_seconds": round(seed_seconds, 2)},
        "review_time": review,
        "extractor_version": EXTRACTOR_VERSION,
    }
    return metrics


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


def _extraction_metrics(gdocs, key_to_doc, findings_by_doc, pages_text):
    per_type: dict[str, list[int]] = {}
    field_stats: dict[str, dict[str, list[int]]] = {}
    evidence = {"page_correct": 0, "passage_correct": 0, "matched": 0, "verifiable": 0, "predicted": 0}
    doc_type_ok = doc_date_ok = 0
    errors = []
    all_pairs = []
    for gd in gdocs:
        db = key_to_doc[gd["key"]]
        preds = findings_by_doc.get(db["id"], [])
        doc_type_ok += db["doc_type"] == gd["doc_type"]
        doc_date_ok += (db["document_date_iso"] or None) == gd["document_date_iso"]
        pairs, ugt, upred = match_doc(gd["findings"], preds)
        for g, f in pairs:
            all_pairs.append((gd, g, f))
        for t in ("condition", "medication", "allergy", "investigation", "event"):
            c = per_type.setdefault(t, [0, 0, 0])
            c[0] += sum(1 for g, _ in pairs if g["type"] == t)
            c[1] += sum(1 for f in upred if f["finding_type"] == t)
            c[2] += sum(1 for g in ugt if g["type"] == t)
        for g, f in pairs:
            for gname, pf in FIELDS[g["type"]]:
                st = field_stats.setdefault(g["type"], {}).setdefault(gname, [0, 0])
                ok = field_equal(gname, g.get(gname), field_value(f, pf))
                st[0] += ok
                st[1] += 1
                if not ok and len(errors) < 400:
                    errors.append({"doc": gd["key"], "type": g["type"], "item": gt_key_name(g), "field": gname,
                                   "expected": g.get(gname), "got": field_value(f, pf)})
            evidence["matched"] += 1
            evidence["page_correct"] += f["page_number"] == g["page"]
            evidence["passage_correct"] += fuzzy_in(g.get("evidence") or "", f["source_passage"], 0.8)
        for f in preds:
            evidence["predicted"] += 1
            page_text = pages_text.get((f["document_id"], f["page_number"]), "")
            evidence["verifiable"] += bool(f["source_passage"]) and f["original_text"].strip()[:40] in page_text
        for g in ugt:
            errors.append({"doc": gd["key"], "type": g["type"], "item": gt_key_name(g), "field": "MISSED", "expected": g.get("evidence")})
        for f in upred:
            errors.append({"doc": gd["key"], "type": f["finding_type"], "item": pred_key_name(f), "field": "SPURIOUS", "got": f["source_passage"]})
    entity = {t: prf(*c) for t, c in per_type.items()}
    tp, fp, fn = (sum(c[i] for c in per_type.values()) for i in range(3))
    fields = {t: {k: {"correct": v[0], "total": v[1], "accuracy": _r(v[0] / v[1]) if v[1] else None} for k, v in fs.items()}
              for t, fs in field_stats.items()}
    date_c = sum(v["date_iso"][0] for v in field_stats.values() if "date_iso" in v)
    date_t = sum(v["date_iso"][1] for v in field_stats.values() if "date_iso" in v)
    m = evidence["matched"]
    return {
        "entity": entity, "micro": prf(tp, fp, fn), "fields": fields,
        "date_extraction": {"correct": date_c, "total": date_t, "accuracy": _r(date_c / date_t) if date_t else None},
        "medication_status": fields.get("medication", {}).get("status"),
        "evidence": {"page_reference_accuracy": _r(evidence["page_correct"] / m) if m else None,
                     "passage_accuracy": _r(evidence["passage_correct"] / m) if m else None,
                     "source_document_accuracy": 1.0 if m else None,
                     "evidence_completeness": _r(evidence["verifiable"] / evidence["predicted"]) if evidence["predicted"] else None,
                     "matched_findings": m, "predicted_findings": evidence["predicted"]},
        "document_classification_accuracy": _r(doc_type_ok / len(gdocs)) if gdocs else None,
        "document_date_accuracy": _r(doc_date_ok / len(gdocs)) if gdocs else None,
        "documents": len(gdocs),
        "errors": errors,
    }, all_pairs


def _timeline_metrics(pairs, gt, key_to_doc):
    by_patient: dict[str, list] = {}
    for gd, g, f in pairs:
        by_patient.setdefault(gd["patient"], []).append((g, f))
    concordant = comparable = 0
    for items in by_patient.values():
        dated = [(g, f) for g, f in items if g.get("date_iso") and len(g["date_iso"]) == 10]
        for (g1, f1), (g2, f2) in combinations(dated, 2):
            if g1["date_iso"] == g2["date_iso"]:
                continue
            comparable += 1
            if f1["date_iso"] and f2["date_iso"] and (g1["date_iso"] < g2["date_iso"]) == (f1["date_iso"][:10] < f2["date_iso"][:10]) and f1["date_iso"][:10] != f2["date_iso"][:10]:
                concordant += 1
    dated_items = [(g, f) for _, g, f in pairs if g.get("date_iso")]
    # allergies carry no annotated own date, so they are excluded from the date-handling measure
    undated_items = [(g, f) for _, g, f in pairs if not g.get("date_iso") and g["type"] != "allergy"]
    med_pairs = [(g, f) for _, g, f in pairs if g["type"] == "medication"]
    med_dated = [(g, f) for g, f in med_pairs if g.get("date_iso")]
    med_order_ok = med_order_total = 0
    for (g1, f1), (g2, f2) in combinations(med_dated, 2):
        if g1["name"] != g2["name"] or g1["date_iso"] == g2["date_iso"]:
            continue
        med_order_total += 1
        med_order_ok += bool(f1["date_iso"] and f2["date_iso"] and (g1["date_iso"] < g2["date_iso"]) == (f1["date_iso"] < f2["date_iso"]))
    hist = [(g, f) for g, f in med_pairs if g["status"] in ("historical", "documented_stopped", "documented_ongoing")]
    return {
        "event_date_accuracy": _r(sum(g["date_iso"] == f["date_iso"] for g, f in dated_items) / len(dated_items)) if dated_items else None,
        "dated_items_evaluated": len(dated_items),
        "pairwise_ordering_accuracy": _r(concordant / comparable) if comparable else None,
        "ordering_pairs": comparable,
        "medication_chronology_accuracy": _r(med_order_ok / med_order_total) if med_order_total else None,
        "medication_chronology_pairs": med_order_total,
        "historical_current_status_accuracy": _r(sum(g["status"] == f["details"].get("status") for g, f in hist) / len(hist)) if hist else None,
        "historical_current_items": len(hist),
        "missing_or_ambiguous_date_handling": _r(sum(f["date_iso"] is None for g, f in undated_items) / len(undated_items)) if undated_items else None,
        "missing_or_ambiguous_items": len(undated_items),
        "note": "Missing/ambiguous handling = share of ground-truth items without a determinable date for which MedTrace also "
                "produced no interpreted date (i.e. did not fabricate one).",
    }


def _duplicate_metrics(conn, gt, patient_ids, key_to_doc, docid_to_key):
    pred = {}
    for r in rows(conn, "SELECT * FROM duplicate_candidates WHERE level='document'"):
        a, b = docid_to_key[r["item_a"]], docid_to_key[r["item_b"]]
        pred[frozenset((a, b))] = r["kind"]
    gold = {frozenset((d["a"], d["b"])): d["kind"] for d in gt["duplicates"]}
    positive = {"exact_duplicate", "near_duplicate"}
    gp = {k for k, v in gold.items() if v in positive}
    pp = {k for k, v in pred.items() if v in positive}
    tp, fp, fn = len(gp & pp), len(pp - gp), len(gp - pp)
    by_patient: dict[str, list[str]] = {}
    for d in gt["documents"]:
        by_patient.setdefault(d["patient"], []).append(d["key"])
    negatives = sum(1 for keys in by_patient.values() for p in combinations(keys, 2) if frozenset(p) not in gp)
    kind_ok = sum(pred.get(k) == v for k, v in gold.items())
    return {**prf(tp, fp, fn), "false_positive_rate": _r(fp / negatives) if negatives else None, "negative_pairs": negatives,
            "kind_accuracy_on_labelled_pairs": _r(kind_ok / len(gold)) if gold else None,
            "labelled_pairs": len(gold),
            "predicted": [{"pair": sorted(k), "kind": v, "expected": gold.get(k, "not_duplicate")} for k, v in sorted(pred.items(), key=lambda x: sorted(x[0]))],
            "missed": [sorted(k) for k in gp - pp]}


def _conflict_metrics(conn, gt, patient_ids, docid_to_key):
    pred = []
    for c in rows(conn, "SELECT * FROM conflicts WHERE still_detected=1", json_fields=("evidence_json",)):
        ks = frozenset(docid_to_key[e["document_id"]] for e in c["evidence_json"])
        pred.append((c["category"], ks, c["explanation"]))
    gold_pos = [(c["category"], frozenset(c["docs"])) for c in gt["conflicts"] if not c.get("negative")]
    gold_neg = [(c["category"], frozenset(c["docs"])) for c in gt["conflicts"] if c.get("negative")]
    pred_set = {(c, k) for c, k, _ in pred}
    tp = len(set(gold_pos) & pred_set)
    fp_items = [(c, sorted(k), e) for c, k, e in pred if (c, k) not in set(gold_pos)]
    fn_items = [(c, sorted(k)) for c, k in gold_pos if (c, k) not in pred_set]
    neg_flagged = [(c, sorted(k)) for c, k in gold_neg if (c, k) in pred_set]
    dev = [c for c in gt["conflicts"] if not c.get("negative") and not any(d.startswith("F") for d in c["docs"])]
    hold = [c for c in gt["conflicts"] if not c.get("negative") and any(d.startswith("F") for d in c["docs"])]
    def rec(lst):
        hit = sum((c["category"], frozenset(c["docs"])) in pred_set for c in lst)
        return {"detected": hit, "total": len(lst), "recall": _r(hit / len(lst)) if lst else None}
    return {**prf(tp, len(fp_items), len(fn_items)), "false_positives": fp_items, "missed_conflicts": fn_items,
            "negative_controls_flagged": neg_flagged, "development_recall": rec(dev), "holdout_recall": rec(hold),
            "auto_resolved": 0, "note": "Conflicts are never auto-resolved; auto_resolved is structurally 0 (no code path changes status)."}


def _qa_metrics(conn, gt, patient_ids, docid_to_key, answer_question, holdout):
    results = []
    for q in gt["questions"]:
        a = answer_question(conn, patient_ids[q["patient"]], q["q"])
        got = category(a["retrieval_status"])
        cited = {docid_to_key.get(c["document_id"]) for c in a["citations"]}
        blob = " ".join([a["answer"]] + [f["statement"] for f in a["facts"]] + [p["passage"] for p in a["related_passages"]] + a["notes"]).lower()
        cite_ok = set(q["cites"]) <= cited
        include_ok = all(s.lower() in blob for s in q["must_include"])
        foreign = [c for c in cited if c and not c.startswith(q["patient"])]
        results.append({"patient": q["patient"], "question": q["q"], "expected": q["expect"], "got": got, "status": a["retrieval_status"],
                        "status_correct": got == q["expect"], "citations_ok": cite_ok, "content_ok": include_ok,
                        "cited": sorted(c for c in cited if c), "cross_patient_citations": foreign,
                        "correct": got == q["expect"] and cite_ok and (include_ok or q["expect"] != "answer"),
                        "holdout": q["patient"] in holdout})
    ans = [r for r in results if r["expected"] == "answer"]
    neg = [r for r in results if r["expected"] in ("abstain", "decline")]
    no_ev = [r for r in results if r["expected"] == "abstain" and not r["cited"] and not any(r["question"] == q["q"] and q["cites"] for q in gt["questions"])]
    def share(lst, key):
        return _r(sum(r[key] for r in lst) / len(lst)) if lst else None
    with_cites = [r for r in results if r["cited"]]
    return {
        "questions": len(results),
        "overall_accuracy": share(results, "correct"),
        "status_accuracy": share(results, "status_correct"),
        "evidence_supported_answer_accuracy": share(ans, "correct"),
        "citation_accuracy": share([r for r in results if r["expected"] != "decline" and next(q for q in gt["questions"] if q["q"] == r["question"] and q["patient"] == r["patient"])["cites"]], "citations_ok"),
        "abstention_accuracy": _r(sum(r["got"] in ("abstain", "decline") for r in neg) / len(neg)) if neg else None,
        "unsupported_answer_rate": _r(sum(r["got"] == "answer" for r in neg) / len(neg)) if neg else None,
        "over_abstention_rate": _r(sum(r["got"] != "answer" for r in ans) / len(ans)) if ans else None,
        "missing_evidence_detection": _r(sum(r["got"] == "abstain" for r in no_ev) / len(no_ev)) if no_ev else None,
        "cross_patient_citation_rate": _r(sum(bool(r["cross_patient_citations"]) for r in with_cites) / len(with_cites)) if with_cites else 0.0,
        "development_accuracy": share([r for r in results if not r["holdout"]], "correct"),
        "holdout_accuracy": share([r for r in results if r["holdout"]], "correct"),
        "results": results,
    }


def _cer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0
    sm = difflib.SequenceMatcher(None, r, h, autojunk=False)
    edits = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
    return edits / len(r)


def _ocr_metrics(gt, key_to_doc, pages_text):
    out = []
    for d in gt["documents"]:
        db = key_to_doc[d["key"]]
        if db["text_source_summary"] not in ("ocr", "mixed"):
            continue
        cers = []
        for i, ref_lines in enumerate(d["text_pages"], start=1):
            ref = "\n".join(ref_lines) + "\n" + "SYNTHETIC RECORD - FICTIONAL PATIENT - FOR SOFTWARE EVALUATION ONLY"
            cers.append(_cer(ref, pages_text.get((db["id"], i), "")))
        out.append({"doc": d["key"], "format": d["format"], "engine_mean_confidence": db["ocr_mean_confidence"],
                    "character_error_rate": _r(sum(cers) / len(cers))})
    return {"documents": out,
            "mean_character_error_rate": _r(statistics.mean(o["character_error_rate"] for o in out)) if out else None,
            "mean_engine_confidence": _r(statistics.mean(o["engine_mean_confidence"] for o in out if o["engine_mean_confidence"] is not None)) if out else None,
            "engine": "RapidOCR (PP-OCR models, ONNX Runtime, local)",
            "note": "CER compares OCR text with the known source text of each synthetic image (whitespace-normalised)."}


def _review_proxy(conn, gt, patient_ids):
    """Automated reading-load proxy. NOT a human study: it counts words a reviewer would have to
    read and items to check, then applies stated reading-speed assumptions."""
    from ..views import summarise

    per_patient = []
    for key, pid in patient_ids.items():
        docs = [d for d in gt["documents"] if d["patient"] == key]
        words_raw = sum(len(" ".join(" ".join(p) for p in d["text_pages"]).split()) for d in docs)
        f = [x for x in get_findings(conn, pid) if x["finding_type"] in ("medication", "allergy", "investigation")]
        words_struct = sum(len(summarise(x).split()) + 4 for x in f)  # +4: date/source label per row
        baseline_s = words_raw / READING_WPM * 60 + SECONDS_PER_DOC_OPEN * len(docs)
        medtrace_s = words_struct / READING_WPM * 60 + SECONDS_PER_FACT_CHECK * len(f) * 0.25  # spot-check 25% of facts
        per_patient.append({"patient": key, "documents": len(docs), "raw_words": words_raw, "structured_words": words_struct,
                            "baseline_seconds_estimate": round(baseline_s, 1), "medtrace_seconds_estimate": round(medtrace_s, 1)})
    b = sum(p["baseline_seconds_estimate"] for p in per_patient)
    m = sum(p["medtrace_seconds_estimate"] for p in per_patient)
    with connection() as c2:
        sessions = rows(c2, "SELECT mode, participant_kind, duration_seconds, tasks_total, tasks_correct, missed_findings FROM review_sessions WHERE finished_at IS NOT NULL")
    return {"kind": "automated_reading_load_proxy", "is_human_study": False,
            "assumptions": {"reading_wpm": READING_WPM, "seconds_per_document_open": SECONDS_PER_DOC_OPEN,
                            "seconds_per_fact_check": SECONDS_PER_FACT_CHECK, "fact_spot_check_share": 0.25},
            "per_patient": per_patient, "baseline_total_seconds_estimate": round(b, 1), "medtrace_total_seconds_estimate": round(m, 1),
            "estimated_reduction": _r(1 - m / b) if b else None,
            "human_sessions_recorded": len(sessions),
            "note": "No human reviewer study has been performed. Use the Review-time study page to record real timed sessions."}


# ---------------------------------------------------------------- reporting
def to_markdown(m: dict) -> str:
    ex, ds = m["extraction"], m["dataset"]
    L = [f"# MedTrace Evaluation Report", "", f"Generated: {m['generated_at']}  ", f"Extractor: `{m['extractor_version']}`  ",
         f"Dataset: `{ds['version']}` (synthetic; {ds['patients']} patients, {ds['documents']} documents, {ds['ground_truth_findings']} annotated findings, {ds['questions']} questions)  ",
         f"Hold-out patients (never used to tune rules): {', '.join(ds['holdout_patients'])}", "",
         "All numbers below are measured by `python -m medtrace.evaluation.runner` against hand-written ground truth, except the review-time "
         "section, which is an explicitly labelled automated estimate.", "",
         "## Dataset", "", "| Document type | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in ds["documents_by_type"].items()]
    L += ["", "| Format | Count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in ds["documents_by_format"].items()]
    L += ["", "## Extraction (entity detection)", "", "| Type | Precision | Recall | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
    for t, v in ex["entity"].items():
        L.append(f"| {t} | {v['precision']} | {v['recall']} | {v['f1']} | {v['tp']} | {v['fp']} | {v['fn']} |")
    mi = ex["micro"]
    L.append(f"| **micro (all)** | **{mi['precision']}** | **{mi['recall']}** | **{mi['f1']}** | {mi['tp']} | {mi['fp']} | {mi['fn']} |")
    L += ["", "### Development vs hold-out", "", "| Split | Docs | Precision | Recall | F1 |", "|---|---|---|---|---|"]
    for s, v in m["extraction_by_split"].items():
        L.append(f"| {s} | {v['documents']} | {v['micro']['precision']} | {v['micro']['recall']} | {v['micro']['f1']} |")
    L += ["", "### Attribute (field-level) accuracy on matched findings", "", "| Type | Field | Correct / Total | Accuracy |", "|---|---|---|---|"]
    for t, fs in ex["fields"].items():
        for k, v in fs.items():
            L.append(f"| {t} | {k} | {v['correct']} / {v['total']} | {v['accuracy']} |")
    ev = ex["evidence"]
    L += ["", "## Evidence", "", f"- Page reference accuracy: **{ev['page_reference_accuracy']}**",
          f"- Evidence passage accuracy: **{ev['passage_accuracy']}**",
          f"- Source document accuracy: {ev['source_document_accuracy']} (matching is per document)",
          f"- Evidence completeness (every predicted finding has a verbatim span present in its cited page): **{ev['evidence_completeness']}**",
          f"- Document classification accuracy: {ex['document_classification_accuracy']}",
          f"- Document date accuracy: {ex['document_date_accuracy']}", ""]
    tl = m["timeline"]
    L += ["## Timeline", "", f"- Event date accuracy: **{tl['event_date_accuracy']}** ({tl['dated_items_evaluated']} dated items)",
          f"- Pairwise chronological ordering accuracy: **{tl['pairwise_ordering_accuracy']}** ({tl['ordering_pairs']} pairs)",
          f"- Medication chronology accuracy: {tl['medication_chronology_accuracy']} ({tl['medication_chronology_pairs']} pairs)",
          f"- Historical / current status accuracy: {tl['historical_current_status_accuracy']} ({tl['historical_current_items']} items)",
          f"- Missing/ambiguous date handling (no fabricated dates): **{tl['missing_or_ambiguous_date_handling']}** ({tl['missing_or_ambiguous_items']} items)", ""]
    du = m["duplicates"]
    L += ["## Duplicate detection (document level)", "", f"- Precision {du['precision']}, recall {du['recall']}, F1 {du['f1']}",
          f"- False-positive rate: {du['false_positive_rate']} over {du['negative_pairs']} non-duplicate pairs",
          f"- Kind accuracy on labelled pairs (exact / near / similar-distinct): {du['kind_accuracy_on_labelled_pairs']}", ""]
    co = m["conflicts"]
    L += ["## Contradiction detection", "", f"- Precision {co['precision']}, recall {co['recall']}, F1 {co['f1']}",
          f"- Development recall: {co['development_recall']['detected']}/{co['development_recall']['total']}; hold-out recall: {co['holdout_recall']['detected']}/{co['holdout_recall']['total']}",
          f"- Negative controls wrongly flagged: {len(co['negative_controls_flagged'])}", f"- Missed: {co['missed_conflicts']}",
          f"- False positives: {[(c, k) for c, k, _ in co['false_positives']]}", "- Conflicts auto-resolved: 0 (by design)", ""]
    qa = m["qa"]
    L += ["## Records-only question answering", "", f"- Questions: {qa['questions']}", f"- Overall accuracy: **{qa['overall_accuracy']}** (dev {qa['development_accuracy']}, hold-out {qa['holdout_accuracy']})",
          f"- Evidence-supported answer accuracy: {qa['evidence_supported_answer_accuracy']}", f"- Citation accuracy: {qa['citation_accuracy']}",
          f"- Abstention accuracy (abstain/decline when expected): **{qa['abstention_accuracy']}**", f"- Unsupported-answer rate: **{qa['unsupported_answer_rate']}**",
          f"- Over-abstention rate: {qa['over_abstention_rate']}", f"- Missing-evidence detection: {qa['missing_evidence_detection']}",
          f"- Cross-patient citation rate: {qa['cross_patient_citation_rate']}", "", "| Pt | Question | Expected | Got | Status | Correct |", "|---|---|---|---|---|---|"]
    for r in qa["results"]:
        L.append(f"| {r['patient']} | {r['question']} | {r['expected']} | {r['got']} | {r['status']} | {'yes' if r['correct'] else 'NO'} |")
    oc = m["ocr"]
    L += ["", "## OCR", "", f"Engine: {oc['engine']}. Mean character error rate: **{oc['mean_character_error_rate']}**; mean engine confidence {oc['mean_engine_confidence']}.", "",
          "| Doc | Format | Engine confidence | CER |", "|---|---|---|---|"]
    L += [f"| {o['doc']} | {o['format']} | {o['engine_mean_confidence']} | {o['character_error_rate']} |" for o in oc["documents"]]
    la = m["latency"]
    L += ["", "## Processing latency (measured on this machine)", "", f"- Native-text documents: median {la['native_ms_median']} ms ({la['documents_native']} docs)",
          f"- OCR documents: median {la['ocr_ms_median']} ms ({la['documents_ocr']} docs)", ""]
    rv = m["review_time"]
    L += ["## Review time", "", "**This is an automated reading-load estimate, not a human study.**", "",
          f"Assumptions: {rv['assumptions']}", "", "| Patient | Docs | Raw words | Structured words | Baseline (s, est.) | MedTrace (s, est.) |", "|---|---|---|---|---|---|"]
    L += [f"| {p['patient']} | {p['documents']} | {p['raw_words']} | {p['structured_words']} | {p['baseline_seconds_estimate']} | {p['medtrace_seconds_estimate']} |" for p in rv["per_patient"]]
    L += ["", f"Estimated reduction: {rv['estimated_reduction']}. Human sessions recorded: {rv['human_sessions_recorded']}.", "",
          "## Limitations", "", "- The dataset is small and synthetic; documents follow a limited set of layouts and phrasings.",
          "- Rules were developed while looking at patients A-E (development split). Development metrics are therefore optimistic; "
          "the hold-out patient F is the fairer estimate of generalisation, and it is very small.",
          "- Ground truth was written by the system author, not by independent clinical annotators.",
          "- The review-time figures are model-based estimates; no human reviewer study has been run.", "",
          "## Error listing (first 80)", "", "| Doc | Type | Item | Field | Expected | Got |", "|---|---|---|---|---|---|"]
    for e in ex["errors"][:80]:
        L.append(f"| {e['doc']} | {e['type']} | {e['item']} | {e['field']} | {str(e.get('expected', ''))[:50]} | {str(e.get('got', ''))[:60]} |")
    return "\n".join(L) + "\n"


def run_evaluation(out_dir: Path | None = None) -> dict:
    """Run in an isolated temporary data directory, then store the result in the configured DB."""
    original = get_settings()
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="medtrace_eval_") as tmp:
        eval_settings = Settings()
        eval_settings.data_dir = Path(tmp)
        eval_settings.admin_password = "eval-only-" + new_id("x")
        override_settings(eval_settings)
        try:
            metrics = evaluate()
        finally:
            override_settings(original)
    metrics["generated_at"] = now_iso()
    duration = round((time.perf_counter() - t0) * 1000, 1)
    report = to_markdown(metrics)
    init_db()
    rid = new_id("eval")
    with transaction() as conn:
        conn.execute("INSERT INTO evaluation_runs (id, created_at, dataset_version, extractor_version, duration_ms, metrics_json, report_markdown) VALUES (?,?,?,?,?,?,?)",
                     (rid, metrics["generated_at"], metrics["dataset"]["version"], EXTRACTOR_VERSION, duration, json.dumps(metrics), report))
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "latest_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / "EVALUATION_REPORT.md").write_text(report, encoding="utf-8")
    return {"id": rid, "created_at": metrics["generated_at"], "duration_ms": duration, "metrics_json": metrics}


def score_review_answers(conn, patient_id: str, answers: dict) -> dict:
    """Score a human review session's free-text answers against the patient's current findings."""
    meds = {(f["details"].get("normalized_name") or f["details"].get("name_as_written") or "").lower()
            for f in get_findings(conn, patient_id, "f.finding_type='medication' AND f.verification_status!='rejected'")}
    allergies = {(f["details"].get("normalized_substance") or "").lower()
                 for f in get_findings(conn, patient_id, "f.finding_type='allergy' AND f.verification_status!='rejected'")} - {""}
    txt_m = str(answers.get("medications", "")).lower()
    txt_a = str(answers.get("allergies", "")).lower()
    missed = [m for m in meds if m and m not in txt_m] + [a for a in allergies if a not in txt_a]
    correct = int(all(m in txt_m for m in meds if m)) + int(all(a in txt_a for a in allergies))
    return {"correct": correct, "missed": len(missed), "missed_items": missed}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[3] / "docs" / "evaluation"))
    a = ap.parse_args()
    import logging
    logging.getLogger("medtrace").setLevel(logging.WARNING)
    res = run_evaluation(Path(a.out))
    m = res["metrics_json"]
    print(json.dumps({"extraction_micro": m["extraction"]["micro"], "by_split": {k: v["micro"] for k, v in m["extraction_by_split"].items()},
                      "evidence": m["extraction"]["evidence"], "timeline": {k: v for k, v in m["timeline"].items() if k != "note"},
                      "duplicates": {k: m["duplicates"][k] for k in ("precision", "recall", "f1", "false_positive_rate")},
                      "conflicts": {k: m["conflicts"][k] for k in ("precision", "recall", "f1", "missed_conflicts", "false_positives")},
                      "qa": {k: v for k, v in m["qa"].items() if k != "results"}, "ocr_cer": m["ocr"]["mean_character_error_rate"]}, indent=1, default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
