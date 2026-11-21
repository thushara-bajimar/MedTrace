import { useState } from "react";
import { Link } from "react-router-dom";
import { api, P } from "../api";
import type { FindingDetail } from "../types";
import { Badge, ConfidenceBadge, DateCell, ErrorBox, Spinner, VerificationBadge, fmtDateTime, label, useAsync } from "./ui";

const EDITABLE: Record<string, string[]> = {
  condition: ["name_as_written", "normalized_name", "status_as_documented", "classification"],
  medication: ["name_as_written", "normalized_name", "strength", "dosage", "route", "frequency", "duration", "start_date_text", "stop_date_text", "status"],
  allergy: ["substance", "normalized_substance", "reaction", "severity", "assertion"],
  investigation: ["test_name", "normalized_test", "category", "value_text", "value_numeric", "unit", "reference_range", "flag_as_written"],
  event: ["event_type", "description"],
};
const ENUMS: Record<string, string[]> = {
  status: ["prescribed", "documented_ongoing", "documented_stopped", "documented_changed", "historical", "uncertain", "mentioned_only", "unknown"],
  status_as_documented: ["confirmed_as_documented", "suspected", "possible", "ruled_out", "history_of", "known_case", "explicitly_denied"],
  assertion: ["documented_allergy", "explicitly_denied_specific", "explicitly_denied_general", "status_not_recorded"],
  category: ["laboratory", "imaging", "other"],
  event_type: ["admission", "discharge", "surgery", "procedure", "consultation", "investigation", "follow_up", "documented_event"],
};

export function PageWithHighlight({ pid, docId, page, width, height, boxes }: {
  pid: string; docId: string; page: number; width: number | null; height: number | null;
  boxes: { x0: number; y0: number; x1: number; y1: number }[];
}) {
  return (
    <div className="relative border border-slate-200 bg-white">
      <img src={`${P(pid)}/documents/${docId}/pages/${page}/image`} alt={`Source page ${page}`} className="block w-full" />
      {width && height && boxes.map((b, i) => (
        <div key={i} className="absolute border-2 border-amber-500 bg-amber-300/25 rounded-sm pointer-events-none"
          style={{ left: `${(b.x0 / width) * 100 - 0.4}%`, top: `${(b.y0 / height) * 100 - 0.3}%`,
                   width: `${((b.x1 - b.x0) / width) * 100 + 0.8}%`, height: `${((b.y1 - b.y0) / height) * 100 + 0.6}%` }} />
      ))}
    </div>
  );
}

export default function EvidenceDrawer({ pid, findingId, onClose, onChanged, canWrite }: {
  pid: string; findingId: string; onClose: () => void; onChanged?: () => void; canWrite: boolean;
}) {
  const { data: f, error, loading, reload } = useAsync(() => api.get<FindingDetail>(`${P(pid)}/findings/${findingId}`), [pid, findingId]);
  const [mode, setMode] = useState<"view" | "correct" | "reject">("view");
  const [form, setForm] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const submit = async (action: "verify" | "correct" | "reject") => {
    if (!f) return;
    setBusy(true);
    setMsg(null);
    try {
      const changes: Record<string, string | null> = {};
      if (action === "correct") {
        for (const [k, v] of Object.entries(form)) {
          const orig = k === "date_text" ? f.date_text : k === "date_iso" ? f.date_iso : f.details[k];
          if ((v ?? "") !== String(orig ?? "")) changes[k] = v === "" ? null : v;
        }
        if (!Object.keys(changes).length) throw new Error("No field was changed.");
      }
      await api.post(`${P(pid)}/findings/${f.id}/review`, { action, changes: action === "correct" ? changes : undefined, reason: reason || undefined });
      setMode("view");
      setReason("");
      reload();
      onChanged?.();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const startCorrect = () => {
    if (!f) return;
    const init: Record<string, string> = { date_text: f.date_text ?? "", date_iso: f.date_iso ?? "" };
    for (const k of EDITABLE[f.finding_type] ?? []) init[k] = f.details[k] == null ? "" : String(f.details[k]);
    setForm(init);
    setMode("correct");
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside className="h-full w-full max-w-5xl overflow-y-auto bg-slate-50 shadow-xl" onClick={(e) => e.stopPropagation()} aria-label="Evidence viewer">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500">Evidence viewer</div>
            <div className="font-semibold text-slate-900">{f?.summary ?? "…"}</div>
          </div>
          <button className="btn-secondary" onClick={onClose}>Close</button>
        </div>
        {loading && !f && <Spinner />}
        {error && <div className="p-4"><ErrorBox error={error} /></div>}
        {f && (
          <div className="grid gap-4 p-5 lg:grid-cols-[1.15fr_1fr]">
            <section className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <div>
                  <span className="font-medium">{f.evidence.document_filename}</span>
                  <span className="muted"> · {label(f.evidence.document_type)} · page {f.evidence.page}, line {f.evidence.line_start + 1}</span>
                </div>
                <Link className="text-brand-700 text-xs hover:underline" to={`/patients/${pid}/documents/${f.document_id}?page=${f.page_number}&line=${f.line_start}`}>Open full document →</Link>
              </div>
              <PageWithHighlight pid={pid} docId={f.document_id} page={f.page_number} width={f.evidence.page_width} height={f.evidence.page_height}
                boxes={f.evidence.page_text_source === "human_corrected" ? [] : f.evidence.highlight} />
              <div className="card p-3">
                <div className="text-xs font-semibold text-slate-500 mb-1">Source passage (verbatim, {label(f.evidence.page_text_source)} text)</div>
                <div className="font-mono text-[13px] space-y-0.5">
                  {f.evidence.context_lines.map((l) => (
                    <div key={l.line_index} className={l.line_index >= f.line_start && l.line_index <= f.line_end ? "bg-amber-100 rounded px-1" : "px-1 text-slate-500"}>
                      {l.text}{l.confidence != null && <span className="ml-2 text-[10px] text-slate-400">ocr {l.confidence.toFixed(2)}</span>}
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="space-y-3">
              <div className="card p-3 space-y-2">
                <div className="flex flex-wrap gap-1.5">
                  <Badge tone="teal">{f.finding_type}</Badge>
                  <VerificationBadge status={f.verification_status} />
                  <ConfidenceBadge label={f.confidence_label} score={f.confidence_score} reasons={f.confidence_reasons} />
                  <Badge>{label(f.provenance_type)}</Badge>
                  <Badge>{label(f.extraction_method)}</Badge>
                </div>
                <div className="text-xs text-slate-500">Extracted span: <span className="font-mono text-slate-800">“{f.original_text}”</span></div>
                <table className="w-full text-sm">
                  <tbody>
                    <tr><td className="py-1 pr-2 text-slate-500 w-40">date as written</td><td><DateCell text={f.date_text} iso={null} status={f.date_status} candidates={f.date_candidates} /></td></tr>
                    <tr><td className="py-1 pr-2 text-slate-500">interpreted date</td><td>{f.date_iso ?? <span className="text-slate-400 italic">not interpreted</span>} <span className="text-[11px] text-slate-500">{f.date_role ? `(${label(f.date_role)})` : ""}</span></td></tr>
                    {Object.entries(f.details).map(([k, v]) => (
                      <tr key={k}>
                        <td className="py-1 pr-2 text-slate-500">{label(k)}{k.startsWith("normalized") || k.startsWith("converted") ? <span className="text-[10px] text-violet-600"> (normalised)</span> : null}</td>
                        <td className={v == null ? "text-slate-400 italic" : ""}>{v == null ? "not documented" : String(v)}</td>
                      </tr>
                    ))}
                    {f.temporal_status && <tr><td className="py-1 pr-2 text-slate-500">temporal status</td><td>{label(f.temporal_status)}</td></tr>}
                  </tbody>
                </table>
                {f.confidence_reasons?.length > 0 && (
                  <details className="text-xs text-slate-600"><summary className="cursor-pointer">How confidence was determined</summary>
                    <ul className="list-disc ml-5 mt-1">{f.confidence_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                    <p className="mt-1 text-slate-500">Confidence is a rule-based heuristic, not a guarantee. Verify against the source.</p>
                  </details>
                )}
              </div>

              {f.conflicts.length > 0 && (
                <div className="card p-3 border-red-200">
                  <div className="text-xs font-semibold text-red-700 mb-1">Involved in conflicts</div>
                  {f.conflicts.map((c) => <div key={c.id} className="text-sm">• {c.explanation} <Badge tone="red">{label(c.status)}</Badge></div>)}
                </div>
              )}
              {f.gaps.length > 0 && (
                <div className="card p-3">
                  <div className="text-xs font-semibold text-amber-700 mb-1">Documentation gaps</div>
                  {f.gaps.map((g, i) => <div key={i} className="text-sm">• {g.description}</div>)}
                </div>
              )}

              {canWrite && mode === "view" && (
                <div className="flex flex-wrap gap-2">
                  <button className="btn-primary" disabled={busy} onClick={() => submit("verify")}>Mark verified</button>
                  <button className="btn-secondary" onClick={startCorrect}>Correct extraction</button>
                  <button className="btn-danger" onClick={() => setMode("reject")}>Reject</button>
                </div>
              )}
              {mode === "correct" && (
                <div className="card p-3 space-y-2">
                  <div className="text-sm font-semibold">Correct extraction</div>
                  <p className="text-xs text-slate-500">The original machine extraction (version 1) and the verbatim evidence are kept. Your correction becomes a new version.</p>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.keys(form).map((k) => (
                      <div key={k}>
                        <label className="label">{label(k)}</label>
                        {ENUMS[k] ? (
                          <select className="input" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })}>
                            {ENUMS[k].map((o) => <option key={o} value={o}>{label(o)}</option>)}
                          </select>
                        ) : (
                          <input className="input" value={form[k]} placeholder={k === "date_iso" ? "YYYY-MM-DD" : ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                        )}
                      </div>
                    ))}
                  </div>
                  <label className="label">Reason (required)</label>
                  <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. OCR misread 5 as 6; verified against page image" />
                  <div className="flex gap-2"><button className="btn-primary" disabled={busy || !reason} onClick={() => submit("correct")}>Save correction</button><button className="btn-secondary" onClick={() => setMode("view")}>Cancel</button></div>
                </div>
              )}
              {mode === "reject" && (
                <div className="card p-3 space-y-2">
                  <label className="label">Reason for rejecting this extraction (required)</label>
                  <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
                  <div className="flex gap-2"><button className="btn-danger" disabled={busy || !reason} onClick={() => submit("reject")}>Reject finding</button><button className="btn-secondary" onClick={() => setMode("view")}>Cancel</button></div>
                </div>
              )}
              {msg && <ErrorBox error={msg} />}

              <div className="card p-3">
                <div className="text-xs font-semibold text-slate-500 mb-2">Version history</div>
                <ol className="space-y-2">
                  {f.history.map((h) => (
                    <li key={h.version} className="text-xs border-l-2 pl-2 border-slate-200">
                      <div className="font-medium text-slate-800">v{h.version} · {h.origin === "machine" ? "machine extraction (original)" : `human · ${h.reviewer ?? "unknown"}`} · {fmtDateTime(h.created_at)}</div>
                      {h.reason && <div className="text-slate-600">{h.reason}</div>}
                      <div className="font-mono text-[11px] text-slate-500 break-all">{JSON.stringify(h.data_json)}{h.date_iso ? ` · date ${h.date_iso}` : ""}</div>
                    </li>
                  ))}
                </ol>
              </div>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}
