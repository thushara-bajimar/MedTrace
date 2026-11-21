export interface User { id: string; username: string; role: "admin" | "reviewer" | "viewer" }

export interface Patient {
  id: string; display_name: string; synthetic_label: string | null; date_of_birth_text: string | null; sex: string | null;
  notes: string | null; is_synthetic: number; created_at: string;
  counts: { documents: number; findings: number; unverified: number; conflicts_unresolved: number; duplicates_pending: number; gaps: number; processing: number };
}

export interface DocumentRow {
  id: string; patient_id: string; original_filename: string; file_format: string; mime_type: string; size_bytes: number; sha256: string;
  doc_type: string; doc_type_confidence: number | null; doc_type_source: string; doc_type_original: string | null;
  document_date_text: string | null; document_date_iso: string | null; document_date_status: string; provider: string | null;
  page_count: number | null; upload_date: string; extraction_status: string; ocr_status: string; text_source_summary: string | null;
  ocr_mean_confidence: number | null; injection_flags: string[] | null; error_message: string | null;
  findings_count: number; findings_by_type: Record<string, number>; conflicts_count: number;
  duplicate_flags: { id: string; kind: string; similarity: number; review_status: string; other_document_id: string }[];
  preview: string | null;
}

export interface Finding {
  id: string; patient_id: string; document_id: string; finding_type: string; section: string | null; current_version: number;
  verification_status: string; confidence_score: number; confidence_label: string; confidence_reasons: string[];
  extraction_method: string; provenance_type: string; page_number: number; line_start: number; line_end: number;
  source_passage: string; original_text: string; date_text: string | null; date_iso: string | null; date_precision: string | null;
  date_status: string; date_candidates: string[] | null; date_role: string | null; temporal_status: string | null;
  document_filename: string; document_type: string; document_date_text: string | null; document_upload_date: string;
  details: Record<string, string | number | null>; summary?: string;
}

export interface EvidenceLine { line_index: number; text: string; x0: number; y0: number; x1: number; y1: number; confidence: number | null; source: string }
export interface Evidence {
  document_id: string; document_filename: string; document_type: string; page: number; line_start: number; line_end: number;
  source_passage: string; original_text: string; extraction_method: string; provenance_type: string;
  page_width: number | null; page_height: number | null; page_text_source: string | null;
  highlight: EvidenceLine[]; context_lines: EvidenceLine[];
}
export interface VersionRow { version: number; origin: string; data_json: Record<string, unknown>; date_text: string | null; date_iso: string | null; reason: string | null; created_at: string; reviewer: string | null }
export interface FindingDetail extends Finding {
  evidence: Evidence; history: VersionRow[];
  conflicts: { id: string; category: string; explanation: string; status: string }[];
  gaps: { gap_type: string; description: string }[];
}

export interface TimelineEntry {
  id: string; finding_type: string; event_type: string; summary: string; date_text: string | null; date_iso: string | null;
  date_status: string; date_kind: string; date_role: string | null; date_candidates: string[] | null; temporal_status: string | null;
  document_id: string; document_filename: string; document_type: string; document_date_text: string | null; upload_date: string;
  page: number; line: number; passage: string; confidence_label: string; confidence_score: number; verification_status: string;
  provenance_type: string; conflict_ids: string[];
}

export interface ConflictEvidence { finding_id: string; document_id: string; document_filename: string; document_type: string; page: number; line: number; passage: string; date_text: string | null; date_iso: string | null; value: string }
export interface Conflict {
  id: string; category: string; explanation: string; evidence_json: ConflictEvidence[]; status: string; still_detected: number;
  detected_at: string; updated_at: string; resolutions: { previous_status: string; new_status: string; note: string | null; created_at: string; reviewer: string | null }[];
}

export interface Citation { finding_id?: string; document_id: string; document_filename: string; document_type: string; page: number; line: number; passage: string; score?: number }
export interface Fact { statement: string; finding_type: string; date_text: string | null; date_iso: string | null; date_status: string; provenance_type: string; verification_status: string; confidence_label: string; normalized: Record<string, string> | null; citation: Citation }
export interface Answer {
  id: string; question: string; retrieval_status: string; answer: string; intent: string | null; facts: Fact[]; citations: Citation[];
  conflicts: { conflict_id: string; category: string; explanation: string; status: string; evidence: ConflictEvidence[] }[];
  uncertainty: string[]; notes: string[]; related_passages: Citation[]; retrieval: { methods: string[]; findings_considered: number; lines_searched: number }; boundary: string;
}
