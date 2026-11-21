-- MedTrace SQLite schema.
-- Principles: stable text identifiers, patient-scoped rows, foreign keys, append-only
-- evidence (machine extractions are never overwritten; corrections create new versions).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- identity / access
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin','reviewer','viewer')),
    failed_logins   INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash      TEXT PRIMARY KEY,           -- sha256 of the random cookie token
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS patients (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    synthetic_label TEXT,                       -- e.g. "Patient A - medication changes"
    date_of_birth_text TEXT,
    sex             TEXT,
    notes           TEXT,
    is_synthetic    INTEGER NOT NULL DEFAULT 1,
    created_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patient_access (
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    permission      TEXT NOT NULL CHECK (permission IN ('read','write')),
    granted_at      TEXT NOT NULL,
    PRIMARY KEY (user_id, patient_id)
);

-- ---------------------------------------------------------------- documents
CREATE TABLE IF NOT EXISTS documents (
    id                  TEXT PRIMARY KEY,
    patient_id          TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    original_filename   TEXT NOT NULL,          -- sanitised, display only
    stored_filename     TEXT NOT NULL,          -- server-generated, never user-controlled
    file_format         TEXT NOT NULL,          -- pdf | png | jpeg
    mime_type           TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL,
    sha256              TEXT NOT NULL,          -- source integrity
    doc_type            TEXT NOT NULL DEFAULT 'unclassified',
    doc_type_confidence REAL,
    doc_type_source     TEXT NOT NULL DEFAULT 'classifier',   -- classifier | human
    doc_type_original   TEXT,                   -- classifier output preserved after a human correction
    document_date_text  TEXT,                   -- exactly as written
    document_date_iso   TEXT,                   -- only when unambiguous
    document_date_status TEXT NOT NULL DEFAULT 'missing',     -- parsed | ambiguous | missing | partial
    provider            TEXT,
    page_count          INTEGER,
    upload_date         TEXT NOT NULL,
    uploaded_by         TEXT REFERENCES users(id) ON DELETE SET NULL,
    extraction_status   TEXT NOT NULL DEFAULT 'pending',      -- pending | processing | completed | failed
    ocr_status          TEXT NOT NULL DEFAULT 'not_required', -- not_required | completed | partial | failed | unavailable
    text_source_summary TEXT,                   -- native | ocr | mixed | human_corrected
    ocr_mean_confidence REAL,
    injection_flags     TEXT,                   -- JSON list of instruction-like passages (treated as data)
    error_message       TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_patient ON documents(patient_id);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(patient_id, sha256);

CREATE TABLE IF NOT EXISTS document_pages (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL,           -- 1-based
    text            TEXT NOT NULL,              -- current text (may be human corrected)
    original_text   TEXT NOT NULL,              -- machine text, never modified
    text_source     TEXT NOT NULL,              -- native | ocr | human_corrected
    original_text_source TEXT NOT NULL,         -- native | ocr
    ocr_confidence  REAL,
    width           REAL,
    height          REAL,
    UNIQUE (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS page_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    page_number     INTEGER NOT NULL,
    line_index      INTEGER NOT NULL,
    text            TEXT NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,         -- bounding box in page coordinates
    confidence      REAL,
    source          TEXT NOT NULL               -- native | ocr
);
CREATE INDEX IF NOT EXISTS idx_lines_doc ON page_lines(document_id, page_number, line_index);
CREATE INDEX IF NOT EXISTS idx_lines_patient ON page_lines(patient_id);

CREATE TABLE IF NOT EXISTS page_text_corrections (
    id              TEXT PRIMARY KEY,
    page_id         TEXT NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    previous_text   TEXT NOT NULL,
    corrected_text  TEXT NOT NULL,
    reason          TEXT,
    corrected_by    TEXT REFERENCES users(id) ON DELETE SET NULL,
    corrected_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_runs (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    extractor_version TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_ms     REAL,
    status          TEXT NOT NULL,              -- running | completed | failed
    stages_json     TEXT                        -- per-stage timings and outcomes
);

-- ---------------------------------------------------------------- findings + evidence
-- One row per extracted fact. Typed attributes live in finding_versions (all versions)
-- and in the *_details tables (current version, for typed querying).
CREATE TABLE IF NOT EXISTS findings (
    id                  TEXT PRIMARY KEY,
    patient_id          TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    document_id         TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    run_id              TEXT REFERENCES processing_runs(id) ON DELETE SET NULL,
    finding_type        TEXT NOT NULL CHECK (finding_type IN ('condition','medication','allergy','investigation','event')),
    section             TEXT,                   -- document section the passage came from
    current_version     INTEGER NOT NULL DEFAULT 1,
    verification_status TEXT NOT NULL DEFAULT 'unverified',  -- unverified | human_verified | corrected | rejected
    confidence_score    REAL NOT NULL,
    confidence_label    TEXT NOT NULL,          -- high | medium | low
    confidence_reasons  TEXT,                   -- JSON list explaining the score
    extraction_method   TEXT NOT NULL,          -- rules_native_text | rules_ocr_text
    provenance_type     TEXT NOT NULL,          -- direct_extraction | ocr_extraction | human_correction
    -- evidence (immutable machine evidence)
    page_number         INTEGER NOT NULL,
    line_start          INTEGER NOT NULL,
    line_end            INTEGER NOT NULL,
    source_passage      TEXT NOT NULL,          -- verbatim text of the supporting line(s)
    original_text       TEXT NOT NULL,          -- verbatim span the fact was read from
    -- temporal
    date_text           TEXT,                   -- as written
    date_iso            TEXT,                   -- only when justified
    date_precision      TEXT,                   -- day | month | year
    date_status         TEXT NOT NULL,          -- parsed | ambiguous | partial | missing | document_date
    date_candidates     TEXT,                   -- JSON list for ambiguous dates
    date_role           TEXT,                   -- e.g. test_date, prescription_date, admission_date
    temporal_status     TEXT,                   -- historical | current_as_documented | discontinued | updated | uncertain | unknown
    is_active           INTEGER NOT NULL DEFAULT 1,  -- 0 when superseded by a re-extraction run
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_patient ON findings(patient_id, finding_type);
CREATE INDEX IF NOT EXISTS idx_findings_doc ON findings(document_id);

CREATE TABLE IF NOT EXISTS finding_versions (
    id              TEXT PRIMARY KEY,
    finding_id      TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    origin          TEXT NOT NULL,              -- machine | human
    data_json       TEXT NOT NULL,              -- typed attributes as extracted / corrected
    date_text       TEXT,
    date_iso        TEXT,
    reason          TEXT,
    created_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (finding_id, version)
);

CREATE TABLE IF NOT EXISTS condition_details (
    finding_id          TEXT PRIMARY KEY REFERENCES findings(id) ON DELETE CASCADE,
    name_as_written     TEXT NOT NULL,
    normalized_name     TEXT,
    status_as_documented TEXT NOT NULL,         -- confirmed_as_documented | suspected | possible | ruled_out | history_of | known_case
    classification      TEXT                    -- only when explicitly written (e.g. a code)
);

CREATE TABLE IF NOT EXISTS medication_details (
    finding_id          TEXT PRIMARY KEY REFERENCES findings(id) ON DELETE CASCADE,
    name_as_written     TEXT NOT NULL,
    normalized_name     TEXT,
    strength            TEXT,
    dosage              TEXT,
    route               TEXT,
    frequency           TEXT,
    duration            TEXT,
    start_date_text     TEXT,
    stop_date_text      TEXT,
    status              TEXT NOT NULL           -- prescribed | documented_ongoing | documented_stopped | documented_changed | historical | uncertain | mentioned_only | unknown
);
CREATE INDEX IF NOT EXISTS idx_med_name ON medication_details(normalized_name);

CREATE TABLE IF NOT EXISTS allergy_details (
    finding_id          TEXT PRIMARY KEY REFERENCES findings(id) ON DELETE CASCADE,
    substance           TEXT,                   -- NULL for a general negative (e.g. NKDA)
    normalized_substance TEXT,
    reaction            TEXT,
    severity            TEXT,
    assertion           TEXT NOT NULL           -- documented_allergy | explicitly_denied_specific | explicitly_denied_general | status_not_recorded
);

CREATE TABLE IF NOT EXISTS investigation_details (
    finding_id          TEXT PRIMARY KEY REFERENCES findings(id) ON DELETE CASCADE,
    test_name           TEXT NOT NULL,          -- as written
    normalized_test     TEXT,
    category            TEXT NOT NULL,          -- laboratory | imaging | other
    value_text          TEXT,                   -- verbatim value / result text
    value_numeric       REAL,
    unit                TEXT,                   -- verbatim unit
    reference_range     TEXT,                   -- verbatim
    flag_as_written     TEXT,                   -- e.g. H / L only if printed
    converted_value     REAL,                   -- display-only conversion, never replaces original
    converted_unit      TEXT,
    conversion_rule     TEXT
);
CREATE INDEX IF NOT EXISTS idx_inv_test ON investigation_details(normalized_test);

CREATE TABLE IF NOT EXISTS event_details (
    finding_id          TEXT PRIMARY KEY REFERENCES findings(id) ON DELETE CASCADE,
    event_type          TEXT NOT NULL,          -- admission | discharge | surgery | procedure | consultation | investigation | follow_up | documented_event
    description         TEXT NOT NULL
);

-- ---------------------------------------------------------------- analysis
CREATE TABLE IF NOT EXISTS conflicts (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    conflict_key    TEXT NOT NULL,              -- deterministic key so re-detection does not duplicate
    category        TEXT NOT NULL,              -- medication_dosage | medication_status | allergy | event_date | investigation_value
    explanation     TEXT NOT NULL,
    evidence_json   TEXT NOT NULL,              -- per finding: document, page, passage, date
    status          TEXT NOT NULL DEFAULT 'unresolved', -- unresolved | reviewed | resolved_by_documented_evidence | not_a_contradiction | insufficient_information
    still_detected  INTEGER NOT NULL DEFAULT 1,
    detector_version TEXT NOT NULL,
    detected_at     TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (patient_id, conflict_key)
);

CREATE TABLE IF NOT EXISTS conflict_findings (
    conflict_id     TEXT NOT NULL REFERENCES conflicts(id) ON DELETE CASCADE,
    finding_id      TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    PRIMARY KEY (conflict_id, finding_id)
);

CREATE TABLE IF NOT EXISTS conflict_resolutions (
    id              TEXT PRIMARY KEY,
    conflict_id     TEXT NOT NULL REFERENCES conflicts(id) ON DELETE CASCADE,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    previous_status TEXT NOT NULL,
    new_status      TEXT NOT NULL,
    note            TEXT,
    reviewer_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    level           TEXT NOT NULL CHECK (level IN ('document','finding')),
    item_a          TEXT NOT NULL,
    item_b          TEXT NOT NULL,
    kind            TEXT NOT NULL,              -- exact_duplicate | near_duplicate | similar_distinct | duplicate_finding | related_finding
    similarity      REAL,
    details_json    TEXT,
    review_status   TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed_duplicate | not_duplicate
    reviewed_by     TEXT REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at     TEXT,
    detected_at     TEXT NOT NULL,
    UNIQUE (patient_id, level, item_a, item_b)
);

CREATE TABLE IF NOT EXISTS gaps (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    document_id     TEXT REFERENCES documents(id) ON DELETE CASCADE,
    finding_id      TEXT REFERENCES findings(id) ON DELETE CASCADE,
    gap_type        TEXT NOT NULL,
    description     TEXT NOT NULL,
    detected_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gaps_patient ON gaps(patient_id);

-- ---------------------------------------------------------------- QA, evaluation, audit
CREATE TABLE IF NOT EXISTS qa_logs (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    user_id         TEXT REFERENCES users(id) ON DELETE SET NULL,
    question        TEXT NOT NULL,
    retrieval_status TEXT NOT NULL,
    answer_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    duration_ms     REAL,
    metrics_json    TEXT NOT NULL,
    report_markdown TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT REFERENCES users(id) ON DELETE SET NULL,
    patient_id      TEXT REFERENCES patients(id) ON DELETE CASCADE,
    mode            TEXT NOT NULL CHECK (mode IN ('baseline_raw_documents','medtrace')),
    participant_kind TEXT NOT NULL CHECK (participant_kind IN ('human','automated_simulation')),
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    duration_seconds REAL,
    tasks_total     INTEGER,
    tasks_correct   INTEGER,
    missed_findings INTEGER,
    corrections_made INTEGER,
    answers_json    TEXT
);

CREATE TABLE IF NOT EXISTS access_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    user_id         TEXT,
    action          TEXT NOT NULL,              -- privacy-conscious: identifiers only, never document text
    patient_id      TEXT,
    resource_id     TEXT,
    outcome         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_access_patient ON access_logs(patient_id);
