# Testing and Evaluation

## Test methodology
`backend/tests/` contains **77 automated tests** (Pytest + FastAPI TestClient). The session fixture creates an isolated temporary data directory and seeds the synthetic dataset through the real pipeline (including OCR), so API tests exercise the full system. Run: `cd backend && python -m pytest -q` (~70 s on the development laptop; OCR dominates).

| File | Covers |
|---|---|
| `test_dates_units.py` | unambiguous/ambiguous numeric dates, declared conventions, textual/partial dates, two-digit years, explicit unit conversions |
| `test_extraction.py` | condition qualifiers, medication fields and "not documented", status changes/stops/history/uncertain, allergy assertions, investigations with original units and ranges, events, verbatim evidence, prompt-injection lines, OCR fuzzy lexicon |
| `test_ingestion.py` | extension/magic mismatch, empty/oversize files, PDF JavaScript/launch rejection, corrupt images, filename traversal, native text with line boxes, OCR on an image upload, scanned PDF OCR, classification |
| `test_api_security.py` | 401 without session, CSRF requirement, lockout path, cookie flags, security headers, reviewer isolation, cross-patient 404s, mixed-ID access, QA isolation, viewer read-only, weak passwords, malicious uploads, page-route traversal, prompt injection inertness, identifier-only audit log |
| `test_timeline_conflicts.py` | chronological order with event (not upload) dates, ambiguous/missing section, filters, medication chronology and no implied current use, allergy explicit-negative vs not-documented vs conflict, contradictions left unresolved, dose change ≠ contradiction, conflict review with explanation + history, exact/near/similar duplicates, duplicate review, gaps, new-document update without overwriting, document endpoints |
| `test_corrections_qa.py` | evidence page/passage/bbox, OCR provenance, correction versioning with original preserved and timeline update, verify/reject, page-text correction, review queue; supported/missing/conflicting/ambiguous-date questions, diagnosis/treatment/interpretation/speculation refusal, unit preservation in answers, current-medication caution, reason quoting, question-text escalation, answer history |
| `test_evaluation.py` | P/R/F1 arithmetic, normalisation and fuzzy evidence matching, status categories, matching TP/FP/FN, a full end-to-end evaluation run |

Last run: **77 passed** (2026-11-21).

## Synthetic dataset and ground truth
`dataset/generate_dataset.py` renders 36 documents for 6 fictional patients and writes `dataset/ground_truth.json`. Annotations were written by hand next to each document's text and record **what the document says**, independent of the extractor: conditions with documented status, medications with strength/frequency/status/date, allergies with assertion and reaction, investigations with value/unit/reference range/date, events with dates, evidence page + snippet, document types and dates, duplicate pairs (7 labelled), conflicts (8 positives + 1 negative control) and 38 questions with expected behaviour (answer / abstain / decline), required citations and required content.

**Split:** patients A–E are the *development* split (rules were refined while viewing them). Patient F is a *hold-out* split written before any rule tuning and never used to tune rules.

## Metrics
- **Entity detection** — per type, matching within each document by type + key (normalised name / test / substance + assertion / event type), greedy best attribute agreement. Precision, recall, F1; micro-average.
- **Attribute accuracy** — on matched findings: medication strength, frequency, status, date; investigation value, unit, reference range, date; allergy assertion, reaction; condition status, date; event date.
- **Evidence** — page reference accuracy, passage accuracy (ground-truth snippet fuzzily contained in the cited passage, ≥ 0.8 similarity for OCR), evidence completeness (verbatim span present on the cited page), document classification and document date accuracy.
- **Timeline** — event date accuracy; pairwise ordering accuracy over all pairs of distinct-day items per patient; medication chronology; historical/current status accuracy; missing/ambiguous handling (no fabricated date).
- **Duplicates** — precision/recall for exact+near duplicates over all same-patient pairs; false-positive rate over non-duplicate pairs; kind accuracy on labelled pairs.
- **Contradictions** — precision/recall by (category, document pair); negative control must not be flagged; auto-resolution count.
- **QA** — status category accuracy, evidence-supported answer accuracy, citation accuracy, abstention accuracy, unsupported-answer rate, over-abstention, missing-evidence detection, cross-patient citation rate.
- **OCR** — character error rate of OCR text vs the known source text, plus engine confidence.
- **Latency** — measured per-document processing time.

## Results (measured 2026-11-21, extractor rules-1.0.0)
Full report with per-question and per-error tables: [evaluation/EVALUATION_REPORT.md](evaluation/EVALUATION_REPORT.md). Pre-tuning report: [evaluation/BASELINE_BEFORE_TUNING.md](evaluation/BASELINE_BEFORE_TUNING.md).

| Entity type | Precision | Recall | F1 | TP / FP / FN |
|---|---|---|---|---|
| Condition | 1.000 | 1.000 | 1.000 | 21 / 0 / 0 |
| Medication | 1.000 | 0.926 | 0.962 | 50 / 0 / 4 |
| Allergy | 1.000 | 1.000 | 1.000 | 13 / 0 / 0 |
| Investigation | 1.000 | 1.000 | 1.000 | 50 / 0 / 0 |
| Event | 0.978 | 0.978 | 0.978 | 44 / 1 / 1 |
| **Micro** | **0.994** | **0.973** | **0.983** | 178 / 1 / 5 |

| Split | Docs | P | R | F1 | F1 before tuning |
|---|---|---|---|---|---|
| Development (A–E) | 31 | 1.000 | 1.000 | 1.000 | 0.984 |
| Hold-out (F) | 5 | 0.964 | 0.844 | **0.900** | 0.871 |

Attribute accuracy on matched findings: all fields 100 % except medication status 49/50 (hold-out omeprazole: "Current medications" read as *prescribed*, annotated *ongoing*).

| Area | Result |
|---|---|
| Evidence | page 1.000 · passage 0.938 · completeness 1.000 · classification 1.000 · document date 1.000 |
| Timeline | event date 1.000 (125) · ordering 1.000 (1,068 pairs) · medication chronology 1.000 (41) · historical/current 0.929 (14) · no fabricated dates 1.000 (40) |
| Duplicates | P 1.000 · R 1.000 · FP rate 0.000 (87 negative pairs) · kind accuracy 1.000 (7) |
| Contradictions | P 1.000 · R 0.875 (dev 5/5, hold-out 2/3) · negative control not flagged · auto-resolved 0 |
| QA (38 q) | overall 0.947 (dev 1.000, hold-out 0.600) · status 1.000 · evidence-supported answers 0.958 · citations 0.923 · abstention 1.000 · unsupported answers 0.000 · over-abstention 0.000 · cross-patient citations 0 |
| OCR (7 docs) | mean CER 0.036 · mean engine confidence 0.991 |
| Latency | native PDF median 138 ms (29 docs) · OCR median 5.8 s (7 docs) |

Before tuning, QA abstention accuracy was 0.643 and the unsupported-answer rate 0.357; the general fixes (test-group synonyms, date-scoped questions, speculative-question detection, keyword coverage threshold, abstention on ambiguous *when* questions) brought development QA to 1.0. The hold-out failures remain and are kept visible:
- *propranolol* is not in the medication lexicon → 4 missed mentions and one wrong QA answer;
- "after appendicectomy on 29 June 2024" is not recognised as a procedure statement → missed surgery event and missed event-date conflict;
- a spurious follow-up event from "Post-operative review after …".

## Review-time comparison
**No human reviewer study has been performed.** Two mechanisms exist:
1. An **automated reading-load proxy** (in the evaluation report): words a reviewer would read in all raw documents vs in the structured medication/allergy/investigation rows, at 200 wpm, plus 10 s per document opened (baseline) and 6 s per spot-check of 25 % of facts (MedTrace). Result: 916.8 s vs 589.8 s estimated across the six patients (−36 %). This is a model with stated assumptions, not a measurement.
2. A **Review-time study** page that records real timed sessions (baseline: original documents only; MedTrace: timeline and evidence viewer) for four tasks, with automatic scoring of medication and allergy completeness. Recorded sessions are stored in `review_sessions` with `participant_kind = 'human'` and reported separately.

## Limitations
Small, synthetic, author-annotated dataset with limited layouts; development metrics are optimistic by construction; the hold-out split has only 5 documents and 32 findings; the OCR test images are clean renders with mild noise, much easier than real phone photos; QA questions were written by the developer and mostly follow supported phrasings.
