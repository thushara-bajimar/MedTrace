# MedTrace Evaluation Report

Generated: 2026-11-21T07:04:56+00:00  
Extractor: `rules-1.0.0`  
Dataset: `synthetic-v1` (synthetic; 6 patients, 36 documents, 183 annotated findings, 38 questions)  
Hold-out patients (never used to tune rules): F

All numbers below are measured by `python -m medtrace.evaluation.runner` against hand-written ground truth, except the review-time section, which is an explicitly labelled automated estimate.

## Dataset

| Document type | Count |
|---|---|
| prescription | 7 |
| lab_report | 12 |
| consultation_note | 10 |
| discharge_summary | 4 |
| imaging_report | 3 |

| Format | Count |
|---|---|
| pdf | 29 |
| scan_pdf | 3 |
| png | 3 |
| jpg | 1 |

## Extraction (entity detection)

| Type | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| condition | 1.0 | 1.0 | 1.0 | 21 | 0 | 0 |
| medication | 1.0 | 0.9259 | 0.9615 | 50 | 0 | 4 |
| allergy | 1.0 | 1.0 | 1.0 | 13 | 0 | 0 |
| investigation | 1.0 | 1.0 | 1.0 | 50 | 0 | 0 |
| event | 0.9778 | 0.9778 | 0.9778 | 44 | 1 | 1 |
| **micro (all)** | **0.9944** | **0.9727** | **0.9834** | 178 | 1 | 5 |

### Development vs hold-out

| Split | Docs | Precision | Recall | F1 |
|---|---|---|---|---|
| development | 31 | 1.0 | 1.0 | 1.0 |
| holdout | 5 | 0.9643 | 0.8438 | 0.9 |

### Attribute (field-level) accuracy on matched findings

| Type | Field | Correct / Total | Accuracy |
|---|---|---|---|
| condition | status | 21 / 21 | 1.0 |
| condition | date_iso | 21 / 21 | 1.0 |
| allergy | assertion | 13 / 13 | 1.0 |
| allergy | reaction | 13 / 13 | 1.0 |
| medication | strength | 50 / 50 | 1.0 |
| medication | frequency | 50 / 50 | 1.0 |
| medication | status | 49 / 50 | 0.98 |
| medication | date_iso | 50 / 50 | 1.0 |
| event | date_iso | 44 / 44 | 1.0 |
| investigation | value | 50 / 50 | 1.0 |
| investigation | unit | 50 / 50 | 1.0 |
| investigation | reference_range | 50 / 50 | 1.0 |
| investigation | date_iso | 50 / 50 | 1.0 |

## Evidence

- Page reference accuracy: **1.0**
- Evidence passage accuracy: **0.9382**
- Source document accuracy: 1.0 (matching is per document)
- Evidence completeness (every predicted finding has a verbatim span present in its cited page): **1.0**
- Document classification accuracy: 1.0
- Document date accuracy: 1.0

## Timeline

- Event date accuracy: **1.0** (125 dated items)
- Pairwise chronological ordering accuracy: **1.0** (1068 pairs)
- Medication chronology accuracy: 1.0 (41 pairs)
- Historical / current status accuracy: 0.9286 (14 items)
- Missing/ambiguous date handling (no fabricated dates): **1.0** (40 items)

## Duplicate detection (document level)

- Precision 1.0, recall 1.0, F1 1.0
- False-positive rate: 0.0 over 87 non-duplicate pairs
- Kind accuracy on labelled pairs (exact / near / similar-distinct): 1.0

## Contradiction detection

- Precision 1.0, recall 0.875, F1 0.9333
- Development recall: 5/5; hold-out recall: 2/3
- Negative controls wrongly flagged: 0
- Missed: [('event_date', ['F4', 'F5'])]
- False positives: []
- Conflicts auto-resolved: 0 (by design)

## Records-only question answering

- Questions: 38
- Overall accuracy: **0.9474** (dev 1.0, hold-out 0.6)
- Evidence-supported answer accuracy: 0.9583
- Citation accuracy: 0.9231
- Abstention accuracy (abstain/decline when expected): **1.0**
- Unsupported-answer rate: **0.0**
- Over-abstention rate: 0.0
- Missing-evidence detection: 1.0
- Cross-patient citation rate: 0.0

| Pt | Question | Expected | Got | Status | Correct |
|---|---|---|---|---|---|
| A | Which medications are documented in the uploaded records? | answer | answer | answered | yes |
| A | Were any medication changes documented? | answer | answer | answered | yes |
| A | When was the last laboratory test documented? | answer | answer | answered | yes |
| A | What medications were documented in the discharge summary? | answer | answer | answered | yes |
| A | What was the HbA1c? | answer | answer | answered | yes |
| A | When was the patient admitted? | answer | answer | answered | yes |
| A | Should the patient increase the metformin dose? | decline | decline | declined_clinical_advice | yes |
| A | Is the HbA1c of 8.4 normal? | decline | decline | declined_clinical_judgement | yes |
| A | What is the patient's blood group? | abstain | abstain | abstained_no_evidence | yes |
| A | Why was glimepiride stopped? | answer | answer | answered | yes |
| B | Which allergy statements appear in the records? | answer | answer | answered_with_conflicts | yes |
| B | Is the patient allergic to penicillin? | abstain | abstain | abstained_conflict | yes |
| B | Are there conflicting statements about allergies? | answer | answer | answered_with_conflicts | yes |
| B | Was montelukast stopped? | answer | answer | answered | yes |
| B | What investigations are recorded? | answer | answer | answered | yes |
| B | What treatment should she get for asthma? | decline | decline | declined_clinical_advice | yes |
| C | What creatinine values are documented? | answer | answer | answered | yes |
| C | Which documents mention chronic kidney disease? | answer | answer | answered | yes |
| C | What glucose results are recorded? | answer | answer | answered | yes |
| C | Does the patient have diabetes? | decline | decline | declined_clinical_judgement | yes |
| C | Will the kidney disease get worse? | decline | decline | declined_unsupported_inference | yes |
| D | What LDL cholesterol values are documented? | answer | answer | answered_with_conflicts | yes |
| D | What was the LDL cholesterol on 3 October 2023? | abstain | abstain | abstained_conflict | yes |
| D | Which allergy statements appear in the records? | answer | answer | answered | yes |
| D | Were any medication changes documented? | answer | answer | answered | yes |
| E | What dose of levothyroxine is documented? | answer | answer | answered | yes |
| E | Which allergy statements appear in the records? | answer | answer | answered | yes |
| E | When was the patient discharged? | abstain | abstain | abstained_not_established | yes |
| E | When was the thyroid test done? | abstain | abstain | abstained_ambiguous_date | yes |
| E | What information is missing from the records? | answer | answer | answered | yes |
| E | What medications is the patient currently taking? | answer | answer | answered | yes |
| E | What is the patient's weight? | abstain | abstain | abstained_no_evidence | yes |
| E | Can she stop levothyroxine? | decline | decline | declined_clinical_advice | yes |
| F | Which allergy statements appear in the records? | answer | answer | answered_with_conflicts | yes |
| F | When was the appendicectomy performed? | abstain | abstain | abstained_no_evidence | NO |
| F | Were any medication changes documented? | answer | answer | answered | NO |
| F | What haemoglobin values are documented? | answer | answer | answered | yes |
| F | Is the vitamin B12 low? | decline | decline | declined_clinical_judgement | yes |

## OCR

Engine: RapidOCR (PP-OCR models, ONNX Runtime, local). Mean character error rate: **0.0363**; mean engine confidence 0.991.

| Doc | Format | Engine confidence | CER |
|---|---|---|---|
| A4 | scan_pdf | 0.9862 | 0.0964 |
| A6 | png | 0.996 | 0.0 |
| B5 | jpg | 0.9924 | 0.0664 |
| D6 | scan_pdf | 0.9893 | 0.0144 |
| E4 | scan_pdf | 0.9886 | 0.0769 |
| E6 | png | 0.9913 | 0.0 |
| F3 | png | 0.9931 | 0.0 |

## Processing latency (measured on this machine)

- Native-text documents: median 132.4 ms (29 docs)
- OCR documents: median 5766.8 ms (7 docs)

## Review time

**This is an automated reading-load estimate, not a human study.**

Assumptions: {'reading_wpm': 200, 'seconds_per_document_open': 10, 'seconds_per_fact_check': 6, 'fact_spot_check_share': 0.25}

| Patient | Docs | Raw words | Structured words | Baseline (s, est.) | MedTrace (s, est.) |
|---|---|---|---|---|---|
| A | 6 | 439 | 316 | 191.7 | 130.8 |
| B | 6 | 300 | 244 | 150.0 | 101.7 |
| C | 6 | 283 | 240 | 144.9 | 100.5 |
| D | 7 | 338 | 273 | 171.4 | 117.9 |
| E | 6 | 237 | 144 | 131.1 | 62.7 |
| F | 5 | 259 | 184 | 127.7 | 76.2 |

Estimated reduction: 0.3567. Human sessions recorded: 0.

## Limitations

- The dataset is small and synthetic; documents follow a limited set of layouts and phrasings.
- Rules were developed while looking at patients A-E (development split). Development metrics are therefore optimistic; the hold-out patient F is the fairer estimate of generalisation, and it is very small.
- Ground truth was written by the system author, not by independent clinical annotators.
- The review-time figures are model-based estimates; no human reviewer study has been run.

## Error listing (first 80)

| Doc | Type | Item | Field | Expected | Got |
|---|---|---|---|---|---|
| F1 | medication | omeprazole | status | documented_ongoing | prescribed |
| F1 | medication | propranolol | MISSED | Propranolol |  |
| F3 | medication | propranolol | MISSED | Propranolol |  |
| F4 | medication | propranolol | MISSED | Propranolol was withheld |  |
| F5 | event | surgery | MISSED | appendicectomy on 29 June 2024 |  |
| F5 | medication | propranolol | MISSED | Propranolol restarted |  |
| F5 | event | follow_up | SPURIOUS |  | Post-operative review after appendicectomy on 29 June 2024.  |
