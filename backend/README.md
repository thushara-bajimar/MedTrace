# backend/

FastAPI + SQLite service that ingests documents, extracts evidence-linked findings, reconstructs the timeline, detects duplicates/contradictions/gaps, answers records-only questions and runs the evaluation.

| Path | Contents |
|---|---|
| `medtrace/main.py` | app factory, security middleware, routers, SPA serving |
| `medtrace/ingest/` | upload validation, PDF text + OCR, classification |
| `medtrace/extract/` | dates, lexicons/units, rules-based extractor |
| `medtrace/analysis/` | duplicates, conflicts, gaps |
| `medtrace/views.py`, `corrections.py`, `pipeline.py`, `store.py` | timeline/medication/allergy views, review workflow, pipeline, persistence |
| `medtrace/qa/` | records-only question answering |
| `medtrace/api/` | REST routes (auth, patients, documents, analysis, evaluation) |
| `medtrace/evaluation/` | evaluation runner |
| `medtrace/seed.py` | loads the synthetic dataset |
| `tests/` | 77 automated tests |

Run: `python -m uvicorn medtrace.main:app --port 8000` · Seed: `python -m medtrace.seed --reset` · Test: `python -m pytest -q` · Evaluate: `python -m medtrace.evaluation.runner`.
