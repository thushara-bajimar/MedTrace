"""Rules-based document classifier.

Each document type has weighted cue phrases. Title-like cues found in the first lines
count double. The score margin between the best and second-best type becomes the
classification confidence. Reviewers can override the type; the classifier output is
kept in ``doc_type_original``."""
from __future__ import annotations

import re

DOC_TYPES = ["lab_report", "prescription", "discharge_summary", "consultation_note", "imaging_report"]

CUES: dict[str, list[tuple[str, float]]] = {
    "lab_report": [
        (r"\blaboratory\b", 2), (r"\blab(oratory)? report\b", 3), (r"\btest\s+(name|description)\b", 2),
        (r"\breference (range|interval)\b", 2), (r"\bbiological ref", 2), (r"\bspecimen\b", 1.5),
        (r"\bsample (collected|date|type)\b", 2), (r"\bpathology\b", 1.5), (r"\bhaematology|hematology|biochemistry\b", 1.5),
        (r"\bresult\b", 0.5), (r"\bunits?\b", 0.5),
    ],
    "prescription": [
        (r"\bprescription\b", 3), (r"^\s*rx\b|\brx:", 2.5), (r"\btab\.|\bcap\.|\bsyp\.|\binj\.", 1.0),
        (r"\b(od|bd|tds|qid|hs|sos)\b", 0.5), (r"\bsignature of (the )?(doctor|physician)\b", 1), (r"\brefill", 1),
    ],
    "discharge_summary": [
        (r"\bdischarge summary\b", 4), (r"\bdate of admission\b", 2), (r"\bdate of discharge\b", 2),
        (r"\bhospital course\b", 2), (r"\bcondition (at|on) discharge\b", 2), (r"\bmedications? on discharge\b", 2),
        (r"\badmitted\b", 0.5),
    ],
    "consultation_note": [
        (r"\bconsultation\b", 3), (r"\bopd\b|\bout-?patient\b", 2), (r"\bchief complaints?\b", 2),
        (r"\bhistory of presenting|presenting complaint", 1.5), (r"\bexamination\b", 1), (r"\bassessment\b", 1),
        (r"\bplan\b", 0.5), (r"\bfollow[- ]?up\b", 0.5), (r"\bclinic note\b|\bprogress note\b", 2.5),
    ],
    "imaging_report": [
        (r"\bradiology\b", 3), (r"\bimaging\b", 2), (r"\bx-?ray\b", 2), (r"\bultrasound|usg\b|sonograph", 2),
        (r"\b(ct|mri)\b", 2), (r"\becho(cardiogra(m|phy))?\b|\b2d echo\b", 2), (r"\becg\b|\belectrocardiogra", 2),
        (r"\btechnique\b", 1), (r"\bimpression\b", 1), (r"\bfindings\b", 0.5),
    ],
}


def classify_document(text: str) -> tuple[str, float, dict[str, float]]:
    lower = text.lower()
    head = "\n".join(lower.splitlines()[:6])
    # OCR often drops spaces ("CONSULTATIONNOTE"); multi-letter cues are also tried on space-free text.
    compact, compact_head = re.sub(r"\s+", "", lower), re.sub(r"\s+", "", head)
    scores: dict[str, float] = {}
    for dtype, cues in CUES.items():
        sc = 0.0
        for pattern, weight in cues:
            rx = re.compile(pattern, re.M)
            cp = pattern.replace(r"\b", "").replace(" ", "")
            crx = re.compile(cp) if re.fullmatch(r"[a-z]{6,}", cp) else None
            if rx.search(lower) or (crx and crx.search(compact)):
                sc += weight
                if rx.search(head) or (crx and crx.search(compact_head)):
                    sc += weight  # title-like position
        scores[dtype] = round(sc, 2)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < 2:
        return "unclassified", 0.0, scores
    confidence = round(min(0.99, 0.5 + (best_score - second) / (best_score + 1e-9) * 0.5), 3)
    return best, confidence, scores
