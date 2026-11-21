import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, P, qs } from "../../api";
import type { DocumentRow } from "../../types";
import { Badge, DateCell, Empty, ErrorBox, Spinner, fmtDateTime, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

const TYPES = ["", "lab_report", "prescription", "discharge_summary", "consultation_note", "imaging_report", "unclassified"];

export default function DocumentsTab({ pid, canWrite, refreshKey, bump }: TabProps) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [query, setQuery] = useState({ q: "", type: "" });
  const { data, error, loading, reload } = useAsync(() => api.get<DocumentRow[]>(`${P(pid)}/documents${qs({ q: query.q, doc_type: query.type })}`), [pid, query, refreshKey]);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pending = (data ?? []).some((d) => d.extraction_status === "pending" || d.extraction_status === "processing");

  useEffect(() => {
    if (!pending) return;
    const t = setInterval(reload, 2000);
    return () => clearInterval(t);
  }, [pending, reload]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploadErr(null);
    setUploadMsg(null);
    for (const f of Array.from(files)) {
      try {
        const r = await api.upload<{ note: string }>(`${P(pid)}/documents`, f);
        setUploadMsg(`${f.name}: ${r.note}`);
      } catch (e) {
        setUploadErr(`${f.name}: ${(e as Error).message}`);
      }
    }
    if (fileRef.current) fileRef.current.value = "";
    reload();
    bump();
  };

  return (
    <div className="space-y-3">
      {canWrite && (
        <div className="card p-4 flex flex-wrap items-center gap-3"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}>
          <div className="flex-1 min-w-[16rem]">
            <div className="h2">Upload documents</div>
            <p className="text-xs muted">PDF (native or scanned), PNG, JPG/JPEG · max 15 MB · processed locally (text layer first, OCR only when needed). Drag files here or choose.</p>
          </div>
          <input ref={fileRef} type="file" multiple accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => upload(e.target.files)} className="text-sm" aria-label="Upload documents" />
          {uploadMsg && <div className="w-full text-xs text-emerald-700">{uploadMsg}</div>}
          {uploadErr && <div className="w-full"><ErrorBox error={uploadErr} /></div>}
        </div>
      )}
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setQuery({ q, type }); }}>
        <input className="input max-w-xs" placeholder="Search text or filename…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input max-w-[14rem]" value={type} onChange={(e) => { setType(e.target.value); setQuery({ q, type: e.target.value }); }}>
          {TYPES.map((t) => <option key={t} value={t}>{t ? label(t) : "All document types"}</option>)}
        </select>
        <button className="btn-secondary">Search</button>
      </form>
      {loading && !data && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && (data.length === 0 ? <div className="card"><Empty>No documents.</Empty></div> : (
        <div className="grid gap-3">
          {data.map((d) => (
            <div key={d.id} className="card p-4 grid md:grid-cols-[1fr_auto] gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Link className="font-medium text-brand-700 hover:underline" to={`/patients/${pid}/documents/${d.id}`}>{d.original_filename}</Link>
                  <Badge tone="teal" title={d.doc_type_source === "human" ? `Set by reviewer (classifier said ${d.doc_type_original})` : `Classifier confidence ${d.doc_type_confidence ?? "—"}`}>{label(d.doc_type)}{d.doc_type_source === "human" ? " ✓" : ""}</Badge>
                  <Badge tone={d.extraction_status === "completed" ? "green" : d.extraction_status === "failed" ? "red" : "amber"}>extraction: {d.extraction_status}</Badge>
                  <Badge tone={d.ocr_status === "not_required" ? "gray" : d.ocr_status === "completed" ? "blue" : "red"}>OCR: {label(d.ocr_status)}{d.ocr_mean_confidence != null ? ` (${d.ocr_mean_confidence.toFixed(2)})` : ""}</Badge>
                  <Badge>text: {label(d.text_source_summary)}</Badge>
                  {d.conflicts_count > 0 && <Badge tone="red">{d.conflicts_count} conflicts</Badge>}
                  {d.duplicate_flags.map((x) => <Badge key={x.id} tone={x.kind === "similar_distinct" ? "gray" : "amber"}>{label(x.kind)} ({x.similarity.toFixed(2)})</Badge>)}
                  {d.injection_flags && <Badge tone="violet" title={d.injection_flags.join("\n")}>instruction-like text ignored</Badge>}
                </div>
                <div className="mt-1 grid sm:grid-cols-4 gap-x-4 text-xs text-slate-600">
                  <div>Document date: <DateCell text={d.document_date_text} iso={d.document_date_iso} status={d.document_date_status} /></div>
                  <div>Uploaded: {fmtDateTime(d.upload_date)}</div>
                  <div>{d.provider ?? "Provider not documented"}</div>
                  <div>{d.page_count ?? "?"} page(s) · {d.file_format.toUpperCase()} · sha256 {d.sha256.slice(0, 10)}…</div>
                </div>
                {d.preview && <pre className="mt-2 max-h-16 overflow-hidden whitespace-pre-wrap font-mono text-[11px] text-slate-500">{d.preview}</pre>}
                {d.error_message && <div className="mt-1 text-xs text-red-700">{d.error_message}</div>}
              </div>
              <div className="text-right text-xs space-y-1">
                <div className="text-2xl font-semibold tabular-nums text-slate-900">{d.findings_count}</div>
                <div className="muted">findings</div>
                <div className="flex flex-wrap justify-end gap-1">{Object.entries(d.findings_by_type).map(([k, v]) => <Badge key={k}>{k} {v}</Badge>)}</div>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
