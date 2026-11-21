import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, P } from "../api";
import { useAuth } from "../App";
import type { DocumentRow, Finding } from "../types";
import EvidenceDrawer, { PageWithHighlight } from "../components/EvidenceDrawer";
import { Badge, DateCell, ErrorBox, Notice, Spinner, label, useAsync } from "../components/ui";

interface Page { page_number: number; text: string; original_text: string; text_source: string; original_text_source: string; ocr_confidence: number | null; width: number; height: number;
  lines: { line_index: number; text: string; x0: number; y0: number; x1: number; y1: number; confidence: number | null; source: string }[];
  corrections: { previous_text: string; corrected_text: string; reason: string; corrected_at: string; reviewer: string }[] }

const TYPES = ["lab_report", "prescription", "discharge_summary", "consultation_note", "imaging_report", "unclassified"];

export default function DocumentViewer() {
  const { pid = "", did = "" } = useParams();
  const { user } = useAuth();
  const canWrite = user?.role !== "viewer";
  const [sp, setSp] = useSearchParams();
  const page = Number(sp.get("page") ?? 1);
  const line = sp.get("line") != null ? Number(sp.get("line")) : null;
  const [key, setKey] = useState(0);
  const doc = useAsync(() => api.get<DocumentRow>(`${P(pid)}/documents/${did}`), [pid, did, key]);
  const text = useAsync(() => api.get<{ pages: Page[] }>(`${P(pid)}/documents/${did}/text`), [pid, did, key]);
  const findings = useAsync(() => api.get<Finding[]>(`${P(pid)}/findings?document_id=${did}`), [pid, did, key]);
  const [evidence, setEvidence] = useState<string | null>(null);
  const [selLine, setSelLine] = useState<number | null>(null);
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState("");
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  if (doc.loading && !doc.data) return <Spinner />;
  if (doc.error || !doc.data) return <div className="p-6"><ErrorBox error={doc.error ?? "Not found"} /></div>;
  const d = doc.data;
  const p = text.data?.pages.find((x) => x.page_number === page);
  const pageFindings = (findings.data ?? []).filter((f) => f.page_number === page);
  const active = selLine ?? line;
  const boxes = p && active != null ? p.lines.filter((l) => l.line_index === active) : [];

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); setMsg(ok); setKey((k) => k + 1); } catch (e) { setMsg((e as Error).message); }
  };

  return (
    <div className="p-6 space-y-3">
      <div className="text-xs"><Link className="text-brand-700 hover:underline" to={`/patients/${pid}/documents`}>← Documents</Link></div>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="h1">{d.original_filename}</h1>
          <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
            <Badge tone="teal">{label(d.doc_type)}{d.doc_type_source === "human" ? " (reviewer)" : ` (classifier ${d.doc_type_confidence ?? ""})`}</Badge>
            <Badge>{d.page_count} page(s)</Badge><Badge>text: {label(d.text_source_summary)}</Badge>
            <Badge tone="blue">OCR: {label(d.ocr_status)}{d.ocr_mean_confidence != null ? ` · mean conf ${d.ocr_mean_confidence.toFixed(3)}` : ""}</Badge>
            <span>Document date: <DateCell text={d.document_date_text} iso={d.document_date_iso} status={d.document_date_status} /></span>
          </div>
          <div className="text-[11px] text-slate-500 mt-1">Provider: {d.provider ?? "not documented"} · SHA-256 {d.sha256}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <a className="btn-secondary" href={`${P(pid)}/documents/${did}/file`}>Download original</a>
          {canWrite && (
            <>
              <select className="input w-auto" value={d.doc_type} onChange={(e) => act(() => api.patch(`${P(pid)}/documents/${did}`, { doc_type: e.target.value }), "Document type corrected — reprocess to re-run extraction.")}>
                {TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
              </select>
              <button className="btn-secondary" onClick={() => act(() => api.post(`${P(pid)}/documents/${did}/reprocess`), "Reprocessing started. Earlier unverified findings are kept as inactive; reviewed findings are retained.")}>Reprocess</button>
              <button className="btn-danger" onClick={() => { if (confirm("Delete this document, its findings and related conflict records? This cannot be undone.")) act(() => api.del(`${P(pid)}/documents/${did}`), "Deleted."); }}>Delete</button>
            </>
          )}
        </div>
      </div>
      {msg && <Notice>{msg}</Notice>}
      {d.injection_flags && <Notice tone="warn">Instruction-like text was found in this document and treated purely as data (never as instructions): <span className="font-mono">{d.injection_flags.join(" | ")}</span></Notice>}
      <div className="flex gap-1">{Array.from({ length: d.page_count ?? 1 }, (_, i) => i + 1).map((n) => <button key={n} className={n === page ? "btn-primary" : "btn-secondary"} onClick={() => { setSp({ page: String(n) }); setSelLine(null); }}>Page {n}</button>)}</div>
      <div className="grid xl:grid-cols-[1.1fr_1fr] gap-4">
        <PageWithHighlight pid={pid} docId={did} page={page} width={p?.width ?? null} height={p?.height ?? null} boxes={p?.text_source === "human_corrected" ? [] : boxes} />
        <div className="space-y-3 min-w-0">
          <div className="card p-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold text-slate-500">Extracted text — {label(p?.text_source)}{p?.ocr_confidence != null ? ` (OCR mean ${p.ocr_confidence.toFixed(3)})` : ""}</div>
              {canWrite && p && !edit && <button className="text-xs text-brand-700" onClick={() => { setDraft(p.text); setEdit(true); }}>Correct page text</button>}
            </div>
            {edit && p ? (
              <div className="space-y-2 mt-2">
                <textarea className="input font-mono text-xs h-64" value={draft} onChange={(e) => setDraft(e.target.value)} />
                <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required), e.g. OCR merged words" />
                <div className="flex gap-2"><button className="btn-primary" disabled={reason.length < 3} onClick={() => act(async () => { await api.put(`${P(pid)}/documents/${did}/pages/${page}/text`, { text: draft, reason }); setEdit(false); setReason(""); }, "Page text corrected. Original machine text is preserved. Reprocess to extract from the corrected text.")}>Save</button><button className="btn-secondary" onClick={() => setEdit(false)}>Cancel</button></div>
              </div>
            ) : (
              <div className="mt-2 font-mono text-[12px] space-y-px max-h-[28rem] overflow-y-auto">
                {p?.lines.map((l) => {
                  const hasFinding = pageFindings.some((f) => l.line_index >= f.line_start && l.line_index <= f.line_end);
                  return (
                    <div key={l.line_index} onClick={() => setSelLine(l.line_index)}
                      className={`px-1 rounded cursor-pointer ${active === l.line_index ? "bg-amber-100" : hasFinding ? "bg-brand-50" : "hover:bg-slate-50"}`}>
                      <span className="text-slate-400 mr-2 select-none">{String(l.line_index + 1).padStart(2, " ")}</span>{l.text}
                      {l.confidence != null && <span className="ml-2 text-[10px] text-slate-400">{l.confidence.toFixed(2)}</span>}
                    </div>
                  );
                })}
                {p?.text_source === "human_corrected" && <pre className="whitespace-pre-wrap text-[12px] mt-2 border-t pt-2">{p.text}</pre>}
              </div>
            )}
            {p && p.corrections.length > 0 && <div className="mt-2 text-[11px] text-slate-600">Text corrections: {p.corrections.map((c, i) => <div key={i}>{c.corrected_at} · {c.reviewer}: {c.reason}</div>)}</div>}
          </div>
          <div className="card">
            <div className="h2 px-3 pt-3 pb-1">Findings on this page ({pageFindings.length})</div>
            <ul className="divide-y divide-slate-100">
              {pageFindings.map((f) => (
                <li key={f.id} className={`px-3 py-2 text-sm cursor-pointer hover:bg-slate-50 ${active === f.line_start ? "bg-amber-50" : ""}`} onMouseEnter={() => setSelLine(f.line_start)} onClick={() => setEvidence(f.id)}>
                  <Badge>{f.finding_type}</Badge> <span className="font-medium">{f.summary}</span> <span className="text-[11px] text-slate-500">line {f.line_start + 1} · {label(f.verification_status)}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
      {evidence && <EvidenceDrawer pid={pid} findingId={evidence} canWrite={canWrite} onClose={() => setEvidence(null)} onChanged={() => setKey((k) => k + 1)} />}
    </div>
  );
}
