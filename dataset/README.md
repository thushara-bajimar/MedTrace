# dataset/ — SYNTHETIC

All patients, institutions and records here are **fictional**, generated for software evaluation.

- `generate_dataset.py` — document text, hand-written ground truth, rendering (native PDF, scanned PDF, PNG, JPG).
- `documents/patient_A … patient_F/` — 36 generated documents.
- `ground_truth.json` — per-document findings, duplicate pairs, conflicts (incl. a negative control) and 38 questions with expected behaviour.

Patients: A medication changes · B allergy conflict · C unit differences · D duplicates · E missing information + an embedded prompt-injection line · F hold-out (never used to tune rules).

Regenerate: `python dataset/generate_dataset.py` (deterministic).
