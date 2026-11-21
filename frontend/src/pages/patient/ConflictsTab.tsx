import { useState } from "react";
import { api, P } from "../../api";
import type { Conflict } from "../../types";
import { Badge, Empty, ErrorBox, Notice, Spinner, fmtDateTime, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

const STATUSES = ["unresolved", "reviewed", "resolved_by_documented_evidence", "not_a_contradiction", "insufficient_information"];

function ConflictCard({ c, pid, canWrite, openEvidence, onDone }: { c: Conflict; pid: string; canWrite: boolean; openEvidence: (id: string) => void; onDone: () => void }) {
  const [status, setStatus] = useState(c.status);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setErr(null);
    try { await api.post(`${P(pid)}/conflicts/${c.id}/review`, { status, note: note || undefined }); setNote(""); onDone(); }
    catch (e) { setErr((e as Error).message); }
  };
  return (
    <div className={`card p-4 ${c.status === "unresolved" ? "border-red-200" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="red">{label(c.category)}</Badge>
        <Badge tone={c.status === "unresolved" ? "red" : "gray"}>{label(c.status)}</Badge>
        {!c.still_detected && <Badge tone="amber" title="After later corrections the detector no longer finds this conflict; history is kept">no longer detected</Badge>}
        <span className="text-xs muted ml-auto">detected {fmtDateTime(c.detected_at)}</span>
      </div>
      <div className="mt-2 text-sm font-medium text-slate-900">{c.explanation}</div>
      <div className="mt-3 grid md:grid-cols-2 gap-3">
        {c.evidence_json.map((e) => (
          <button key={e.finding_id} className="text-left rounded-md border border-slate-200 bg-slate-50 p-3 hover:border-brand-300" onClick={() => openEvidence(e.finding_id)}>
            <div className="text-xs text-slate-500">{e.document_filename} · {label(e.document_type)} · p.{e.page} · {e.date_text ?? "date not documented"}</div>
            <div className="mt-1 text-sm font-semibold">{e.value}</div>
            <div className="mt-1 font-mono text-[12px] text-slate-700">“{e.passage}”</div>
          </button>
        ))}
      </div>
      {c.resolutions.length > 0 && (
        <div className="mt-3 text-xs text-slate-600">
          <div className="font-semibold">Resolution history</div>
          {c.resolutions.map((r, i) => <div key={i}>{fmtDateTime(r.created_at)} · {r.reviewer}: {label(r.previous_status)} → {label(r.new_status)}{r.note ? ` — “${r.note}”` : ""}</div>)}
        </div>
      )}
      {canWrite && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div><label className="label">Review status</label>
            <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>{STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></div>
          <div className="flex-1 min-w-[16rem]"><label className="label">Explanation (required when resolving)</label><input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Which documented evidence supports this decision?" /></div>
          <button className="btn-primary" onClick={save}>Record review</button>
        </div>
      )}
      {err && <div className="mt-2"><ErrorBox error={err} /></div>}
    </div>
  );
}

export default function ConflictsTab({ pid, canWrite, refreshKey, openEvidence, bump }: TabProps) {
  const [stale, setStale] = useState(false);
  const { data, error, loading, reload } = useAsync(() => api.get<Conflict[]>(`${P(pid)}/conflicts${stale ? "?include_stale=true" : ""}`), [pid, refreshKey, stale]);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div className="space-y-3">
      <Notice tone="warn">Contradictions are surfaced, never silently resolved. Each conflict keeps the evidence from every source. Only a human reviewer can record a resolution, with an explanation; the original statements remain unchanged.</Notice>
      <div className="flex items-center gap-3 text-sm">
        <label className="flex items-center gap-1"><input type="checkbox" checked={stale} onChange={(e) => setStale(e.target.checked)} /> include conflicts no longer detected</label>
        {canWrite && <button className="btn-secondary" onClick={async () => { await api.post(`${P(pid)}/conflicts/detect`); reload(); }}>Re-run detection</button>}
      </div>
      {(data ?? []).length === 0 ? <div className="card"><Empty>No contradictions detected. (Detection covers medication dose/status on the same date, allergy statements, event dates and same-day lab values.)</Empty></div>
        : data!.map((c) => <ConflictCard key={c.id} c={c} pid={pid} canWrite={canWrite} openEvidence={openEvidence} onDone={() => { reload(); bump(); }} />)}
    </div>
  );
}
