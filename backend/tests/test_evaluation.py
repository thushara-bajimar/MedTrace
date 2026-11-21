"""Evaluation framework: metric arithmetic and a full end-to-end evaluation run."""
from medtrace.evaluation.runner import category, fuzzy_in, match_doc, norm, prf


def test_prf_arithmetic():
    m = prf(8, 2, 2)
    assert m["precision"] == 0.8 and m["recall"] == 0.8 and m["f1"] == 0.8
    assert prf(0, 0, 0)["precision"] is None
    assert prf(0, 3, 0)["precision"] == 0.0
    assert prf(5, 0, 5)["recall"] == 0.5 and round(prf(5, 0, 5)["f1"], 4) == 0.6667


def test_normalisation_and_fuzzy_evidence_match():
    assert norm(" 4.0 - 5.6 ") == norm("4.0-5.6")
    assert fuzzy_in("Iodinated contrast", "Allergies: lodinated contrast - hives")
    assert not fuzzy_in("Penicillin", "Allergies: Sulfonamides - skin rash")


def test_status_categories():
    assert category("answered_with_conflicts") == "answer"
    assert category("abstained_conflict") == "abstain"
    assert category("declined_clinical_advice") == "decline"


def _pred(ftype, details, date_iso=None, passage="", fid="x"):
    return {"id": fid, "finding_type": ftype, "details": details, "date_iso": date_iso, "source_passage": passage}


def test_matching_counts_tp_fp_fn():
    gt = [{"type": "medication", "name": "metformin", "strength": "500 mg", "frequency": "twice daily", "status": "prescribed",
           "date_iso": "2023-01-10", "page": 1, "evidence": "Metformin"},
          {"type": "allergy", "substance": None, "assertion": "explicitly_denied_general", "reaction": None, "page": 1, "evidence": "NKDA"}]
    preds = [_pred("medication", {"normalized_name": "metformin", "strength": "500 mg", "frequency": "twice daily", "status": "prescribed"},
                   "2023-01-10", "Tab. Metformin 500 mg", "p1"),
             _pred("medication", {"normalized_name": "aspirin", "strength": "75 mg"}, None, "Aspirin", "p2")]
    pairs, fn, fp = match_doc(gt, preds)
    assert len(pairs) == 1 and pairs[0][1]["id"] == "p1"
    assert len(fn) == 1 and fn[0]["type"] == "allergy"
    assert [f["id"] for f in fp] == ["p2"]


def test_full_evaluation_run_produces_measured_metrics(tmp_path, seeded):
    from medtrace.evaluation.runner import run_evaluation

    res = run_evaluation(tmp_path)
    m = res["metrics_json"]
    assert m["dataset"]["documents"] >= 25 and m["dataset"]["patients"] >= 5
    ex = m["extraction"]
    for t in ("condition", "medication", "allergy", "investigation", "event"):
        assert ex["entity"][t]["precision"] is not None and ex["entity"][t]["recall"] is not None
    assert 0 < ex["micro"]["f1"] <= 1
    assert ex["evidence"]["evidence_completeness"] == 1.0
    assert m["timeline"]["pairwise_ordering_accuracy"] is not None
    assert m["duplicates"]["recall"] is not None and m["conflicts"]["recall"] is not None
    assert m["qa"]["unsupported_answer_rate"] is not None and m["qa"]["cross_patient_citation_rate"] == 0.0
    assert m["review_time"]["is_human_study"] is False
    assert (tmp_path / "EVALUATION_REPORT.md").read_text(encoding="utf-8").startswith("# MedTrace Evaluation Report")
