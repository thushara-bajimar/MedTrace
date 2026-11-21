"""Timeline reconstruction, medication history, duplicates, contradictions and gaps (seeded synthetic data)."""
import io
from pathlib import Path

import pymupdf as fitz

from conftest import doc_id

DATASET = Path(__file__).resolve().parents[2] / "dataset" / "documents"


def test_timeline_is_chronological_and_uses_event_dates(admin_client, pid):
    t = admin_client.get(f"/api/patients/{pid['A']}/timeline").json()
    dates = [e["date_iso"] for e in t["dated"]]
    assert dates == sorted(dates, key=lambda d: (d + "-00-00")[:10] if len(d) < 10 else d)
    upload_dates = {e["upload_date"][:10] for e in t["dated"]}
    assert not ({e["date_iso"] for e in t["dated"]} & upload_dates)  # event dates, not upload dates
    adm = next(e for e in t["dated"] if e["event_type"] == "admission")
    assert adm["date_iso"] == "2024-02-03" and adm["date_text"] == "03/02/2024"   # original text preserved


def test_ambiguous_and_missing_dates_listed_separately(admin_client, pid):
    t = admin_client.get(f"/api/patients/{pid['E']}/timeline").json()
    und = t["undated_or_ambiguous"]
    assert any(e["date_status"] == "ambiguous" and e["date_text"] == "05/06/2023" for e in und)
    assert any(e["date_status"] == "missing" for e in und)
    assert all(e["date_iso"] for e in t["dated"])


def test_timeline_filters(admin_client, pid):
    base = f"/api/patients/{pid['A']}/timeline"
    meds = admin_client.get(base, params={"types": "medication"}).json()
    assert meds["dated"] and all(e["finding_type"] == "medication" for e in meds["dated"])
    rng = admin_client.get(base, params={"date_from": "2024-01-01", "date_to": "2024-12-31"}).json()
    assert rng["dated"] and all(e["date_iso"] >= "2024" for e in rng["dated"]) and not rng["undated_or_ambiguous"]
    q = admin_client.get(base, params={"q": "sitagliptin"}).json()
    assert q["dated"] and all("sitagliptin" in (e["summary"] + e["passage"]).lower() for e in q["dated"])


def test_medication_history_chronology_and_no_implied_current_use(admin_client, pid):
    h = admin_client.get(f"/api/patients/{pid['A']}/medications").json()["medications"]
    met = next(m for m in h if m["medication"] == "metformin")
    seq = [(m["date_iso"], m["strength"], m["status"]) for m in met["mentions"]]
    assert seq[0] == ("2023-01-10", "500 mg", "prescribed")
    assert ("2023-04-20", "1000 mg", "documented_changed") in seq
    assert "NOT established" in met["current_status_note"]
    sit = next(m for m in h if m["medication"] == "sitagliptin")
    assert any(c["kind"] == "documented_stopped" for c in sit["documented_changes"])
    gli = next(m for m in h if m["medication"] == "glimepiride")
    assert gli["mentions"][0]["status"] == "historical"


def test_allergy_explicit_negative_vs_not_documented_vs_conflict(admin_client, pid):
    a = admin_client.get(f"/api/patients/{pid['B']}/allergies").json()
    per_doc = {d["document_filename"][:2]: d["allergy_documentation"] for d in a["per_document"]}
    assert per_doc["B1"] == "allergy_documented"
    assert per_doc["B2"] == "explicit_negative"
    assert per_doc["B5"] == "not_documented"
    assert len(a["conflicts"]) == 3


def test_contradictions_detected_and_left_unresolved(admin_client, pid):
    c = admin_client.get(f"/api/patients/{pid['B']}/conflicts").json()
    assert {x["category"] for x in c} == {"allergy"}
    assert all(x["status"] == "unresolved" for x in c)
    assert all(len(x["evidence_json"]) == 2 and all(e["passage"] and e["page"] for e in x["evidence_json"]) for x in c)
    d = admin_client.get(f"/api/patients/{pid['D']}/conflicts").json()
    assert {x["category"] for x in d} == {"investigation_value"}
    assert all("LDL" in x["explanation"] for x in d)


def test_dose_change_across_dates_is_not_a_contradiction(admin_client, pid):
    c = admin_client.get(f"/api/patients/{pid['A']}/conflicts").json()
    assert not [x for x in c if x["category"] == "medication_dosage"]


def test_conflict_review_requires_explanation_and_keeps_history(admin_client, pid):
    c = admin_client.get(f"/api/patients/{pid['D']}/conflicts").json()[0]
    url = f"/api/patients/{pid['D']}/conflicts/{c['id']}/review"
    assert admin_client.post(url, json={"status": "resolved_by_documented_evidence"}).status_code == 400
    r = admin_client.post(url, json={"status": "resolved_by_documented_evidence", "note": "D3 is marked AMENDED by the laboratory."}).json()
    assert r["status"] == "resolved_by_documented_evidence"
    assert r["resolutions"][-1]["previous_status"] == "unresolved"
    assert len(r["evidence_json"]) == 2                        # evidence from both sources kept
    r = admin_client.post(url, json={"status": "unresolved", "note": "reopened"}).json()
    assert len(r["resolutions"]) == 2


def test_duplicates_exact_near_and_similar(admin_client, pid):
    dups = admin_client.get(f"/api/patients/{pid['D']}/duplicates", params={"level": "document"}).json()
    kinds = {frozenset((d["a"]["original_filename"][:2], d["b"]["original_filename"][:2])): d["kind"] for d in dups}
    assert kinds[frozenset(("D1", "D2"))] == "exact_duplicate"
    assert kinds[frozenset(("D1", "D3"))] == "near_duplicate"
    assert kinds[frozenset(("D5", "D6"))] == "near_duplicate"          # native vs scanned copy
    assert kinds[frozenset(("D1", "D4"))] == "similar_distinct"
    docs = admin_client.get(f"/api/patients/{pid['D']}/documents").json()
    assert len(docs) == 7                                               # nothing merged or deleted
    finding_dups = admin_client.get(f"/api/patients/{pid['D']}/duplicates", params={"level": "finding"}).json()
    assert any(d["kind"] == "duplicate_finding" for d in finding_dups)


def test_duplicate_review(admin_client, pid):
    d = admin_client.get(f"/api/patients/{pid['D']}/duplicates", params={"level": "document"}).json()[0]
    r = admin_client.post(f"/api/patients/{pid['D']}/duplicates/{d['id']}/review", json={"decision": "confirmed_duplicate"})
    assert r.status_code == 200
    again = next(x for x in admin_client.get(f"/api/patients/{pid['D']}/duplicates").json() if x["id"] == d["id"])
    assert again["review_status"] == "confirmed_duplicate"


def test_gaps_are_documentation_statements(admin_client, pid):
    g = admin_client.get(f"/api/patients/{pid['E']}/gaps").json()
    types = {x["gap_type"] for x in g}
    assert {"date_ambiguous", "medication_dosage_not_documented", "document_date_missing", "reference_range_missing",
            "allergy_status_not_recorded", "medication_status_uncertain"} <= types
    c = admin_client.get(f"/api/patients/{pid['C']}/gaps").json()
    assert any(x["gap_type"] == "unit_difference" and "creatinine" in x["description"] for x in c)
    assert all("NOT evidence" in x["description"] for x in g if x["gap_type"] == "allergy_status_not_documented")


def test_new_document_updates_history_without_overwriting(admin_client, pid):
    """Upload a new same-day prescription with a different strength: a dosage conflict appears,
    earlier findings remain, and the timeline gains the new mention."""
    p = pid["C"]
    before = admin_client.get(f"/api/patients/{p}/findings").json()
    d = fitz.open()
    page = d.new_page()
    for i, line in enumerate(["Greenfield Nephrology Clinic (Synthetic)", "PRESCRIPTION", "Patient: Chen Li (Synthetic C)",
                              "Date: 12-Feb-2024", "Rx:", "1. Tab. Telmisartan 80 mg OD"]):
        page.insert_text((50, 60 + 16 * i), line, fontsize=10)
    r = admin_client.post(f"/api/patients/{p}/documents", files={"file": ("C7_new_prescription.pdf", io.BytesIO(d.tobytes()), "application/pdf")})
    assert r.status_code == 202
    after = admin_client.get(f"/api/patients/{p}/findings").json()
    assert {f["id"] for f in before} <= {f["id"] for f in after}          # nothing overwritten
    conflicts = admin_client.get(f"/api/patients/{p}/conflicts").json()
    dose = [c for c in conflicts if c["category"] == "medication_dosage"]
    assert dose and "telmisartan" in dose[0]["explanation"]
    status = admin_client.get(f"/api/patients/{p}/documents/{r.json()['id']}/status").json()
    stages = [s["stage"] for s in status["runs"][0]["stages_json"]]
    assert stages[:3] == ["text_extraction_ocr", "classification", "structured_extraction"] and "conflict_detection" in stages


def test_document_endpoints(admin_client, pid):
    did = doc_id(admin_client, pid["A"], "A5")
    d = admin_client.get(f"/api/patients/{pid['A']}/documents/{did}").json()
    assert d["doc_type"] == "discharge_summary" and d["page_count"] == 2 and d["document_date_iso"] == "2024-02-07"
    assert d["sha256"] and "stored_filename" not in d
    t = admin_client.get(f"/api/patients/{pid['A']}/documents/{did}/text").json()
    assert len(t["pages"]) == 2 and t["pages"][1]["lines"]
    img = admin_client.get(f"/api/patients/{pid['A']}/documents/{did}/pages/2/image")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    f = admin_client.get(f"/api/patients/{pid['A']}/documents/{did}/file")
    assert f.status_code == 200 and f.content[:5] == b"%PDF-" and "attachment" in f.headers["content-disposition"]
    s = admin_client.get(f"/api/patients/{pid['A']}/documents", params={"q": "ceftriaxone"}).json()
    assert [x["id"] for x in s] == [did]
