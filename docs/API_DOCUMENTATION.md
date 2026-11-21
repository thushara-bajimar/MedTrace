# MedTrace API Documentation

> Example payloads below are taken from the seeded synthetic database (scanned prescription A4 for the run timings).

Base URL: `http://127.0.0.1:8000`. Interactive OpenAPI docs: `/docs` (Swagger UI) and `/openapi.json`. All request and response bodies are JSON unless noted.

## Authentication
1. `POST /api/auth/login` with `{"username": "...", "password": "..."}` and header `X-MedTrace-CSRF: 1`. The response sets the HttpOnly session cookie `medtrace_session`.
2. Send the cookie on every request (browsers do this automatically; with curl use a cookie jar).
3. Every `POST/PUT/PATCH/DELETE` under `/api/` **must** include `X-MedTrace-CSRF: 1`, otherwise `403 Missing CSRF header`.

```bash
curl -c jar -H "X-MedTrace-CSRF: 1" -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"<from .env>"}' http://127.0.0.1:8000/api/auth/login
curl -b jar http://127.0.0.1:8000/api/patients
```

## Errors
| Status | Meaning |
|---|---|
| 400 | validation failure (bad upload, missing reason, invalid field/enum) — `{"detail": "message"}` |
| 401 | not signed in / session expired |
| 403 | missing CSRF header, role lacks permission (viewer writing, non-admin on admin routes) |
| 404 | resource not found **or not visible to you** (other patients' records are never disclosed) |
| 409 | conflict (duplicate username, finished session) |
| 413 | upload larger than the configured limit |
| 422 | request body/query does not match the schema (FastAPI validation) |
| 429 | account temporarily locked |

## Endpoints (generated from the OpenAPI schema)
`{pid}` = patient ID, `{did}` = document ID, `{fid}` = finding ID, `{cid}` = conflict ID.

| Method | Path | Group | Summary |
|---|---|---|---|
| POST | `/api/auth/login` | auth | Do Login |
| POST | `/api/auth/logout` | auth | Do Logout |
| GET | `/api/auth/me` | auth | Me |
| GET | `/api/users` | auth | List Users |
| POST | `/api/users` | auth | Add User |
| POST | `/api/users/{user_id}/access` | auth | Grant Access |
| DELETE | `/api/users/{user_id}/access/{patient_id}` | auth | Revoke Access |
| GET | `/api/dashboard` | auth | Dashboard |
| GET | `/api/patients` | patients | List Patients |
| POST | `/api/patients` | patients | Create Patient |
| GET | `/api/patients/{pid}` | patients | Get Patient |
| PATCH | `/api/patients/{pid}` | patients | Update Patient |
| DELETE | `/api/patients/{pid}` | patients | Delete Patient |
| GET | `/api/patients/{pid}/findings` | patients | List Findings · query: type, document_id, verification, confidence, date_from, date_to, include_rejected |
| GET | `/api/patients/{pid}/findings/{fid}` | patients | Finding Detail |
| GET | `/api/patients/{pid}/findings/{fid}/evidence` | patients | Finding Evidence |
| GET | `/api/patients/{pid}/findings/{fid}/history` | patients | Finding Versions |
| GET | `/api/patients/{pid}/timeline` | patients | Get Timeline · query: types, date_from, date_to, document_id, verification, q |
| GET | `/api/patients/{pid}/timeline/{fid}` | patients | Get Timeline Event |
| POST | `/api/patients/{pid}/timeline/rebuild` | patients | Rebuild Timeline |
| GET | `/api/patients/{pid}/medications` | patients | Get Medications |
| GET | `/api/patients/{pid}/medications/mentions` | patients | Get Med Mentions |
| GET | `/api/patients/{pid}/medications/changes` | patients | Get Med Changes |
| GET | `/api/patients/{pid}/allergies` | patients | Get Allergies |
| GET | `/api/patients/{pid}/allergies/statements` | patients | Get Allergy Statements |
| GET | `/api/patients/{pid}/allergies/conflicts` | patients | Get Allergy Conflicts |
| GET | `/api/patients/{pid}/investigations` | patients | Get Investigations |
| GET | `/api/patients/{pid}/conditions` | patients | Get Conditions |
| GET | `/api/patients/{pid}/events` | patients | Get Events |
| POST | `/api/patients/{pid}/documents` | documents | Upload |
| GET | `/api/patients/{pid}/documents` | documents | List Documents · query: q, doc_type, status |
| GET | `/api/patients/{pid}/documents/{did}` | documents | Get Document |
| PATCH | `/api/patients/{pid}/documents/{did}` | documents | Patch Document |
| DELETE | `/api/patients/{pid}/documents/{did}` | documents | Delete Document |
| GET | `/api/patients/{pid}/documents/{did}/text` | documents | Get Text |
| GET | `/api/patients/{pid}/documents/{did}/status` | documents | Get Status |
| GET | `/api/patients/{pid}/documents/{did}/pages/{page}/image` | documents | Page Image |
| GET | `/api/patients/{pid}/documents/{did}/file` | documents | Original File |
| POST | `/api/patients/{pid}/documents/{did}/reprocess` | documents | Reprocess |
| PUT | `/api/patients/{pid}/documents/{did}/pages/{page}/text` | documents | Put Page Text |
| GET | `/api/patients/{pid}/conflicts` | analysis | List Conflicts · query: status, include_stale |
| POST | `/api/patients/{pid}/conflicts/detect` | analysis | Detect Conflicts |
| GET | `/api/patients/{pid}/conflicts/{cid}` | analysis | Get Conflict |
| POST | `/api/patients/{pid}/conflicts/{cid}/review` | analysis | Review Conflict |
| GET | `/api/patients/{pid}/duplicates` | analysis | List Duplicates · query: level |
| POST | `/api/patients/{pid}/duplicates/{dup_id}/review` | analysis | Review Duplicate |
| GET | `/api/patients/{pid}/gaps` | analysis | List Gaps |
| GET | `/api/patients/{pid}/review` | analysis | Review Queue |
| POST | `/api/patients/{pid}/findings/{fid}/review` | analysis | Post Review |
| POST | `/api/patients/{pid}/ask` | analysis | Ask |
| GET | `/api/patients/{pid}/ask/history` | analysis | Ask History |
| GET | `/api/patients/{pid}/ask/{qid}` | analysis | Ask Get |
| GET | `/api/patients/{pid}/ask/{qid}/evidence` | analysis | Ask Evidence |
| GET | `/api/patients/{pid}/ask/{qid}/uncertainty` | analysis | Ask Uncertainty |
| POST | `/api/evaluation/run` | evaluation | Run Eval |
| GET | `/api/evaluation/latest` | evaluation | Latest |
| GET | `/api/evaluation/runs` | evaluation | Runs |
| GET | `/api/evaluation/extraction` | evaluation | Extraction |
| GET | `/api/evaluation/precision-recall` | evaluation | Precision Recall |
| GET | `/api/evaluation/f1` | evaluation | F1 |
| GET | `/api/evaluation/review-time` | evaluation | Review Time |
| GET | `/api/evaluation/comparison` | evaluation | Comparison |
| GET | `/api/review-sessions/tasks` | evaluation | Tasks |
| GET | `/api/review-sessions` | evaluation | List Sessions |
| POST | `/api/review-sessions` | evaluation | Start Session |
| POST | `/api/review-sessions/{sid}/finish` | evaluation | Finish Session |
| GET | `/api/health` |  | Health |

## Key request / response formats

### Upload a document
`POST /api/patients/{pid}/documents` — `multipart/form-data` with field `file` (PDF/PNG/JPG/JPEG). Returns `202`:
```json
{"id": "doc_3f…", "status": "pending", "exact_duplicate_of": null, "note": "Processing started."}
```
Poll `GET /api/patients/{pid}/documents/{did}/status` → `{"extraction_status": "completed", "ocr_status": "completed", "runs": [{"duration_ms": 9201.9, "stages_json": [{"stage": "text_extraction_ocr", "ms": 8858.8}, {"stage": "classification", "ms": 1.1}, …]}]}`.

### Finding (list item)
```json
{"id": "fnd_…", "finding_type": "medication", "document_id": "doc_…", "document_filename": "A5_discharge_summary_2024-02-07.pdf",
 "page_number": 2, "line_start": 4, "line_end": 4,
 "source_passage": "3. Tab. Amoxicillin-clavulanate 625 mg three times a day x 5 days",
 "original_text": "Tab. Amoxicillin-clavulanate 625 mg three times a day x 5 days",
 "date_text": "07/02/2024", "date_iso": "2024-02-07", "date_status": "document_date", "date_role": "documented_in_record_dated",
 "confidence_score": 0.92, "confidence_label": "high", "confidence_reasons": ["native PDF text layer", "listed in medications section"],
 "extraction_method": "rules_native_text", "provenance_type": "direct_extraction", "verification_status": "unverified",
 "temporal_status": "unknown",
 "details": {"name_as_written": "Amoxicillin-clavulanate", "normalized_name": "amoxicillin-clavulanate", "strength": "625 mg",
             "dosage": null, "route": null, "frequency": "three times a day", "duration": "5 days", "status": "prescribed"},
 "summary": "Amoxicillin-clavulanate 625 mg three times a day 5 days - Prescribed (as of record date)"}
```
`GET /api/patients/{pid}/findings/{fid}` adds `evidence` (page size, highlighted line bounding boxes, ±2 context lines), `history` (all versions), `conflicts` and `gaps`.

### Review a finding
`POST /api/patients/{pid}/findings/{fid}/review`
```json
{"action": "correct", "changes": {"strength": "500 mg", "date_iso": "2023-06-05"}, "reason": "Verified against page image"}
```
`action` ∈ `verify | correct | reject`; `reason` is required for `correct` and `reject`. Editable fields per type: condition (`name_as_written, normalized_name, status_as_documented, classification`), medication (`name_as_written, normalized_name, strength, dosage, route, frequency, duration, start_date_text, stop_date_text, status`), allergy (`substance, normalized_substance, reaction, severity, assertion`), investigation (`test_name, normalized_test, category, value_text, value_numeric, unit, reference_range, flag_as_written`), event (`event_type, description`), plus `date_text`, `date_iso` (YYYY, YYYY-MM or YYYY-MM-DD). Returns the updated finding.

### Timeline
`GET /api/patients/{pid}/timeline?types=medication,admission&date_from=2023-01-01&date_to=2024-12-31&document_id=…&verification=unverified&q=metformin`
```json
{"dated": [{"id": "fnd_…", "event_type": "admission", "summary": "Hospital admission", "date_text": "03/02/2024", "date_iso": "2024-02-03",
            "date_kind": "event_date", "document_filename": "A5_…pdf", "page": 1, "passage": "Date of admission: 03/02/2024",
            "verification_status": "unverified", "conflict_ids": []}],
 "undated_or_ambiguous": [ … ], "note": "Ordered by documented event dates; …"}
```

### Conflict review
`POST /api/patients/{pid}/conflicts/{cid}/review` with `{"status": "resolved_by_documented_evidence", "note": "D3 is marked AMENDED"}`. `note` is required for `resolved_by_documented_evidence` and `not_a_contradiction`. Returns the conflict with its `resolutions` history.

### Duplicate review
`POST /api/patients/{pid}/duplicates/{id}/review` with `{"decision": "confirmed_duplicate" | "not_duplicate" | "pending"}`.

### Ask the records
`POST /api/patients/{pid}/ask` with `{"question": "Is the patient allergic to penicillin?"}` (≤ 500 chars)
```json
{"id": "qa_…", "retrieval_status": "abstained_conflict",
 "answer": "The records contain conflicting statements. I cannot determine which is correct. Both statements are shown with their sources.",
 "intent": "allergy",
 "facts": [{"statement": "Allergy documented: Penicillin (urticaria, moderate) (record dated 5 September 2022)",
            "citation": {"document_filename": "B1_consultation_2022-09-05.pdf", "page": 1, "line": 5, "passage": "Allergies: Allergic to Penicillin (urticaria, moderate)"},
            "verification_status": "unverified", "normalized": null}],
 "citations": [ … ], "conflicts": [{"category": "allergy", "explanation": "…", "evidence": [ … ]}],
 "uncertainty": [], "notes": ["B5_consultation_2023-06-02.jpg (consultation note): no allergy statement - status not documented in this record."],
 "retrieval": {"methods": ["structured_findings"], "findings_considered": 31, "lines_searched": 64},
 "boundary": "Answers are assembled only from this patient's uploaded records. MedTrace does not diagnose or advise."}
```

### Page text correction
`PUT /api/patients/{pid}/documents/{did}/pages/{n}/text` with `{"text": "...", "reason": "OCR merged words"}`; then `POST …/reprocess` to extract from the corrected text.

### Evaluation
`POST /api/evaluation/run` (admin, ~1 min) runs the full evaluation in an isolated temporary database and stores the result; `GET /api/evaluation/latest` returns `{created_at, duration_ms, metrics_json, report_markdown}`. Sub-resources: `/api/evaluation/extraction`, `/precision-recall`, `/f1`, `/review-time`, `/comparison`.

### Review-time study
`POST /api/review-sessions` `{"patient_id": "...", "mode": "baseline_raw_documents" | "medtrace"}` → tasks; `POST /api/review-sessions/{id}/finish` `{"answers": {"medications": "...", "allergies": "...", "last_lab_date": "...", "conflicts": "..."}}` → duration and automatic scoring of the medication and allergy tasks.
