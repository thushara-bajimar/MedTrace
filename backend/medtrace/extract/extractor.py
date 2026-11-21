"""Deterministic, rules-based structured extraction.

Input: ordered page lines (native or OCR text). Output: ``RawFinding`` objects, each tied
to a page + line range + verbatim passage. Nothing is inferred that is not written:
absent attributes stay ``None`` ("not documented"), qualifiers such as *suspected* or
*history of* are preserved as a status, and medication mentions are never promoted to
"currently taking" unless the text says so.

Known limitation (documented): rules + lexicons only recognise phrasing they encode.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lexicon
from .dates import DateMention, declared_convention, find_dates, first_date


@dataclass
class SrcLine:
    page: int
    index: int
    text: str
    source: str               # native | ocr
    confidence: float | None  # OCR line confidence


@dataclass
class RawFinding:
    finding_type: str
    page: int
    line_start: int
    line_end: int
    source_passage: str
    original_text: str
    data: dict
    section: str | None
    date: DateMention | None = None
    date_status: str = "missing"
    date_role: str | None = None
    temporal_status: str | None = None
    confidence: float = 0.9
    reasons: list[str] = field(default_factory=list)
    extraction_method: str = "rules_native_text"


@dataclass
class DocMeta:
    doc_date: DateMention | None
    doc_date_label: str | None
    provider: str | None
    convention: str | None
    injection_flags: list[str]


# ---------------------------------------------------------------- sections
SECTION_RX = re.compile(
    r"^\s*(?P<h>(?:final |provisional |principal |secondary )?diagnos[ie]s|impression|assessment|problem list|"
    r"past (?:medical |surgical )?history|medical history|history|known history|"
    r"(?:drug )?allerg(?:y|ies)(?: status)?|"
    r"medications? (?:on|at) discharge|discharge medications?|current medications?|medications? stopped|"
    r"stopped medications?|medication changes?|medications?|drug history|treatment given|treatment|rx|prescription|"
    r"advice(?: on discharge)?|plan|"
    r"investigations?(?: done| results?)?|lab(?:oratory)? results|results|"
    r"hospital course|course in hospital|procedures?(?: done| performed)?|operation(?: notes?)?|surgery|"
    r"chief complaints?|presenting complaints?|history of presenting illness|examination|"
    r"follow[- ]?up|review|findings|technique|condition (?:at|on) discharge)\s*[:\-]\s*(?P<rest>.*)$",
    re.I,
)
HEADING_ONLY_RX = re.compile(r"^\s*([A-Z][A-Z &/]{3,})\s*$")
# Any other "Label: value" line ends the current section (e.g. "Note: ..." after "Allergies: NKA"),
# unless the label is itself a test or medication name ("Chest X-ray: ..." inside Investigations).
GENERIC_LABEL_RX = re.compile(r"^\s*([A-Za-z][A-Za-z /()\-]{1,30}):\s*\S")

SECTION_MAP = [
    (r"diagnos|impression|assessment|problem list", "diagnosis"),
    (r"history of presenting|complaint", "complaints"),
    (r"history", "history"),
    (r"allerg", "allergies"),
    (r"stopped", "medications_stopped"),
    (r"medication changes?", "medication_changes"),
    (r"medication|drug history|treatment|^rx$|prescription", "medications"),
    (r"advice|plan", "advice"),
    (r"investigation|result", "investigations"),
    (r"hospital course|course in hospital", "hospital_course"),
    (r"procedure|operation|surgery", "procedure"),
    (r"examination", "examination"),
    (r"follow|review", "follow_up"),
    (r"findings|technique", "findings"),
    (r"condition", "condition_at_discharge"),
]


def _section_name(heading: str) -> str:
    h = heading.lower().strip()
    for pattern, name in SECTION_MAP:
        if re.search(pattern, h):
            return name
    return "other"


def split_sections(lines: list[SrcLine]) -> list[tuple[SrcLine, str | None, str]]:
    """Return (line, section, content) where content excludes a leading heading label."""
    out = []
    current: str | None = None
    for ln in lines:
        m = SECTION_RX.match(ln.text)
        if m:
            current = _section_name(m.group("h"))
            out.append((ln, current, m.group("rest").strip()))
            continue
        g = GENERIC_LABEL_RX.match(ln.text)
        if g and not lexicon.find_test(g.group(1)) and not lexicon.find_medications(g.group(1)):
            current = "other"
            out.append((ln, current, ln.text.strip()))
            continue
        m2 = HEADING_ONLY_RX.match(ln.text)
        if m2 and len(ln.text.split()) <= 5:
            sec = _section_name(m2.group(1))
            if sec != "other":
                current = sec
                out.append((ln, current, ""))
                continue
        out.append((ln, current, ln.text.strip()))
    return out


# ---------------------------------------------------------------- shared helpers
RX_LIST_PREFIX = re.compile(r"^\s*(?:\d+[.)]|[-•*]|\(\w\))\s*")
RX_INJECTION = re.compile(
    r"(ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)|disregard (?:the |all )?(?:previous|above|system)|"
    r"system prompt|you are now|act as (?:an? )?(?:doctor|admin)|grant (?:access|admin)|delete (?:all|the) (?:records|patients)|"
    r"new instructions?:|assistant\s*:|override (?:the )?(?:rules|policy)|reveal (?:the )?(?:password|other patients))",
    re.I,
)


def _base_confidence(ln: SrcLine) -> tuple[float, list[str], str]:
    if ln.source == "human_corrected":
        return 0.92, ["human-corrected page text"], "rules_human_corrected_text"
    if ln.source == "ocr":
        oc = ln.confidence if ln.confidence is not None else 0.7
        return min(0.9, oc) - 0.05, [f"OCR text (line OCR confidence {oc:.2f})"], "rules_ocr_text"
    return 0.92, ["native PDF text layer"], "rules_native_text"


def _label(score: float) -> str:
    return "high" if score >= 0.8 else "medium" if score >= 0.6 else "low"


# ---------------------------------------------------------------- medications
RX_STRENGTH = re.compile(r"(\d+(?:\.\d+)?\s?(?:mg|mcg|µg|g|ml|mL|IU|units?)(?:\s?/\s?\d*(?:\.\d+)?\s?(?:mg|ml|mL|dose))?)(?![A-Za-z])", re.I)
RX_FROM_TO = re.compile(r"from\s+(\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|IU|units?))\s+to\s+(\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|IU|units?))", re.I)
RX_DOSAGE = re.compile(r"\b((?:\d+(?:\.\d+)?|one|two|three|half|1/2)\s+(?:tablets?|tabs?|capsules?|caps?|puffs?|drops?|sachets?|teaspoons?|tsp))\b", re.I)
RX_ROUTE = re.compile(r"\b(oral(?:ly)?|by mouth|p\.o\.|po|i\.v\.|iv|intravenous(?:ly)?|i\.m\.|intramuscular(?:ly)?|s\.c\.|subcutaneous(?:ly)?|"
                      r"inhaled|inhalation|via inhaler|topical(?:ly)?|sublingual|nebuli[sz]ed|per rectum)\b", re.I)
RX_FREQ = re.compile(r"(\b(?:once|twice|thrice) (?:daily|a day|weekly)\b|\bthree times (?:a|per) day\b|\bfour times (?:a|per) day\b|"
                     r"\bevery \d+ hours\b|\bq\d+h\b|\b[0-2]-[0-2]-[0-2]\b|\bo\.d\.|\bb\.d\.|\b(?:od|bd|bid|tds|tid|qid|hs|qhs|sos|prn|stat)\b|"
                     r"\bat (?:night|bedtime)\b|\bin the morning\b|\bas (?:needed|required)\b|\bwhen required\b|\bdaily\b|\bweekly\b)", re.I)
RX_DURATION = re.compile(r"(?:\bx\s*|×\s*|\bfor\s+)(\d+\s*(?:days?|weeks?|months?))\b", re.I)
RX_STOP = re.compile(r"\b(stop(?:ped)?|discontinu(?:e|ed)|withdrawn|ceased|held|withheld)\b", re.I)
RX_CHANGE = re.compile(r"\b(increase[ds]?|decrease[ds]?|reduce[ds]?|changed?|switch(?:ed)?|titrat(?:e|ed)|dose (?:modified|adjusted|revised)|uptitrated|tapered?)\b", re.I)
RX_ONGOING = re.compile(r"\b(continue[ds]?|ongoing|currently (?:on|taking)|on regular|remains on|taking)\b", re.I)
RX_HIST = re.compile(r"\b(previously|in the past|was on|history of|h/o|formerly|earlier|years ago|took|had been on|past use|"
                     r"treated with|was given|were given|received|administered)\b", re.I)
RX_ATTR_UNKNOWN = re.compile(r"\b(?:dose|strength|frequency|dosage)\s+(?:not known|unknown|not documented|not recorded)\b", re.I)
RX_UNCERTAIN = re.compile(r"(\?|\bunclear\b|\bunsure\b|\bnot sure\b|\bpossibly\b|\bmay be taking\b|\buncertain\b|\bunknown whether\b|"
                          r"\breportedly\b|\bnot confirmed\b|\bstatus unknown\b|\bnot known\b)", re.I)
RX_FORM_PREFIX = re.compile(r"\b(tab|tablet|cap|capsule|inj|injection|syp|syrup|inh|oint)\.?\s+([A-Z][A-Za-z0-9\-]{2,})", re.I)
RX_START_DATE = re.compile(r"\b(?:started|commenced|initiated|since|from)\b", re.I)
RX_STOP_DATE = re.compile(r"\b(?:stopped|discontinued|ceased|until|till)\b", re.I)

PRESCRIBING_SECTIONS = {"medications", "medication_changes", "advice"}


def _med_status(segment: str, line: str, section: str | None, doc_type: str) -> tuple[str, list[str]]:
    seg_and_line = segment + " " + line
    segment = RX_ATTR_UNKNOWN.sub(" ", segment)  # an unknown *dose* is a gap, not status uncertainty
    if RX_UNCERTAIN.search(segment):
        return "uncertain", ["uncertainty marker in text"]
    if section == "history":
        return "historical", ["past-history section (any stop/change described there is historical)"]
    if section == "hospital_course":
        return "historical", ["administered during the documented admission (hospital course)"]
    if section == "medications_stopped" or RX_STOP.search(segment):
        return "documented_stopped", ["stop wording in text" if RX_STOP.search(segment) else "listed under a 'stopped' heading"]
    if RX_CHANGE.search(segment) or RX_FROM_TO.search(segment):
        return "documented_changed", ["change wording in text"]
    if section == "history" or RX_HIST.search(segment):
        return "historical", ["historical wording or past-history section"]
    if RX_ONGOING.search(seg_and_line):
        return "documented_ongoing", ["continuation wording in text"]
    if section in PRESCRIBING_SECTIONS or doc_type == "prescription":
        return "prescribed", [f"listed in {section or doc_type} section"]
    return "mentioned_only", ["mentioned outside a prescribing context"]


TEMPORAL_FOR_MED = {
    "documented_stopped": "discontinued",
    "documented_changed": "updated",
    "historical": "historical",
    "documented_ongoing": "current_as_documented",
    "uncertain": "uncertain",
    "prescribed": "unknown",        # prescribed on a date; present-day use is NOT established
    "mentioned_only": "unknown",
}


def extract_medications(ln: SrcLine, section: str | None, content: str, doc_type: str, conv: str | None) -> list[RawFinding]:
    if section == "allergies" or re.search(r"allerg|intoleran", content, re.I):
        return []
    if section in {"investigations", "findings"}:
        return []
    mentions = [(s, e, t, c, True) for s, e, t, c in lexicon.find_medications(content)]
    if not mentions and ln.source == "ocr":
        mentions = [(s, e, t, c, True) for s, e, t, c in lexicon.fuzzy_find(content, lexicon.MEDICATIONS)]
    for m in RX_FORM_PREFIX.finditer(content):
        s, e = m.start(2), m.end(2)
        if all(e <= a or s >= b for a, b, *_ in mentions):
            mentions.append((s, e, m.group(2), None, False))
    mentions.sort()
    out = []
    for i, (s, e, written, canon, in_lexicon) in enumerate(mentions):
        seg_end = mentions[i + 1][0] if i + 1 < len(mentions) else len(content)
        # include a leading form prefix (e.g. "Tab.") in the as-written span
        pre = re.search(r"(?:\b(?:tab|tablet|cap|capsule|inj|syp|syrup)\.?\s+)$", content[:s], re.I)
        seg_start = pre.start() if pre else s
        segment = content[seg_start:seg_end].strip(" ,;")
        # status cues may precede the name ("Stopped metformin", "Increase amlodipine to ...")
        lead = content[mentions[i - 1][1] if i else 0:s]
        status_text = lead + " " + segment
        after = content[e:seg_end]
        data = {"name_as_written": written, "normalized_name": canon}
        ft = RX_FROM_TO.search(after)
        if ft:
            data["strength"] = ft.group(2)
            data["previous_strength"] = ft.group(1)
        else:
            sm = RX_STRENGTH.search(after)
            data["strength"] = sm.group(1) if sm else None
        dm = RX_DOSAGE.search(after)
        data["dosage"] = dm.group(1) if dm else None
        rm = RX_ROUTE.search(after)
        data["route"] = rm.group(1) if rm else None
        fm = RX_FREQ.search(after)
        data["frequency"] = fm.group(1) if fm else None
        du = RX_DURATION.search(after)
        data["duration"] = du.group(1) if du else None
        status, why = _med_status(status_text, content, section, doc_type)
        data["status"] = status
        data["start_date_text"] = None
        data["stop_date_text"] = None
        seg_dates = find_dates(status_text, conv)
        date = None
        for d in seg_dates:
            before = status_text[max(0, d.start - 25):d.start]
            if RX_STOP_DATE.search(before):
                data["stop_date_text"] = d.text
                date = date or d
            elif RX_START_DATE.search(before):
                data["start_date_text"] = d.text
                date = date or d
        if date is None and seg_dates:
            date = seg_dates[0]
        conf, reasons, method = _base_confidence(ln)
        reasons += why
        if not in_lexicon:
            conf -= 0.12
            reasons.append("name not in medication lexicon (form-prefix pattern)")
        if data["strength"] is None:
            conf -= 0.05
            reasons.append("strength not documented")
        if status == "uncertain":
            conf -= 0.08
        f = RawFinding("medication", ln.page, ln.index, ln.index, ln.text, segment, data, section,
                       temporal_status=TEMPORAL_FOR_MED[status], confidence=conf, reasons=reasons, extraction_method=method)
        if date is not None:
            f.date = date
            f.date_status = date.status
            f.date_role = "stop_date" if data["stop_date_text"] == date.text else "start_date" if data["start_date_text"] == date.text else "date_in_text"
        out.append(f)
    return out


# ---------------------------------------------------------------- conditions
CONDITION_SYNONYMS = {
    r"\bt2dm\b|type 2 diabetes(?: mellitus)?|type ii diabetes(?: mellitus)?|\bdm type 2\b": "type 2 diabetes mellitus",
    r"\bhtn\b|hypertension|high blood pressure": "hypertension",
    r"\bckd\b|chronic kidney disease": "chronic kidney disease",
    r"\bcad\b|coronary artery disease": "coronary artery disease",
    r"\bcopd\b": "chronic obstructive pulmonary disease",
    r"hypothyroidism": "hypothyroidism",
    r"\basthma\b|bronchial asthma": "asthma",
    r"dyslipid(?:a)?emia|hyperlipid(?:a)?emia": "dyslipidaemia",
    r"\banaemia\b|\banemia\b": "anaemia",
    r"pneumonia": "pneumonia",
    r"cholecystitis": "cholecystitis",
    r"cholelithiasis|gall ?stones?": "cholelithiasis",
    r"urinary tract infection|\buti\b": "urinary tract infection",
    r"tuberculosis|\btb\b": "tuberculosis",
    r"osteoarthritis": "osteoarthritis",
    r"migraine": "migraine",
    r"gastritis": "gastritis",
    r"atrial fibrillation|\baf\b": "atrial fibrillation",
    r"heart failure": "heart failure",
    r"myocardial infarction|\bmi\b": "myocardial infarction",
    r"appendicitis": "appendicitis",
    r"vitamin d deficiency": "vitamin d deficiency",
    r"dengue": "dengue fever",
    r"cellulitis": "cellulitis",
}
_COND_RX = [(re.compile(p, re.I), n) for p, n in CONDITION_SYNONYMS.items()]
RX_PROCEDURE_WORD = re.compile(r"\b\w*(ectomy|otomy|ostomy|plasty|scopy|surgery|operation|repair|replacement|bypass|stenting|angioplasty|"
                               r"caesarean|cesarean|c-section|biopsy|transfusion|cabg|pci)\b", re.I)
RX_SURGERY_WORD = re.compile(r"(ectomy|otomy|ostomy|surgery|operation|repair|replacement|bypass|caesarean|cesarean|c-section|cabg)", re.I)

COND_QUALIFIERS = [
    ("explicitly_denied", re.compile(r"^\s*(?:no (?:known )?(?:history of|h/o)|denies|not a known case of|no evidence of)\s+", re.I)),
    ("ruled_out", re.compile(r"\b(?:ruled out|was excluded|excluded)\b|^\s*(?:negative for)\s+", re.I)),
    ("suspected", re.compile(r"^\s*(?:\?|suspected|query|rule out|r/o|to rule out)\s*|\bsuspected\b|\(\?\)|\?$", re.I)),
    ("possible", re.compile(r"^\s*(?:possible|probable|likely)\b|\b(?:possible|probable|cannot be excluded)\b", re.I)),
    ("known_case", re.compile(r"^\s*(?:known case of|k/c/o|known)\b", re.I)),
    ("history_of", re.compile(r"^\s*(?:history of|h/o|past history of|previous|old)\b", re.I)),
]
RX_COND_TRIGGER = re.compile(r"\b(known case of|k/c/o|diagnosed (?:with|as)|history of|h/o|suspected|no history of)\b", re.I)
RX_STRIP_QUAL = re.compile(r"^\s*(?:\?|suspected|query|rule out|r/o|to rule out|possible|probable|likely|known case of|k/c/o|known|"
                           r"history of|h/o|past history of|previous|old|no (?:known )?(?:history of|h/o)|denies|not a known case of|"
                           r"no evidence of|negative for|diagnosed (?:with|as))\s*", re.I)
RX_COND_TAIL = re.compile(r"\s*(?:-|,)?\s*(?:ruled out|was excluded|excluded|\(\?\)|\?|cannot be excluded)\s*\.?$", re.I)
RX_SINCE = re.compile(r"\s*(?:\(|,)?\s*(?:since|in|diagnosed in|from|for)\s+((?:\w+\s+)?(?:19|20)\d{2}|\d+\s+years?)\)?\s*$", re.I)


def _normalise_condition(name: str) -> str | None:
    for rx, canon in _COND_RX:
        if rx.search(name):
            return canon
    return None


def _split_items(content: str) -> list[tuple[int, str]]:
    """Split a diagnosis list on ';' and ',' outside parentheses; keep offsets."""
    items, depth, start = [], 0, 0
    for i, ch in enumerate(content):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch in ";," and depth == 0:
            items.append((start, content[start:i]))
            start = i + 1
    items.append((start, content[start:]))
    return [(s + (len(t) - len(t.lstrip())), t.strip()) for s, t in items if t.strip()]


def extract_conditions(ln: SrcLine, section: str | None, content: str, doc_type: str, conv: str | None) -> list[RawFinding]:
    if doc_type in {"lab_report", "imaging_report"} or not content:
        return []
    in_dx = section in {"diagnosis", "history"}
    if not in_dx and not RX_COND_TRIGGER.search(content):
        return []
    if section == "allergies" or re.search(r"allerg", content, re.I):
        return []
    text = RX_LIST_PREFIX.sub("", content)
    if not in_dx:
        m = RX_COND_TRIGGER.search(text)
        text = text[m.start():]
    out = []
    for _, item in _split_items(text) if in_dx else [(0, text.split(".")[0])]:
        if lexicon.find_medications(item) or RX_PROCEDURE_WORD.search(item):
            continue  # medication or procedure history is handled by other extractors
        if len(item) < 3 or len(item) > 120 or re.match(r"^(nil|none|nad|not significant|unremarkable)\b", item, re.I):
            continue
        if re.match(r"^(stopped|started|continued?|changed|due to|was|were|on|taking|treated|given|advised|planned)\b", item, re.I):
            continue  # clause about treatment, not a condition name
        status = "history_of" if section == "history" else "confirmed_as_documented"
        for st, rx in COND_QUALIFIERS:
            if rx.search(item):
                status = st
                break
        date = None
        sm = RX_SINCE.search(item)
        name = item
        if sm:
            name = item[:sm.start()]
            date = first_date(sm.group(0), conv)
        name = RX_COND_TAIL.sub("", RX_STRIP_QUAL.sub("", name)).strip(" .:-")
        if not name or len(name) < 3:
            continue
        conf, reasons, method = _base_confidence(ln)
        canon = _normalise_condition(name)
        if canon is None:
            conf -= 0.08
            reasons.append("condition text not in synonym list (kept as written)")
        reasons.append(f"status '{status}' from documented wording/section")
        f = RawFinding("condition", ln.page, ln.index, ln.index, ln.text, item,
                       {"name_as_written": name, "normalized_name": canon, "status_as_documented": status, "classification": None},
                       section, confidence=conf, reasons=reasons, extraction_method=method,
                       temporal_status="historical" if status == "history_of" else "unknown")
        if date:
            f.date, f.date_status, f.date_role = date, date.status, "onset_or_diagnosis_date_as_written"
        out.append(f)
    return out


# ---------------------------------------------------------------- allergies
RX_NEG_GENERAL = re.compile(r"\b(nkda|nka|no known (?:drug |food )?allerg(?:y|ies)|denies (?:any )?(?:drug )?allerg(?:y|ies)|no allerg(?:y|ies)|"
                            r"no drug allerg(?:y|ies))\b", re.I)
RX_NEG_SPECIFIC = re.compile(r"\b(?:no (?:known )?allergy to|not allergic to|denies (?:any )?allergy to|tolerates)\s+([A-Za-z \-]+)", re.I)
RX_NOT_RECORDED = re.compile(r"\ballerg(?:y|ies)(?: status)?\s*[:\-]?\s*(?:not (?:recorded|assessed|documented|known|elicited)|unknown|unable to obtain)", re.I)
RX_POS = re.compile(r"\b(?:allergic to|allergy to|allergies?\s*[:\-]|hypersensitivity to|intolerance to|reaction to)\s*(.+)$", re.I)
REACTIONS = r"(anaphylaxis|angio-?o?edema|urticaria|hives|rash|skin rash|itching|pruritus|swelling|wheez(?:e|ing)|bronchospasm|breathlessness|nausea|vomiting|stevens-johnson syndrome|blisters)"
RX_REACTION = re.compile(REACTIONS, re.I)
RX_SEVERITY = re.compile(r"\b(mild|moderate|severe|life[- ]threatening)\b", re.I)


def extract_allergies(ln: SrcLine, section: str | None, content: str, doc_type: str, conv: str | None) -> list[RawFinding]:
    full = ln.text
    if section != "allergies" and not re.search(r"allerg|nkda|\bnka\b|hypersensitivity", full, re.I):
        return []
    if doc_type in {"lab_report", "imaging_report"}:
        return []
    conf, reasons, method = _base_confidence(ln)

    def mk(data, span, extra_reason):
        return RawFinding("allergy", ln.page, ln.index, ln.index, ln.text, span, data, section, confidence=conf,
                          reasons=reasons + [extra_reason], extraction_method=method, temporal_status="current_as_documented")

    if RX_NOT_RECORDED.search(full):
        return [mk({"substance": None, "normalized_substance": None, "reaction": None, "severity": None,
                    "assertion": "status_not_recorded"}, RX_NOT_RECORDED.search(full).group(0), "document states allergy status was not recorded")]
    out = []
    neg_sp = RX_NEG_SPECIFIC.search(full)
    if neg_sp:
        subs = lexicon.find_allergens(neg_sp.group(1))
        written = subs[0][2] if subs else neg_sp.group(1).strip()
        out.append(mk({"substance": written, "normalized_substance": subs[0][3] if subs else None, "reaction": None, "severity": None,
                       "assertion": "explicitly_denied_specific"}, neg_sp.group(0).strip(), "explicit negative for a named substance"))
        return out
    if RX_NEG_GENERAL.search(full):
        out.append(mk({"substance": None, "normalized_substance": None, "reaction": None, "severity": None,
                       "assertion": "explicitly_denied_general"}, RX_NEG_GENERAL.search(full).group(0), "explicit general negative (e.g. NKDA)"))
        return out
    pm = RX_POS.search(content if section == "allergies" and content else full) or (RX_POS.search(full) if section != "allergies" else None)
    target = pm.group(1) if pm else (content if section == "allergies" else "")
    if not target:
        return out
    subs = lexicon.find_allergens(target)
    fuzzy = False
    if not subs and ln.source == "ocr":
        subs = lexicon.fuzzy_find(target, lexicon.ALLERGENS)
        fuzzy = bool(subs)
        if fuzzy:
            reasons = reasons + ["OCR-tolerant fuzzy lexicon match (verify spelling against image)"]
    if not subs:
        word = re.match(r"\s*([A-Za-z][A-Za-z\- ]{2,30}?)(?:\s*[(\-,:;]|$)", target)
        if word and not RX_REACTION.fullmatch(word.group(1).strip()):
            subs = [(word.start(1), word.end(1), word.group(1).strip(), None)]
    for i, (s, e, written, canon) in enumerate(subs):
        seg = target[s:subs[i + 1][0] if i + 1 < len(subs) else len(target)]
        rx = RX_REACTION.search(seg)
        sv = RX_SEVERITY.search(seg)
        c = conf - (0.1 if canon is None else 0) - (0.1 if fuzzy else 0)
        f = mk({"substance": written, "normalized_substance": canon, "reaction": rx.group(1) if rx else None,
                "severity": sv.group(1) if sv else None, "assertion": "documented_allergy"}, seg.strip(" ,;"), "allergy wording with named substance")
        f.confidence = c
        out.append(f)
    return out


# ---------------------------------------------------------------- investigations
RX_VALUE = re.compile(r"(?<![\w.])([<>≤≥]?\s?\d+(?:\.\d+)?)(?![\w.]*\s*(?:days?|weeks?|months?|years?|yrs?)\b)")
RX_RANGE = re.compile(r"(\d+(?:\.\d+)?\s?(?:-|–|to)\s?\d+(?:\.\d+)?(?:\s?(?:mg/dL|mmol/L|g/dL|%|U/L))?|[<>≤≥]\s?\d+(?:\.\d+)?|up to \d+(?:\.\d+)?)")
RX_FLAG = re.compile(r"(?:^|\s)(H|L|High|Low|HIGH|LOW|\*)(?=\s|$)")
UNITLESS_OK = {"inr"}


def _parse_lab_chunk(chunk: str, conv: str | None):
    t = lexicon.find_test(chunk)
    if t is None:
        return None
    ts, te, written, canon, cat = t
    if cat != "laboratory":
        return None
    rest = chunk[te:]
    rest_clean = re.sub(r"^[\s:,\-()]*", "", rest)
    # skip things like "(Fasting)" or "(Serum)" qualifiers before the value
    vm = RX_VALUE.search(rest)
    if vm is None:
        return None
    value_text = vm.group(1).replace(" ", "")
    after = rest[vm.end():]
    um = lexicon.RX_UNIT.match(after.lstrip())
    unit = um.group(1) if um else None
    after_unit = after.lstrip()[um.end():] if um else after
    ref = None
    rm = RX_RANGE.search(after_unit)
    if rm:
        ref = rm.group(1).strip()
    if unit is None and ref is None and canon not in UNITLESS_OK:
        return None
    if unit is None and canon in {"egfr"}:
        return None
    flag = None
    fm = RX_FLAG.search(after_unit[: rm.start()] if rm else after_unit)
    if fm:
        flag = fm.group(1)
    else:
        fm2 = re.search(r"\b(H|L|High|Low)\s*$", after_unit)
        if fm2:
            flag = fm2.group(1)
    try:
        num = float(re.sub(r"[<>≤≥]", "", value_text))
    except ValueError:
        num = None
    data = {"test_name": written.strip(), "normalized_test": canon, "category": "laboratory", "value_text": value_text,
            "value_numeric": num, "unit": unit, "reference_range": ref, "flag_as_written": flag}
    conv_ = lexicon.convert(canon, num, unit)
    data["converted_value"], data["converted_unit"], data["conversion_rule"] = conv_ if conv_ else (None, None, None)
    _ = rest_clean
    return data


def extract_investigations(ln: SrcLine, section: str | None, content: str, doc_type: str, conv: str | None,
                           test_date: DateMention | None) -> list[RawFinding]:
    out = []
    if not content:
        return out
    lab_context = doc_type == "lab_report" or section in {"investigations"}
    conf, reasons, method = _base_confidence(ln)
    if lab_context:
        chunks = [content] if doc_type == "lab_report" else [c for _, c in _split_items(content)]
        for chunk in chunks:
            data = _parse_lab_chunk(chunk, conv)
            if data is None:
                # imaging mention inside an investigations section, e.g. "Chest X-ray: no consolidation"
                t = lexicon.find_test(chunk)
                if t and t[4] == "imaging" and doc_type != "lab_report":
                    res = re.sub(r"^[\s:\-]+", "", chunk[t[1]:]).strip()
                    if res:
                        data = {"test_name": t[2], "normalized_test": t[3], "category": "imaging", "value_text": res,
                                "value_numeric": None, "unit": None, "reference_range": None, "flag_as_written": None,
                                "converted_value": None, "converted_unit": None, "conversion_rule": None}
                if data is None:
                    continue
            c = conf
            r = list(reasons)
            if data["category"] == "laboratory" and data["reference_range"] is None:
                r.append("reference range not documented")
                c -= 0.03
            line_date = first_date(chunk, conv)
            f = RawFinding("investigation", ln.page, ln.index, ln.index, ln.text, chunk.strip(), data, section,
                           confidence=c, reasons=r, extraction_method=method, temporal_status="historical")
            d = line_date or test_date
            if d:
                f.date = d
                f.date_status = d.status if line_date else ("document_date" if d.status == "parsed" else d.status)
                f.date_role = "test_date_in_line" if line_date else "specimen_or_report_date"
            out.append(f)
    return out


def extract_imaging_report(lines: list[tuple[SrcLine, str | None, str]], doc_date: DateMention | None) -> list[RawFinding]:
    test = None
    for ln, sec, content in lines[:8]:
        t = lexicon.find_test(ln.text)
        if t and t[4] == "imaging":
            test = (ln, t)
            break
    if test is None:
        return []
    impression = None
    for ln, sec, content in lines:
        if re.match(r"^\s*impression\s*[:\-]", ln.text, re.I):
            impression = (ln, content)
            break
    ln, t = test
    src = impression[0] if impression and impression[1] else ln
    result = impression[1] if impression and impression[1] else None
    conf, reasons, method = _base_confidence(src)
    if result is None:
        reasons.append("no impression line found; result not documented")
        conf -= 0.1
    f = RawFinding("investigation", src.page, src.index, src.index, src.text, result or ln.text,
                   {"test_name": t[2], "normalized_test": t[3], "category": "imaging", "value_text": result, "value_numeric": None,
                    "unit": None, "reference_range": None, "flag_as_written": None, "converted_value": None, "converted_unit": None,
                    "conversion_rule": None}, "impression", confidence=conf, reasons=reasons, extraction_method=method,
                   temporal_status="historical")
    if doc_date:
        f.date, f.date_status, f.date_role = doc_date, ("document_date" if doc_date.status == "parsed" else doc_date.status), "study_date"
    return [f]


# ---------------------------------------------------------------- events
RX_ADMIT = re.compile(r"\b(?:date of admission|admission date|admitted on|DOA)\s*[:\-]?\s*", re.I)
RX_DISCH = re.compile(r"\b(?:date of discharge|discharge date|discharged on|DOD)\s*[:\-]?\s*", re.I)
RX_PROC = re.compile(r"\b(?:underwent|procedure(?:s)?(?: done| performed)?\s*[:\-]|operation(?: performed)?\s*[:\-]|surgery\s*[:\-]|s/p|status post)\s*(.+)$", re.I)
RX_FOLLOW = re.compile(r"\b(?:follow[- ]?up|review|next visit|revisit)\b\s*(?:on|after|in|:|-|at)?\s*(.+)$", re.I)


def extract_events(ln: SrcLine, section: str | None, content: str, doc_type: str, conv: str | None) -> list[RawFinding]:
    out = []
    text = ln.text
    conf, reasons, method = _base_confidence(ln)

    def mk(etype, desc, span, date, role, temporal="historical", extra=None):
        c = conf
        r = list(reasons) + ([extra] if extra else [])
        f = RawFinding("event", ln.page, ln.index, ln.index, ln.text, span.strip(), {"event_type": etype, "description": desc.strip()},
                       section, confidence=c, reasons=r, extraction_method=method, temporal_status=temporal)
        if date:
            f.date, f.date_status, f.date_role = date, date.status, role
            if date.status == "ambiguous":
                f.confidence -= 0.15
                f.reasons.append("event date is ambiguous")
        else:
            f.confidence -= 0.15
            f.reasons.append("event date not documented")
        return f

    for rx, etype in ((RX_ADMIT, "admission"), (RX_DISCH, "discharge")):
        m = rx.search(text)
        if m:
            d = first_date(text[m.end():], conv)
            out.append(mk(etype, "Hospital " + etype, text[m.start():], d, f"{etype}_date"))
    if doc_type in {"lab_report"}:
        return out
    pm = RX_PROC.search(text)
    hist_proc = section == "history" and RX_PROCEDURE_WORD.search(text) and not lexicon.find_medications(text)
    if (pm and RX_PROCEDURE_WORD.search(pm.group(1))) or hist_proc:
        target = pm.group(1) if pm else RX_LIST_PREFIX.sub("", content)
        etype = "surgery" if RX_SURGERY_WORD.search(target) else "procedure"
        d = first_date(target, conv)
        desc = re.split(r"\s+(?:on|in|dated)\s+(?=\d|[A-Z][a-z]{2})", target)[0]
        desc = re.sub(r"\s*\((?:\d{4}|[^)]*\d{4}[^)]*)\)\s*$", "", desc).strip(" .,")
        if d and d.text in desc:
            desc = desc.replace(d.text, "").strip(" .,()-")
        out.append(mk(etype, desc, target, d, "procedure_date", extra="procedure wording in text"))
    if section == "follow_up" or RX_FOLLOW.search(text):
        fm = RX_FOLLOW.search(text)
        planned = fm and re.search(r"\d|\b(?:one|two|three|four|six|a)\s+(?:days?|weeks?|months?)|\b(?:opd|clinic|department)\b",
                                   fm.group(1), re.I)
        if planned and not re.search(r"\blost to follow", text, re.I):
            target = fm.group(1)
            d = first_date(target, conv)
            out.append(mk("follow_up", "Follow-up as documented: " + target.strip(" ."), text[fm.start():], d, "planned_follow_up_date",
                          temporal="planned_as_documented", extra="follow-up plan wording; relative intervals are not converted to dates"))
    return out


# ---------------------------------------------------------------- document metadata
DOC_DATE_LABELS = [
    ("discharge_summary", r"date of discharge|discharge date"),
    ("lab_report", r"report(?:ed)? (?:date|on)|date of report"),
    ("lab_report", r"(?:sample )?collected on|collection date|date of collection|sample date"),
    ("imaging_report", r"date of (?:study|examination|scan)|study date|exam date"),
    (None, r"date of (?:visit|consultation|prescription|issue)|visit date|consultation date"),
    (None, r"\bdate\s*(?=[:\-])"),
]
RX_PROVIDER = re.compile(r"(hospital|clinic|laborator(?:y|ies)|\blabs?\b|diagnostics|medical cent(?:re|er)|health ?care|imaging|radiology|nursing home|polyclinic)", re.I)
RX_SPECIMEN_DATE = re.compile(r"(?:sample )?collected on|collection date|date of collection|sample date|specimen date", re.I)


def document_metadata(all_lines: list[SrcLine], doc_type: str) -> DocMeta:
    full = "\n".join(l.text for l in all_lines)
    conv = declared_convention(full)
    doc_date, label = None, None
    for dtype, pattern in DOC_DATE_LABELS:
        if dtype not in (None, doc_type):
            continue
        rx = re.compile(r"(" + pattern + r")\s*[:\-]?\s*", re.I)
        for ln in all_lines:
            m = rx.search(ln.text)
            if m:
                d = first_date(ln.text[m.end():], conv)
                if d:
                    doc_date, label = d, m.group(1)
                    break
        if doc_date:
            break
    provider = None
    for ln in all_lines[:6]:
        if RX_PROVIDER.search(ln.text) and len(ln.text) < 90:
            provider = ln.text.strip()
            break
    flags = [ln.text for ln in all_lines if RX_INJECTION.search(ln.text)]
    return DocMeta(doc_date, label, provider, conv, flags)


def specimen_date(all_lines: list[SrcLine], conv: str | None) -> DateMention | None:
    for ln in all_lines:
        m = RX_SPECIMEN_DATE.search(ln.text)
        if m:
            d = first_date(ln.text[m.end():], conv)
            if d:
                return d
    return None


# ---------------------------------------------------------------- orchestrator
def extract_document(all_lines: list[SrcLine], doc_type: str) -> tuple[DocMeta, list[RawFinding]]:
    meta = document_metadata(all_lines, doc_type)
    conv = meta.convention
    sectioned = split_sections(all_lines)
    findings: list[RawFinding] = []
    test_date = specimen_date(all_lines, conv) or meta.doc_date
    injection_lines = {id(l) for l in all_lines if RX_INJECTION.search(l.text)}

    for ln, section, content in sectioned:
        if id(ln) in injection_lines:
            continue  # instruction-like text is flagged and never turned into facts
        findings += extract_events(ln, section, content, doc_type, conv)
        if doc_type == "imaging_report":
            continue
        findings += extract_allergies(ln, section, content, doc_type, conv)
        findings += extract_conditions(ln, section, content, doc_type, conv)
        findings += extract_medications(ln, section, content, doc_type, conv)
        findings += extract_investigations(ln, section, content, doc_type, conv, test_date)

    if doc_type == "imaging_report":
        findings += extract_imaging_report(sectioned, meta.doc_date)

    # document-level events (consultation / investigation report) anchored on the title line
    title = all_lines[0] if all_lines else None
    if title is not None:
        conf, reasons, method = _base_confidence(title)
        if doc_type == "consultation_note":
            f = RawFinding("event", title.page, title.index, title.index, title.text, title.text,
                           {"event_type": "consultation", "description": "Consultation documented"}, None,
                           confidence=conf, reasons=reasons + ["document classified as consultation note"],
                           extraction_method=method, temporal_status="historical")
            findings.append(f)
        elif doc_type in {"lab_report", "imaging_report"}:
            n = sum(1 for f in findings if f.finding_type == "investigation")
            f = RawFinding("event", title.page, title.index, title.index, title.text, title.text,
                           {"event_type": "investigation", "description": f"Investigation report ({n} result{'s' if n != 1 else ''} extracted)"},
                           None, confidence=conf, reasons=reasons + ["document classified as investigation report"],
                           extraction_method=method, temporal_status="historical")
            findings.append(f)
        for f in findings[-1:]:
            if f.finding_type == "event" and f.data["event_type"] in {"consultation", "investigation"} and f.date is None:
                d = test_date if doc_type == "lab_report" else meta.doc_date
                if d:
                    f.date, f.date_status, f.date_role = d, d.status, "document_date"
                else:
                    f.confidence -= 0.15
                    f.reasons.append("document date not documented")

    # inherit the document date for undated medication/condition findings (marked as such)
    for f in findings:
        if f.date is None and f.finding_type in {"medication", "allergy"} and meta.doc_date is not None:
            f.date = meta.doc_date
            f.date_status = "document_date" if meta.doc_date.status == "parsed" else meta.doc_date.status
            f.date_role = "documented_in_record_dated"
        if f.date is not None and f.date.status == "ambiguous" and "date is ambiguous" not in " ".join(f.reasons):
            f.reasons.append("date is ambiguous (DD/MM vs MM/DD)")
            f.confidence -= 0.1 if f.finding_type != "event" else 0
        f.confidence = round(max(0.05, min(0.99, f.confidence)), 3)
    return meta, findings


def label_for(score: float) -> str:
    return _label(score)
