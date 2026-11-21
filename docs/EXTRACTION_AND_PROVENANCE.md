# Extraction and Provenance

## Pipeline
1. **Text acquisition** — native PDF text via PyMuPDF; pages with < 25 characters of text are rendered at 200 dpi and OCR'd with RapidOCR (PP-OCR detection/recognition models run by ONNX Runtime, locally). Images are always OCR'd. Fragments on the same visual row are merged into a line; wide horizontal gaps are kept as two spaces so table columns stay separable. Each line stores its bounding box, OCR confidence and source.
2. **Classification** — weighted cue phrases per document type; title-position cues count double; OCR-merged words ("CONSULTATIONNOTE") are matched on a space-free copy. Confidence = margin between the best and the second-best score.
3. **Document metadata** — document date from type-specific labels (e.g. *Date of discharge*, *Sample collected on*, *Date:*); provider from header lines; declared date convention (literal `DD/MM/YYYY` or `MM/DD/YYYY` in the document).
4. **Sectioning** — headings such as *Diagnosis*, *Past history*, *Allergies*, *Medications on discharge*, *Medications stopped*, *Hospital course*, *Investigations*, *Plan*, *Impression*. Any other `Label:` line ends the current section (unless the label is a test or drug name).
5. **Rules per finding type** (`extract/extractor.py`):
   - **Conditions**: in diagnosis / history sections, or after triggers (*known case of*, *k/c/o*, *diagnosed with*, *history of*). Qualifiers map to a documented status — `suspected` (?, query, rule out), `possible`, `ruled_out`, `history_of`, `known_case`, `explicitly_denied`, otherwise `confirmed_as_documented`. The name is stored as written; a small synonym table supplies an optional normalised name.
   - **Medications**: lexicon of ~50 generics and example brands, plus a `Tab./Cap./Inj./Syp.` + capitalised-word pattern for unknown names (lower confidence). Strength, dosage, route, frequency, duration, start/stop dates are taken only from the text after the name; a missing attribute stays `null` (*not documented*) — route is never inferred from "Tab.". Status priority: uncertain → past-history/hospital-course (historical) → stopped → changed (incl. "from X to Y") → historical wording → continue/ongoing → prescribing section → mentioned only. A prescription is **never** marked as currently taken: its temporal status is `unknown`.
   - **Allergies**: explicit "not recorded" statements, specific negatives (*denies allergy to X*), general negatives (*NKDA*, *no known drug allergies*), and positives with substance, reaction and severity.
   - **Investigations**: in lab reports or investigation sections: test (lexicon) → first value → unit (verbatim, from a unit list) → reference range (verbatim) → printed flag. Imaging reports produce one result from the *Impression* line. The test date is the specimen date, else the report date (marked as such).
   - **Events**: admission/discharge dates, surgeries and procedures (*Procedure:*, *underwent*, past-history procedures), follow-up plans (relative intervals kept as text), and one document-level consultation or investigation event.
6. **Instruction-like text** (e.g. "ignore all previous instructions…") is recorded in `documents.injection_flags` and those lines are excluded from extraction.
7. **Evidence verification** — a finding is stored only if its verbatim span occurs in the cited line.

## Evidence linking
Every finding records document, page, line range, the full verbatim line (`source_passage`), the exact span (`original_text`), and the line's bounding box via `page_lines`. The evidence viewer renders the page and draws the box; the document viewer lists every finding on a page and highlights its line.

Normalised values (`normalized_name`, `normalized_test`, converted lab values) are stored in separate fields and labelled *normalised* / *display-only* in the UI and in QA answers — they are never presented as verbatim text.

## Provenance types
| Type | Meaning |
|---|---|
| `direct_extraction` | rules applied to the native PDF text layer |
| `ocr_extraction` | rules applied to OCR text |
| `human_correction` | a reviewer changed one or more fields (new version) |
| normalisation | separate `normalized_*` / `converted_*` fields with the rule text |
| derived metadata | timeline position, gaps, duplicates, conflicts — computed, never stored as evidence |

## Confidence
A transparent heuristic, stored with its reasons:
- base 0.92 for native text; for OCR, `min(0.9, line OCR confidence) − 0.05`;
- −0.12 medication name not in lexicon; −0.10 OCR fuzzy lexicon match; −0.10 substance not in lexicon;
- −0.05 strength missing; −0.03 reference range missing; −0.08 uncertain status or condition not in synonyms;
- −0.10 ambiguous date; −0.15 event date missing or ambiguous.

Labels: **high** ≥ 0.80, **medium** ≥ 0.60, **low** < 0.60. Confidence is a triage signal for the review queue, **not** a probability of correctness and not a guarantee.

## Human verification and correction history
- `verify` → `human_verified` (a version is appended recording who verified it).
- `correct` → requires a reason; only type-specific fields plus `date_text` / `date_iso` are editable; enum fields are validated; a new version (origin `human`) is appended, the detail row is updated, `provenance_type` becomes `human_correction`. `source_passage` and `original_text` cannot be edited.
- `reject` → requires a reason; the finding is hidden from views but kept.
- Page text can be corrected (original OCR text kept in `original_text`, change logged in `page_text_corrections`); re-processing then extracts from the corrected text.
- Document type can be corrected (classifier output kept in `doc_type_original`).
After every review, duplicate, conflict and gap detection re-run so the timeline and contradiction centre reflect the change.

## Limitations
Rules recognise only encoded phrasing; lexicons are small; English only; no handwriting; multi-line items are linked to a single line; tables with unusual layouts may misalign value and unit. Optional LLM-assisted extraction was not implemented (no paid API is required, and no local model was available); it is listed as future work, with the requirement that any model output must pass the same evidence-verification step.
