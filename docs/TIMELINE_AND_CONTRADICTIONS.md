# Timeline, Medication History, Duplicates and Contradictions

## Chronological reconstruction
The timeline (`views.timeline`) is computed on every request from the current version of every active, non-rejected finding.

| Date kind | Rule |
|---|---|
| Event date | the finding's own documented date (admission date, specimen date, stop date, "in 2019") |
| Document date | used only when the finding has no own date; labelled *(record date)* |
| Upload date | **never** used as an event date (shown only as metadata) |
| Partial date | kept with its precision (`2019`, `2023-08`); sorted at the start of its period and labelled *partial* |
| Ambiguous / missing | listed in a separate *Undated or ambiguous* section; position not inferred |

Filters: finding/event type, date range, document, verification status and free text.

## Temporal information and medication history
Each medication mention carries a documented status and a temporal status:

| Documented status | Temporal status |
|---|---|
| documented_ongoing | current_as_documented (as of that record's date) |
| documented_stopped | discontinued |
| documented_changed | updated |
| historical | historical |
| uncertain | uncertain |
| prescribed / mentioned_only | **unknown** — present-day use is not established |

The medication history groups mentions by normalised name in date order and lists **documented changes** (explicit change/stop statements) and **between-record differences** (strength differs from the previous dated record, without an explicit change statement — reported as a difference, not as a change). Every medication card states "Current use is NOT established by the records" unless the latest record explicitly says ongoing. Stop dates and doses are never inferred.

## Duplicate detection
Document level (`analysis/duplicates.py`):
- **exact_duplicate** — identical SHA-256;
- **near_duplicate** — similarity ≥ 0.90 (max of word-3-shingle Jaccard and whitespace-free character similarity, which tolerates OCR noise) **and** no conflicting document dates — e.g. an amended re-issue or a scanned copy;
- **similar_distinct** — same document type and similarity ≥ 0.60 (e.g. the same lab's report on another date).

Finding level: identical structured keys (e.g. same medication, strength, frequency, status and date) in different documents → `duplicate_finding`; same condition/allergy statement on different dates → `related_finding`.
Candidates show the lines unique to each document. Reviewers confirm or reject; nothing is merged or deleted, and un-reviewed candidates that stop being produced are removed while reviewed decisions remain.

## Contradiction detection
Rules (`analysis/conflicts.py`), always across different documents:
| Category | Rule |
|---|---|
| medication_dosage | same medication, same documented day, both active statuses, different strength |
| medication_status | same medication, same day, one stopped and one prescribed/ongoing/changed |
| allergy | documented allergy to S vs an explicit general negative, or vs an explicit negative for S |
| event_date | same surgery/procedure (normalised description) with different dates; admission/discharge dates ≤ 7 days apart that disagree |
| investigation_value | same test, same day, same unit, different value |

Different-day dose differences are **changes, not contradictions**. Different units on the same day are not compared (a *unit difference* gap is raised instead) — no clinical equivalence is inferred.

Each conflict stores the evidence of every side (document, page, passage, date, value). Statuses: `unresolved`, `reviewed`, `resolved_by_documented_evidence`, `not_a_contradiction`, `insufficient_information`. Resolving requires a written explanation; every transition is kept in `conflict_resolutions`. No code path resolves a conflict automatically. Re-detection is idempotent (deterministic key); a conflict that is no longer detected after a correction is kept with `still_detected = 0`.

## Missing information (gaps)
`analysis/gaps.py` produces statements about documentation only: document date missing or ambiguous; medication dose / frequency / date not documented; medication status uncertain; allergy reaction not documented; allergy status explicitly not recorded; no allergy statement in a document type that usually has one ("this is NOT evidence of no allergies"); reference range missing; event date missing; same test in different units; low OCR confidence; instruction-like text found. A gap is never converted into a negative fact.

## Unit preservation
Values, units and reference ranges are stored verbatim. Conversions exist only for explicit, documented rules (glucose mg/dL↔mmol/L ÷18.016, creatinine mg/dL↔µmol/L ×88.42, haemoglobin g/dL↔g/L ×10, cholesterol ÷38.67, triglycerides ÷88.57, HbA1c NGSP %↔IFCC mmol/mol), are stored in separate `converted_*` fields with the rule text, shown as *display only*, and are never used to overwrite or compare evidence. Results are never interpreted clinically.

## Date ambiguity
`extract/dates.py`: ISO and textual-month dates parse directly; `a/b/yyyy` is DD/MM if `a > 12`, MM/DD if `b > 12`; if both ≤ 12 and different, the date is **ambiguous** (both candidates stored, no ISO value) unless the document literally declares its convention. Two-digit years are never expanded. Reviewers may set the interpretation through a correction with a reason; the original text and machine version stay visible.
