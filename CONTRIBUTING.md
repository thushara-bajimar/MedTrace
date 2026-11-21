# Contributing to MedTrace

## Setup
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
cd frontend && npm install && cd ..
cp .env.example .env   # set MEDTRACE_ADMIN_PASSWORD
cd backend && python -m medtrace.seed --reset
```

## Development
- Backend: `cd backend && python -m uvicorn medtrace.main:app --reload --port 8000`
- Frontend: `cd frontend && npm run dev` (http://localhost:5173, proxies `/api` to :8000)
- Production-style single origin: `npm run build`, then the backend serves `frontend/dist`.

## Code conventions
- Python: type hints, small modules by responsibility, no ORM (explicit SQL in `db.py`-style helpers), patient scoping via `require_patient()` in **every** patient route, and `(id, patient_id)` in every object lookup.
- Never overwrite evidence: new information is a new row or a new version. Do not add code paths that resolve conflicts or merge duplicates automatically.
- Never infer: absent attributes stay `null`; ambiguous dates stay un-interpreted; normalised values go in separate, labelled fields.
- No document text, names or questions in logs; the audit log takes identifiers only.
- Frontend: TypeScript strict mode, functional components, Tailwind utility classes and the shared components in `src/components/ui.tsx`. Show "not documented" rather than blanks.
- Do not add external network calls or paid APIs to the processing path.

## Testing
- `cd backend && python -m pytest -q` must pass before every commit.
- Add tests for every new extraction rule (positive and negative case) and every new endpoint (including a cross-patient 404 test).
- After changing extraction rules run `python -m medtrace.evaluation.runner` and commit the updated `docs/evaluation/` report. **Do not tune rules on the hold-out patient F**; if you add new rules because of F, say so and create a new hold-out set.
- `cd frontend && npm run build` must type-check cleanly.

## Data
Only synthetic data. Never commit real medical documents, credentials, `.env` files, databases or uploads (see `.gitignore`).

## Contribution workflow
1. Branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Small, focused commits with conventional messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
3. Run tests, build, and the evaluation if extraction changed; review the staged diff for secrets.
4. Open a pull request describing behaviour changes, evaluation deltas and any limitations.
