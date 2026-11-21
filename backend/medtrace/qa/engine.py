"""Records-only question answering.

Pipeline: safety boundary check -> intent + entity detection -> retrieval (structured
findings + BM25 keyword search over the selected patient's page lines) -> evidence-backed,
templated answer with citations -> abstention when evidence is absent, conflicting,
ambiguous in date, or when the question asks for clinical judgement.

No language model generates text here: every statement in an answer is assembled from a
stored finding or a verbatim source line, so document text can never act as an
instruction (prompt-injection resistant by construction) and nothing can be invented.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter

from ..extract import lexicon
from ..extract.dates import find_dates, sort_key
from ..extract.extractor import CONDITION_SYNONYMS, RX_INJECTION
from ..db import rows
from ..store import get_findings
from ..views import MED_STATUS_LABEL, summarise

MAX_QUESTION_CHARS = 500

MSG_NO_EVIDENCE = "I could not find this information in the uploaded records."
MSG_CONFLICT = "The records contain conflicting statements. I cannot determine which is correct."
MSG_NOT_ESTABLISHED = "The records do not establish this fact."
MSG_ADVICE = ("MedTrace can retrieve documented medication and treatment information, but it cannot recommend medication changes, "
              "dosages or treatment. Please consult a qualified clinician.")
MSG_DIAGNOSIS = ("MedTrace is limited to what is documented in the records. It cannot diagnose, interpret results clinically, "
                 "or decide whether the patient has a condition.")
MSG_AMBIGUOUS_DATE = "The relevant date in the records is ambiguous (DD/MM vs MM/DD), so I cannot state it with confidence."

RX_ADVICE = re.compile(
    r"\b(should (?:i|he|she|they|we|the patient)\b|can (?:i|he|she|they|the patient) (?:take|stop|start|increase|reduce|skip)|is it safe|"
    r"(?:do you |would you )?recommend|what (?:dose|dosage) should|how much .{0,30} should|what (?:medicine|medication|drug|treatment) (?:should|to|would)|"
    r"(?:best|right) treatment|how (?:to|do i|should .{0,20}) treat|treatment for|prescribe (?:me|him|her)|ok to (?:take|stop)|"
    r"increase (?:the|his|her|my) dose|reduce (?:the|his|her|my) dose|change (?:the|his|her|my) (?:dose|medication))", re.I)
RX_DIAGNOSIS = re.compile(
    r"\b(diagnos(?:e|is for) (?:me|him|her|the patient|this)|what (?:is wrong|disease|illness)|does (?:the patient|he|she|this patient) (?:have|suffer)|"
    r"do i have|has (?:the patient|he|she) got|is (?:this|it|that) (?:cancer|serious|dangerous|normal|abnormal|bad|good|worrying)|"
    r"is (?:the|his|her|my|this) .{0,40} (?:normal|abnormal|too high|too low|high|low|ok|okay|concerning|dangerous|healthy)\??$|"
    r"what does .{0,40} (?:mean|indicate|suggest)|interpret|prognosis|will (?:he|she|the patient|i) (?:recover|die|need|get better)|"
    r"is (?:the patient|he|she) (?:diabetic|hypertensive|sick|healthy))", re.I)
RX_SPECULATIVE = re.compile(r"\b(likely|probably|predict|in the future|what caused|cause of)\b|"
                            r"\bwill\b.{0,50}\b(get worse|worsen|improve|progress|recover|happen|develop|need|be fine|get better|relapse)\b", re.I)
QUESTION_TEST_GROUPS = [
    (re.compile(r"thyroid", re.I), {"tsh", "free t4"}),
    (re.compile(r"lipid", re.I), {"total cholesterol", "ldl cholesterol", "hdl cholesterol", "triglycerides"}),
    (re.compile(r"glucose|sugar", re.I), {"fasting plasma glucose", "postprandial glucose", "random glucose"}),
    (re.compile(r"kidney function|renal function|\bkft\b|\brft\b", re.I), {"creatinine", "egfr", "urea"}),
    (re.compile(r"blood count|\bcbc\b|haemogram|hemogram", re.I), {"haemoglobin", "white cell count", "platelet count"}),
    (re.compile(r"liver function|\blft\b", re.I), {"alt", "ast"}),
]
RX_WHEN = re.compile(r"\bwhen\b|\bwhat date\b|\bwhich date\b", re.I)
RX_WHY = re.compile(r"^\s*why\b", re.I)
RX_REASON_WORDS = re.compile(r"\b(due to|because|owing to|secondary to|in view of|as a result of|for)\b", re.I)

INTENTS = [
    ("conflicts", re.compile(r"conflict|contradict|inconsisten|disagree|discrepan", re.I)),
    ("gaps", re.compile(r"\bmissing\b|not documented|\bgaps?\b|incomplete|what information is|information (?:is )?(?:absent|lacking)|undocumented", re.I)),
    ("medication_changes", re.compile(r"(medication|dose|dosage|drug|prescription)s?\b.{0,40}\b(chang|stop|discontinu|increas|decreas|switch|adjust)|"
                                      r"\b(chang|stop|discontinu|increas|decreas|switch)\w*\b.{0,40}\b(medication|dose|dosage|drug)|"
                                      r"\bwas .{1,40} (stopped|changed|increased|decreased|discontinued)\b", re.I)),
    ("allergy", re.compile(r"allerg|\bnkda\b|hypersensitiv", re.I)),
    ("investigation_last", re.compile(r"\b(last|latest|most recent|recent)\b.{0,30}\b(lab|laboratory|test|investigation|blood|report)", re.I)),
    ("current_medication", re.compile(r"\b(current(?:ly)?|now|at present|presently|still)\b.{0,40}\b(medication|medicine|drug|taking|on)\b|"
                                      r"\b(taking|on)\b.{0,20}\b(now|currently|at present)\b", re.I)),
    ("medication", re.compile(r"medication|medicine|\bdrugs?\b|prescri|tablet|\btaking\b|\bdose\b|dosage|strength", re.I)),
    ("event", re.compile(r"admi(?:t|ssion)|discharg|surgery|surgical|operat|procedure|consult|\bvisit|follow[- ]?up|hospital", re.I)),
    ("investigation", re.compile(r"\blabs?\b|laborator|\btests?\b|investigation|result|\bvalues?\b|\blevels?\b|x-?ray|scan|ultrasound|echo|\becg\b", re.I)),
    ("condition", re.compile(r"diagnos|condition|disease|history of|problem|\bmention", re.I)),
    ("documents", re.compile(r"\bdocuments?\b|\brecords?\b|\bfiles?\b|uploaded", re.I)),
]
DOC_TYPE_HINTS = [
    ("discharge_summary", re.compile(r"discharge summar", re.I)),
    ("prescription", re.compile(r"prescription", re.I)),
    ("lab_report", re.compile(r"lab(?:oratory)? report", re.I)),
    ("consultation_note", re.compile(r"consultation|clinic note|opd", re.I)),
    ("imaging_report", re.compile(r"imaging|radiology", re.I)),
]
RX_DETERMINATION = re.compile(r"^\s*(is|does|did|has|was|were|are)\b|^\s*what (?:is|was) (?:the|his|her) |"
                              r"\bhow much\b|\bwhich (?:one|value|dose) is (?:correct|right)\b", re.I)
RX_LISTING = re.compile(r"\b(which|what|list|show)\b.{0,30}\b(statements?|documented|appear|mentions?|recorded|records)\b", re.I)
STOP = set("the a an of in on at to for is was were are be been do does did has have had what which when who how any all with from "
           "this that these those patient patients record records document documents uploaded there their his her its by as and or "
           "me show list tell about please give".split())


# ---------------------------------------------------------------- retrieval helpers
def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in STOP and len(t) > 1]


def bm25_search(lines: list[dict], query: str, k: int = 8) -> list[tuple[float, dict]]:
    q = _tokens(query)
    if not q or not lines:
        return []
    docs = [_tokens(l["text"]) for l in lines]
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / n or 1
    df = Counter(t for d in docs for t in set(d))
    scored = []
    for d, l in zip(docs, lines):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avgdl))
        if s > 0:
            scored.append((s, l))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def _cite(f: dict) -> dict:
    return {"finding_id": f["id"], "document_id": f["document_id"], "document_filename": f["document_filename"],
            "document_type": f["document_type"], "page": f["page_number"], "line": f["line_start"], "passage": f["source_passage"]}


def _fact(f: dict, statement: str | None = None) -> dict:
    return {"statement": statement or summarise(f), "finding_type": f["finding_type"], "date_text": f["date_text"],
            "date_iso": f["date_iso"], "date_status": f["date_status"], "provenance_type": f["provenance_type"],
            "verification_status": f["verification_status"], "confidence_label": f["confidence_label"],
            "normalized": _normalized(f), "citation": _cite(f)}


def _normalized(f: dict) -> dict | None:
    d = f["details"]
    if f["finding_type"] == "medication" and d.get("normalized_name"):
        return {"normalized_name": d["normalized_name"], "note": "normalised name (not verbatim)"}
    if f["finding_type"] == "investigation" and d.get("converted_value") is not None:
        return {"converted": f"{d['converted_value']} {d['converted_unit']}", "rule": d.get("conversion_rule"),
                "note": "display-only conversion; the original value and unit above are the documented evidence"}
    if f["finding_type"] == "condition" and d.get("normalized_name"):
        return {"normalized_name": d["normalized_name"], "note": "normalised name (not verbatim)"}
    return None


def _date_word(f: dict) -> str:
    if f["date_status"] == "ambiguous":
        return f"date written '{f['date_text']}' (ambiguous)"
    if not f["date_text"]:
        return "date not documented"
    if f["date_status"] == "document_date":
        return f"record dated {f['date_text']}"
    return f["date_text"]


class Answer:
    def __init__(self, question: str):
        self.question = question
        self.status = "answered"
        self.answer = ""
        self.facts: list[dict] = []
        self.conflicts: list[dict] = []
        self.uncertainty: list[str] = []
        self.notes: list[str] = []
        self.related_passages: list[dict] = []
        self.retrieval: dict = {"methods": [], "findings_considered": 0, "lines_searched": 0}
        self.intent = None

    def to_dict(self) -> dict:
        cites, seen = [], set()
        for f in self.facts:
            c = f["citation"]
            key = (c["document_id"], c["page"], c["line"])
            if key not in seen:
                seen.add(key)
                cites.append(c)
        for p in self.related_passages:
            key = (p["document_id"], p["page"], p["line"])
            if key not in seen:
                seen.add(key)
                cites.append(p)
        return {"question": self.question, "retrieval_status": self.status, "answer": self.answer, "intent": self.intent,
                "facts": self.facts, "citations": cites, "conflicts": self.conflicts, "uncertainty": self.uncertainty,
                "notes": self.notes, "related_passages": self.related_passages, "retrieval": self.retrieval,
                "boundary": "Answers are assembled only from this patient's uploaded records. MedTrace does not diagnose or advise."}


# ---------------------------------------------------------------- main entry
def answer_question(conn: sqlite3.Connection, patient_id: str, question: str) -> dict:
    question = (question or "").strip()[:MAX_QUESTION_CHARS]
    a = Answer(question)
    if not question:
        a.status, a.answer = "abstained_no_evidence", "Please enter a question about the records."
        return a.to_dict()

    findings = get_findings(conn, patient_id, "f.verification_status != 'rejected'")
    lines = rows(conn, "SELECT document_id, page_number AS page, line_index AS line, text FROM page_lines WHERE patient_id=?", (patient_id,))
    docs = {d["id"]: d for d in rows(conn, "SELECT id, original_filename, doc_type, document_date_text FROM documents WHERE patient_id=?", (patient_id,))}
    conflicts = rows(conn, "SELECT * FROM conflicts WHERE patient_id=? AND still_detected=1 AND status NOT IN ('not_a_contradiction','resolved_by_documented_evidence')",
                     (patient_id,), json_fields=("evidence_json",))
    a.retrieval["findings_considered"] = len(findings)
    a.retrieval["lines_searched"] = len(lines)
    a.retrieval["methods"].append("structured_findings")

    entities = _entities(question, findings)
    doc_type = next((t for t, rx in DOC_TYPE_HINTS if rx.search(question)), None)
    if doc_type:
        findings_scoped = [f for f in findings if f["document_type"] == doc_type]
        a.notes.append(f"Scoped to documents classified as {doc_type.replace('_', ' ')}.")
    else:
        findings_scoped = findings

    # 1. medical boundary
    if RX_ADVICE.search(question):
        a.intent = "treatment_or_medication_advice"
        a.status, a.answer = "declined_clinical_advice", MSG_ADVICE
        _attach_documented_context(a, findings, entities, conflicts)
        return a.to_dict()
    if RX_DIAGNOSIS.search(question):
        a.intent = "diagnosis_or_interpretation"
        a.status, a.answer = "declined_clinical_judgement", MSG_DIAGNOSIS
        _attach_documented_context(a, findings, entities, conflicts)
        if a.facts:
            a.notes.append("Shown below is only what the records document about the terms in your question.")
        return a.to_dict()
    if RX_SPECULATIVE.search(question):
        a.intent = "unsupported_inference"
        a.status, a.answer = "declined_unsupported_inference", MSG_NOT_ESTABLISHED + " MedTrace does not speculate beyond the documents."
        return a.to_dict()
    if RX_WHY.search(question):
        return _why(a, question, findings, lines, docs, entities)

    intent = next((name for name, rx in INTENTS if rx.search(question)), None)
    if intent in ("medication", "condition", "investigation", None):
        if entities["medications"] and intent in (None, "condition", "investigation"):
            intent = "medication"
        elif entities["tests"] and intent in (None, "condition"):
            intent = "investigation"
        elif entities["conditions"] and intent in (None,):
            intent = "condition"
    a.intent = intent or "keyword_search"
    determination = bool(RX_DETERMINATION.search(question)) and not RX_LISTING.search(question)

    handler = {
        "conflicts": _conflicts, "gaps": _gaps, "medication_changes": _med_changes, "allergy": _allergy,
        "investigation_last": _last_investigation, "current_medication": _current_meds, "medication": _medications,
        "event": _events, "investigation": _investigations, "condition": _conditions, "documents": _documents,
    }.get(intent or "", None)
    if handler is None:
        _keyword(a, question, lines, docs)
    else:
        handler(a, question=question, findings=findings_scoped, all_findings=findings, lines=lines, docs=docs,
                conflicts=conflicts, entities=entities, determination=determination)

    # universal post-conditions
    if not a.facts and not a.related_passages and a.status == "answered":
        a.status, a.answer = "abstained_no_evidence", MSG_NO_EVIDENCE
    if a.facts and a.status == "answered":
        if any(f["date_status"] == "ambiguous" for f in a.facts):
            a.uncertainty.append("At least one cited fact has an ambiguous date; its position in time is uncertain.")
        if any(f["verification_status"] == "unverified" for f in a.facts):
            a.uncertainty.append("Some cited facts are machine-extracted and not yet human-verified.")
        if any(f["confidence_label"] == "low" for f in a.facts):
            a.uncertainty.append("Some cited facts have low extraction confidence (e.g. OCR text).")
        if a.conflicts:
            a.status = "answered_with_conflicts"
    return a.to_dict()


# ---------------------------------------------------------------- entities
def _entities(question: str, findings: list[dict]) -> dict:
    meds = {c for _, _, _, c in lexicon.find_medications(question)}
    for f in findings:
        if f["finding_type"] == "medication":
            n = (f["details"].get("name_as_written") or "").lower()
            if n and re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", question.lower()):
                meds.add(f["details"].get("normalized_name") or n)
    tests = set()
    for rx, canon, _cat in lexicon.TEST_PATTERNS:
        if rx.search(question):
            tests.add(canon)
    for rx, group in QUESTION_TEST_GROUPS:
        if rx.search(question):
            tests |= group
    conds = set()
    for p, canon in CONDITION_SYNONYMS.items():
        if re.search(p, question, re.I):
            conds.add(canon)
    allergens = {c for _, _, _, c in lexicon.find_allergens(question)}
    dates = {d.iso for d in find_dates(question) if d.iso}
    return {"medications": meds, "tests": tests, "conditions": conds, "allergens": allergens, "dates": dates}


def _date_scope(a: "Answer", items: list[dict], entities: dict) -> list[dict]:
    """If the question names a date, keep only findings documented for that date."""
    if not entities["dates"]:
        return items
    scoped = [f for f in items if f["date_iso"] and any(f["date_iso"].startswith(d) or d.startswith(f["date_iso"]) for d in entities["dates"])]
    a.notes.append(f"Scoped to findings dated {', '.join(sorted(entities['dates']))}.")
    return scoped


def _relevant_conflicts(conflicts: list[dict], finding_ids: set[str]) -> list[dict]:
    out = []
    for c in conflicts:
        ids = {e["finding_id"] for e in c["evidence_json"]}
        if ids & finding_ids:
            out.append({"conflict_id": c["id"], "category": c["category"], "explanation": c["explanation"], "status": c["status"],
                        "evidence": c["evidence_json"]})
    return out


def _attach_documented_context(a: Answer, findings, entities, conflicts) -> None:
    rel = []
    for f in findings:
        d = f["details"]
        if f["finding_type"] == "medication" and (d.get("normalized_name") in entities["medications"]):
            rel.append(f)
        elif f["finding_type"] == "condition" and d.get("normalized_name") in entities["conditions"]:
            rel.append(f)
        elif f["finding_type"] == "investigation" and d.get("normalized_test") in entities["tests"]:
            rel.append(f)
    a.facts = [_fact(f) for f in sorted(rel, key=lambda f: sort_key(f["date_iso"]))]
    a.conflicts = _relevant_conflicts(conflicts, {f["id"] for f in rel})


# ---------------------------------------------------------------- handlers
def _conflicts(a: Answer, findings, conflicts, entities, **_):
    a.retrieval["methods"].append("conflict_records")
    sel = conflicts
    names = entities["medications"] | entities["tests"] | entities["allergens"] | entities["conditions"]
    if names:
        sel = [c for c in conflicts if any(n in c["explanation"].lower() for n in names)]
    if not sel:
        a.status = "answered"
        a.answer = ("No conflicting statements were detected for this question in the uploaded records. "
                    "(Detection covers medication dose/status, allergies, event dates and same-day lab values.)")
        a.notes.append("Absence of a detected conflict is not proof that the records are consistent.")
        a.facts = []
        a.status = "answered_no_conflicts_detected"
        return
    a.conflicts = [{"conflict_id": c["id"], "category": c["category"], "explanation": c["explanation"], "status": c["status"],
                    "evidence": c["evidence_json"]} for c in sel]
    by_id = {f["id"]: f for f in findings}
    for c in sel:
        for e in c["evidence_json"]:
            f = by_id.get(e["finding_id"])
            if f:
                a.facts.append(_fact(f))
    a.answer = f"{len(sel)} conflicting statement set(s) were detected. They are shown with evidence from each source and have not been resolved automatically."
    a.status = "answered_with_conflicts"


def _gaps(a: Answer, findings, docs, **kw):
    conn_rows = kw.get("lines")  # unused; gaps are read below via findings' patient
    _ = conn_rows
    a.retrieval["methods"].append("gap_records")
    from ..analysis.gaps import compute_gaps

    doc_rows = [dict(v, extraction_status="completed", document_date_status=None, ocr_mean_confidence=None, injection_flags=None)
                for v in docs.values()]
    gaps = [g for g in compute_gaps(doc_rows, kw["all_findings"]) if g["gap_type"] != "document_date_missing"]
    by_id = {f["id"]: f for f in kw["all_findings"]}
    counts = Counter(g["gap_type"] for g in gaps)
    for g in gaps:
        f = by_id.get(g["finding_id"]) if g["finding_id"] else None
        if f:
            a.facts.append(_fact(f, g["description"]))
        elif g["document_id"] and g["document_id"] in docs:
            d = docs[g["document_id"]]
            a.notes.append(f"{d['original_filename']}: {g['description']}")
        else:
            a.notes.append(g["description"])
    if not gaps:
        a.answer = "No documentation gaps of the tracked kinds were found."
        a.status = "answered_no_gaps_detected"
        return
    a.answer = "Documentation gaps found: " + "; ".join(f"{k.replace('_', ' ')} ({v})" for k, v in counts.most_common()) + \
               ". Missing documentation is not a negative finding."


def _med_filter(findings, entities):
    meds = [f for f in findings if f["finding_type"] == "medication"]
    if entities["medications"]:
        meds = [f for f in meds if (f["details"].get("normalized_name") or (f["details"].get("name_as_written") or "").lower()) in entities["medications"]]
    return sorted(meds, key=lambda f: (sort_key(f["date_iso"]), f["document_id"]))


def _med_changes(a: Answer, findings, conflicts, entities, **_):
    meds = _med_filter(findings, entities)
    changes = [f for f in meds if f["details"].get("status") in ("documented_changed", "documented_stopped")]
    a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in changes]
    # strength differences between successive dated records of the same medication
    by_name: dict[str, list[dict]] = {}
    for f in meds:
        by_name.setdefault(f["details"].get("normalized_name") or f["details"]["name_as_written"].lower(), []).append(f)
    for name, group in by_name.items():
        dated = [f for f in group if f["date_iso"]]
        for p, c in zip(dated, dated[1:]):
            ps, cs = p["details"].get("strength"), c["details"].get("strength")
            if ps and cs and ps.replace(" ", "").lower() != cs.replace(" ", "").lower() and c["date_iso"] != p["date_iso"] and c not in changes:
                a.facts.append(_fact(c, f"{name}: {ps} in record dated {p['date_text']} -> {cs} in record dated {c['date_text']} "
                                        f"(difference between records; no explicit change statement)"))
    a.conflicts = _relevant_conflicts(conflicts, {f["id"] for f in meds})
    if a.facts:
        a.answer = f"{len(a.facts)} documented medication change/stop statement(s) or between-record differences were found."
    else:
        a.answer = "No medication change or stop is documented in the uploaded records." if meds else MSG_NO_EVIDENCE
        if meds:
            a.status = "answered_none_documented"
            a.notes.append("This means no change is documented, not that no change occurred.")


def _current_meds(a: Answer, findings, conflicts, entities, **_):
    meds = _med_filter(findings, entities)
    if not meds:
        return
    ongoing = [f for f in meds if f["details"].get("status") == "documented_ongoing"]
    latest_by_name: dict[str, dict] = {}
    for f in meds:
        latest_by_name[f["details"].get("normalized_name") or f["details"]["name_as_written"].lower()] = f
    a.conflicts = _relevant_conflicts(conflicts, {f["id"] for f in meds})
    if not ongoing:
        a.status = "abstained_not_established"
        a.answer = ("The records do not establish which medications are currently taken. No record explicitly documents a medication "
                    "as ongoing. The latest documented mention of each medication is listed instead.")
        a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in latest_by_name.values()]
        return
    a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in ongoing]
    a.answer = ("Medications explicitly documented as ongoing (as of each record's date). This does not confirm present-day use.")
    a.uncertainty.append("'Ongoing' reflects the wording of a dated record; later changes may not be documented.")


def _medications(a: Answer, findings, conflicts, entities, determination, **_):
    meds = _med_filter(findings, entities)
    if not meds:
        return
    rel_conf = _relevant_conflicts(conflicts, {f["id"] for f in meds})
    a.conflicts = rel_conf
    if determination and rel_conf and entities["medications"]:
        a.status, a.answer = "abstained_conflict", MSG_CONFLICT
        a.facts = [_fact(f) for f in meds if any(f["id"] in {e["finding_id"] for e in c["evidence"]} for c in rel_conf)]
        return
    a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in meds]
    names = sorted({f["details"].get("normalized_name") or f["details"]["name_as_written"] for f in meds})
    a.answer = (f"{len(meds)} medication mention(s) covering {len(names)} medication(s) are documented: {', '.join(names)}. "
                "Each is shown with its documented status; a mention does not prove current use.")


def _allergy(a: Answer, findings, conflicts, entities, determination, docs, **_):
    al = [f for f in findings if f["finding_type"] == "allergy"]
    if entities["allergens"]:
        al = [f for f in al if f["details"].get("normalized_substance") in entities["allergens"] or
              f["details"].get("assertion") in ("explicitly_denied_general", "status_not_recorded")]
    rel_conf = _relevant_conflicts(conflicts, {f["id"] for f in al})
    a.conflicts = rel_conf
    docs_with = {f["document_id"] for f in al}
    undocumented = [d for d in docs.values() if d["id"] not in docs_with and d["doc_type"] in ("discharge_summary", "consultation_note", "prescription")]
    for d in undocumented:
        a.notes.append(f"{d['original_filename']} ({d['doc_type'].replace('_', ' ')}): no allergy statement - status not documented in this record.")
    if not al:
        a.status, a.answer = "abstained_no_evidence", MSG_NO_EVIDENCE + " No allergy statement was found; this is not evidence of no allergies."
        return
    a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in sorted(al, key=lambda f: sort_key(f["date_iso"]))]
    if determination and rel_conf:
        a.status, a.answer = "abstained_conflict", MSG_CONFLICT + " Both statements are shown with their sources."
        return
    pos = [f for f in al if f["details"]["assertion"] == "documented_allergy"]
    neg = [f for f in al if f["details"]["assertion"].startswith("explicitly_denied")]
    parts = []
    if pos:
        parts.append("documented allergy: " + ", ".join(sorted({f["details"]["substance"] for f in pos})))
    if neg:
        parts.append(f"{len(neg)} explicit negative statement(s)")
    if any(f["details"]["assertion"] == "status_not_recorded" for f in al):
        parts.append("a record stating allergy status was not recorded")
    a.answer = "Allergy statements in the records - " + "; ".join(parts) + "."


def _investigations(a: Answer, question, findings, conflicts, entities, determination, **_):
    inv = [f for f in findings if f["finding_type"] == "investigation"]
    if entities["tests"]:
        inv = [f for f in inv if f["details"].get("normalized_test") in entities["tests"]]
    inv = _date_scope(a, inv, entities)
    if not inv:
        return
    inv.sort(key=lambda f: (sort_key(f["date_iso"]), f["document_id"]))
    a.conflicts = _relevant_conflicts(conflicts, {f["id"] for f in inv})
    if RX_WHEN.search(question) and all(f["date_status"] in ("ambiguous", "missing") for f in inv):
        a.status = "abstained_ambiguous_date" if any(f["date_status"] == "ambiguous" for f in inv) else "abstained_not_established"
        a.answer = MSG_AMBIGUOUS_DATE if a.status == "abstained_ambiguous_date" else "The records contain these results but do not document when the test was done."
        a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in inv]
        return
    if determination and a.conflicts:
        a.status, a.answer = "abstained_conflict", MSG_CONFLICT
        a.facts = [_fact(f) for f in inv]
        return
    a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in inv]
    units = {(f["details"].get("normalized_test"), (f["details"].get("unit") or "").lower()) for f in inv if f["details"].get("unit")}
    tests = {t for t, _ in units}
    if len(units) > len(tests):
        a.uncertainty.append("The same test is documented in different units across records. Original units are shown; "
                             "any converted value is display-only.")
    a.answer = f"{len(inv)} investigation result(s) are documented. Values and units are shown exactly as written; no clinical interpretation is given."


def _last_investigation(a: Answer, findings, conflicts, **_):
    inv = [f for f in findings if f["finding_type"] == "investigation"]
    dated = [f for f in inv if f["date_iso"]]
    if not dated:
        if inv:
            a.status, a.answer = "abstained_ambiguous_date", MSG_AMBIGUOUS_DATE
            a.facts = [_fact(f) for f in inv]
        return
    latest = max(sort_key(f["date_iso"]) for f in dated)
    last = [f for f in dated if sort_key(f["date_iso"]) == latest]
    a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in last]
    a.answer = f"The most recent documented investigation date is {last[0]['date_text']} ({len(last)} result(s))."
    amb = [f for f in inv if not f["date_iso"]]
    if amb:
        a.uncertainty.append(f"{len(amb)} investigation result(s) have ambiguous or missing dates and could not be placed in time.")


def _events(a: Answer, question, findings, conflicts, determination, **_):
    ev = [f for f in findings if f["finding_type"] == "event"]
    wanted = []
    for key, rx in (("admission", r"admi"), ("discharge", r"discharg"), ("surgery", r"surg|operat"), ("procedure", r"procedure"),
                    ("consultation", r"consult|visit"), ("follow_up", r"follow")):
        if re.search(rx, question, re.I):
            wanted.append(key)
    if "surgery" in wanted:
        wanted.append("procedure")
    if wanted:
        ev = [f for f in ev if f["details"]["event_type"] in wanted]
    if not ev:
        return
    ev.sort(key=lambda f: sort_key(f["date_iso"]))
    a.conflicts = _relevant_conflicts(conflicts, {f["id"] for f in ev})
    asks_when = bool(re.search(r"\bwhen\b|\bdate\b", question, re.I))
    if asks_when and a.conflicts:
        a.status, a.answer = "abstained_conflict", MSG_CONFLICT
        a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in ev]
        return
    if asks_when and all(f["date_status"] in ("ambiguous", "missing") for f in ev):
        a.status = "abstained_ambiguous_date" if any(f["date_status"] == "ambiguous" for f in ev) else "abstained_not_established"
        a.answer = MSG_AMBIGUOUS_DATE if a.status == "abstained_ambiguous_date" else "The records mention this event but do not document its date."
        a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in ev]
        return
    a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in ev]
    a.answer = f"{len(ev)} documented event(s) match the question."


def _conditions(a: Answer, question, findings, lines, docs, conflicts, entities, **_):
    conds = [f for f in findings if f["finding_type"] == "condition"]
    if entities["conditions"]:
        conds = [f for f in conds if f["details"].get("normalized_name") in entities["conditions"]]
    else:
        terms = [t for t in _tokens(question) if t not in {"diagnosis", "diagnoses", "condition", "conditions", "disease", "mention", "mentions", "history"}]
        if terms:
            conds = [f for f in conds if any(t in (f["details"].get("name_as_written") or "").lower() for t in terms)] or \
                    ([] if re.search(r"\bmention", question, re.I) else conds)
    if conds:
        a.facts = [_fact(f, f"{summarise(f)} ({_date_word(f)})") for f in sorted(conds, key=lambda f: sort_key(f["date_iso"]))]
        files = sorted({f["document_filename"] for f in conds})
        a.answer = (f"{len(conds)} condition statement(s) in {len(files)} document(s): {', '.join(files)}. "
                    "Statuses (e.g. suspected, ruled out, history of) are preserved as written.")
    if re.search(r"\bmention", question, re.I):
        _keyword(a, question, lines, docs, append=True)


def _documents(a: Answer, docs, **_):
    a.retrieval["methods"].append("document_index")
    if not docs:
        return
    for d in docs.values():
        a.related_passages.append({"document_id": d["id"], "document_filename": d["original_filename"], "document_type": d["doc_type"],
                                   "page": 1, "line": 0, "passage": f"{d['doc_type'].replace('_', ' ')} dated {d['document_date_text'] or 'not documented'}"})
    a.answer = f"{len(docs)} document(s) are uploaded for this patient."


def _keyword(a: Answer, question, lines, docs, append: bool = False):
    a.retrieval["methods"].append("bm25_keyword_search")
    hits = bm25_search(lines, question)
    q_terms = set(_tokens(question))
    added = 0
    for score, l in hits:
        if RX_INJECTION.search(l["text"]):
            a.notes.append("A matching passage contained instruction-like text; it was treated as data and not used.")
            continue
        coverage = len(q_terms & set(_tokens(l["text"]))) / len(q_terms) if q_terms else 0
        if score < 1.0 or coverage < 0.6:
            continue  # weak partial matches are not presented as evidence
        d = docs.get(l["document_id"], {})
        a.related_passages.append({"document_id": l["document_id"], "document_filename": d.get("original_filename"),
                                   "document_type": d.get("doc_type"), "page": l["page"], "line": l["line"], "passage": l["text"],
                                   "score": round(score, 2)})
        added += 1
    if added and not append:
        a.answer = f"No structured finding matched; {added} verbatim passage(s) from the records match the question's terms."
        a.uncertainty.append("Keyword matches are passages, not verified facts. Read them in context.")


def _why(a: Answer, question, findings, lines, docs, entities):
    a.intent = "reason_question"
    a.retrieval["methods"].append("bm25_keyword_search")
    hits = [h for h in bm25_search(lines, question, k=12) if RX_REASON_WORDS.search(h[1]["text"]) and not RX_INJECTION.search(h[1]["text"])]
    names = entities["medications"] | entities["tests"] | entities["conditions"]
    if names:
        aliases = set()
        for n in names:
            aliases |= set(lexicon.MEDICATIONS.get(n, [n]))
        hits = [h for h in hits if any(al in h[1]["text"].lower() for al in aliases)]
    if not hits:
        a.status, a.answer = "abstained_not_established", MSG_NOT_ESTABLISHED + " No documented reason was found."
        return a.to_dict()
    for score, l in hits[:3]:
        d = docs.get(l["document_id"], {})
        a.related_passages.append({"document_id": l["document_id"], "document_filename": d.get("original_filename"),
                                   "document_type": d.get("doc_type"), "page": l["page"], "line": l["line"], "passage": l["text"],
                                   "score": round(score, 2)})
    a.answer = "The records contain the following verbatim statement(s) that give a documented reason. MedTrace quotes them without interpretation."
    return a.to_dict()
