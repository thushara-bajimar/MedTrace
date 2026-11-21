# MedTrace — Project Report

**One Patient, Many Records — Every Medical Fact, Traced to Its Source**

Domain: Data Engineering & Distributed Systems (with applied AI) · November 2026

---

## Abstract
MedTrace reconstructs a chronological, evidence-linked medical history from heterogeneous medical documents — native and scanned PDFs and images of prescriptions, laboratory reports, discharge summaries, consultation notes and imaging reports. A local pipeline validates uploads, extracts text (with OCR only when needed), classifies documents and extracts conditions, medications, allergies, investigations and events with deterministic rules. Every fact is stored with its document, page, line, bounding box and verbatim passage. The system detects duplicates, contradictions and documentation gaps without resolving them automatically, preserves original units and dates, supports versioned human corrections, and answers factual questions only from the selected patient's records, with citations and explicit abstention. Evaluated on a 36-document synthetic dataset with hand-written ground truth, MedTrace reached an extraction F1 of 0.983 (0.900 on a hold-out patient), 100 % page-reference accuracy, perfect duplicate detection, contradiction recall of 0.875 with no false positives, and a 0 % unsupported-answer rate. No human review-time study was performed; an automated reading-load estimate is reported and labelled as such.

## 1. Introduction
A patient's history is usually a folder of documents from different providers. Reading it is slow; summarising it with general-purpose AI is risky because summaries lose dates and dosages, merge time periods, hide contradictions and may invent facts. MedTrace addresses this as a data-integration problem in which **provenance is the primary requirement**.

## 2. Problem statement
Medical documents repeat and contradict each other, use different units and date formats, record medication changes, mix historical and current information, omit facts and contain OCR errors. The project builds a system that makes such records understandable — organised, chronological, verifiable — while never diagnosing, interpreting results or recommending treatment.

## 3. Objectives
- Ingest PDF, scanned PDF, PNG and JPG/JPEG documents of at least five types.
- Extract conditions, medications (with changes and stops), allergies, investigations and events with source evidence.
- Reconstruct a chronological history using documented dates; never guess ambiguous dates.
- Detect duplicates, contradictions and missing information; surface rather than resolve them.
- Preserve original units, values, dates and dosages.
- Allow human corrections with full version history.
- Answer records-only questions with citations; abstain when evidence is insufficient.
- Isolate patients and control access.
- Measure accuracy and (honestly) reviewer efficiency.

## 4. Proposed methodology
1. **Ingestion and validation** — allow-listed formats, magic bytes, size/page limits, active-content rejection, UUID storage, SHA-256.
2. **Text acquisition** — PyMuPDF text layer with line bounding boxes; RapidOCR (local ONNX models) for pages without a text layer and for images.
3. **Classification** — weighted cue phrases with OCR-robust matching.
4. **Structured extraction** — section-aware rules and lexicons; qualifiers and statuses preserved; absent attributes recorded as not documented.
5. **Evidence verification** — a finding is kept only if its verbatim span is present in the cited line.
6. **Analysis** — duplicates (hash + OCR-tolerant similarity + dates), contradictions (five categories), documentation gaps.
7. **Reconstruction** — timeline and medication history derived on read from current finding versions.
8. **Review** — verify / correct / reject with append-only versions.
9. **Records-only QA** — boundary check, structured + BM25 retrieval, templated cited answers, abstention.
10. **Evaluation** — ground truth, development vs hold-out split, pre-tuning baseline kept.

## 5. Architecture
![Architecture](diagrams/architecture.svg)

React SPA → FastAPI (security middleware, patient-scoped routes) → ingestion pipeline, analysis, views, review, QA, evaluation → SQLite + file store; local OCR model; no external services.

## 6. Data model
![Data model](diagrams/data_model.svg)

Findings are evidence records (document, page, line range, verbatim passage and span, date as written and interpreted, confidence with reasons, verification and provenance) with typed details for the current version and an append-only version table. Conflicts, duplicate candidates and gaps reference findings and documents; every row is patient-scoped.

## 7. Document processing
![Pipeline](diagrams/pipeline.svg)

![Documents](screenshots/04_documents.png)

The document library shows type (with classifier confidence or reviewer override), extraction and OCR status with OCR confidence, text source, document vs upload date, provider, page count, hash, findings by type, conflicts, duplicate flags and instruction-like-text warnings.

![Document viewer with OCR](screenshots/13_document_viewer_ocr.png)

## 8. Extraction
Rules extract: conditions with *suspected / possible / ruled out / history of / known case / explicitly denied* status; medications with strength, dosage, route, frequency, duration, start/stop and eight documented statuses; allergy statements with four assertion types; investigations with verbatim value, unit, reference range and printed flag; and documented events. Confidence is a stated heuristic (text source, lexicon match, missing fields, date ambiguity).

![Investigations](screenshots/08_investigations_units.png)

## 9. Timeline
Documented event dates order the history; the document date is a labelled fallback; upload dates are never used; ambiguous and undated entries are listed separately.

![Timeline](screenshots/05_timeline.png)

![Medication history](screenshots/06_medication_history.png)

## 10. Provenance and evidence
Every entry opens the evidence viewer: the original page image with the source line highlighted, verbatim context, extracted span and fields, confidence reasons, conflicts, gaps and version history, with verify / correct / reject actions.

![Evidence viewer](screenshots/12_evidence_viewer.png)

![Review centre](screenshots/11_review_centre.png)

## 11. Contradictions, duplicates and gaps
![Allergy statements](screenshots/07_allergies_conflict.png)

![Contradiction centre](screenshots/09_contradiction_centre.png)

![Duplicates](screenshots/10_duplicates.png)

![Overview and gaps](screenshots/19_overview_gaps.png)

## 12. Question interface
Answers are assembled from stored findings and verbatim lines — never generated — with citations to document and page. The engine abstains on missing, conflicting or ambiguously dated evidence and declines diagnosis and treatment questions.

![Cited answer](screenshots/14_qa_answer.png)

![Abstention on conflict](screenshots/15_qa_conflict_abstain.png)

![Declined treatment question](screenshots/16_qa_declined.png)

## 13. Security
scrypt passwords; HttpOnly SameSite=Strict session cookie with hashed server-side tokens; lockout; CSRF header; CORS allow-list; CSP and security headers; backend patient scoping returning 404 for others' records; upload hardening; identifier-only audit log; local processing; prompt-injection-inert QA (no instruction-following component; instruction-like document lines flagged and excluded). No regulatory compliance is claimed.

## 14. Implementation
Python/FastAPI/SQLite backend (~5,600 lines incl. schema), React/TypeScript/Tailwind/Recharts frontend (~1,900 lines), PyMuPDF, RapidOCR/ONNX Runtime, synthetic dataset generator, evaluation runner, 77 automated tests, Playwright screenshot tooling. Runs locally with no paid API keys.

## 15. Evaluation
**Dataset:** 6 synthetic patients (A–E development, F hold-out), 36 documents (12 lab reports, 10 consultation notes, 7 prescriptions, 4 discharge summaries, 3 imaging reports; 29 native PDF, 3 scanned PDF, 3 PNG, 1 JPG), 183 annotated findings, 9 conflict labels, 7 duplicate labels, 38 questions.

![Evaluation](screenshots/17_evaluation.png)

## 16. Results (measured)
| Metric | All | Development | Hold-out |
|---|---|---|---|
| Extraction precision | 0.994 | 1.000 | 0.964 |
| Extraction recall | 0.973 | 1.000 | 0.844 |
| Extraction F1 | 0.983 | 1.000 | 0.900 |
| QA overall accuracy | 0.947 | 1.000 | 0.600 |

| Metric | Value |
|---|---|
| Page reference accuracy / evidence passage accuracy / completeness | 1.000 / 0.938 / 1.000 |
| Timeline event-date / ordering accuracy | 1.000 / 1.000 |
| Undated/ambiguous items without fabricated dates | 40 / 40 |
| Duplicate precision / recall / false-positive rate | 1.000 / 1.000 / 0.000 |
| Contradiction precision / recall | 1.000 / 0.875 |
| QA abstention accuracy / unsupported-answer rate / cross-patient citations | 1.000 / 0.000 / 0 |
| OCR mean character error rate | 0.036 |
| Median processing time (native / OCR) | 138 ms / 5.8 s |
| Review time | automated reading-load estimate −36 %; **no human study performed** |

Before rule refinement the same evaluation gave extraction F1 0.964 (hold-out 0.871), QA accuracy 0.842 and an unsupported-answer rate of 0.357. Remaining hold-out errors are omissions caused by unseen vocabulary and phrasing; no fabricated facts or unsupported answers were observed.

## 17. Conclusion
MedTrace demonstrates a provenance-first approach to fragmented medical records: traceable facts, visible uncertainty, surfaced contradictions, non-destructive corrections and honest abstention. Its rules-based extractor is accurate where its rules apply and fails by omission elsewhere, which keeps the system safe but limits coverage.

## 18. Future scope
Learned or local-LLM extraction behind the same evidence-verification gate; terminology mapping (RxNorm, LOINC, SNOMED CT where licensing permits); FHIR export; multilingual and handwriting OCR; queue-based workers and PostgreSQL for multi-user deployment; encryption at rest and TLS; broader contradiction rules; a real reviewer study with the built-in timing tool; independent annotation of a larger corpus.
