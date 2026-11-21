import { useState } from "react";
import { api, P, qs } from "../../api";
import type { DocumentRow, TimelineEntry } from "../../types";
import { Badge, ConfidenceBadge, DateCell, Empty, ErrorBox, Notice, Spinner, TYPE_TONE, VerificationBadge, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

const TYPE_OPTIONS = ["medication", "condition", "allergy", "investigation", "event", "admission", "discharge", "surgery", "consultation", "follow_up"];

function Row({ e, openEvidence }: { e: TimelineEntry; openEvidence: (id: string) => void }) {
  return (
    <li className="relative pl-6">
      <span className={`absolute left-0 top-2 h-2.5 w-2.5 rounded-full ${e.conflict_ids.length ? "bg-red-500" : e.finding_type === "medication" ? "bg-brand-500" : "bg-slate-400"}`} />
      <div className="card p-3 hover:border-brand-200 cursor-pointer" onClick={() => openEvidence(e.id)}>
        <div className="flex flex-wrap items-center gap-2">
          <DateCell text={e.date_text} iso={e.date_iso} status={e.date_status} candidates={e.date_candidates} />
          <Badge tone={TYPE_TONE[e.event_type] ?? "gray"}>{label(e.event_type)}</Badge>
          {e.date_kind === "document_date" && <Badge title="The finding has no own date; the document's date is shown">document date</Badge>}
          {e.temporal_status && e.temporal_status !== "unknown" && <Badge tone="violet">{label(e.temporal_status)}</Badge>}
          {e.conflict_ids.length > 0 && <Badge tone="red">conflict</Badge>}
          <span className="ml-auto flex gap-1"><VerificationBadge status={e.verification_status} /><ConfidenceBadge label={e.confidence_label} score={e.confidence_score} /></span>
        </div>
        <div className="mt-1 text-sm font-medium text-slate-900">{e.summary}</div>
        <div className="mt-0.5 text-xs text-slate-500">
          Source: {e.document_filename} · {label(e.document_type)} · p.{e.page} · <span className="font-mono">“{e.passage.length > 110 ? e.passage.slice(0, 110) + "…" : e.passage}”</span>
        </div>
      </div>
    </li>
  );
}

export default function TimelineTab({ pid, refreshKey, openEvidence }: TabProps) {
  const [f, setF] = useState({ types: "", date_from: "", date_to: "", document_id: "", verification: "", q: "" });
  const [applied, setApplied] = useState(f);
  const docs = useAsync(() => api.get<DocumentRow[]>(`${P(pid)}/documents`), [pid]);
  const { data, error, loading } = useAsync(() => api.get<{ dated: TimelineEntry[]; undated_or_ambiguous: TimelineEntry[]; note: string }>(`${P(pid)}/timeline${qs(applied)}`), [pid, applied, refreshKey]);
  const years: Record<string, TimelineEntry[]> = {};
  (data?.dated ?? []).forEach((e) => { (years[e.date_iso!.slice(0, 4)] ??= []).push(e); });
  return (
    <div className="grid lg:grid-cols-[15rem_1fr] gap-5">
      <form className="card p-3 space-y-2 h-fit lg:sticky lg:top-4" onSubmit={(e) => { e.preventDefault(); setApplied(f); }}>
        <div className="h2">Filter</div>
        <div><label className="label">Type</label>
          <select className="input" value={f.types} onChange={(e) => setF({ ...f, types: e.target.value })}>
            <option value="">All</option>{TYPE_OPTIONS.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select></div>
        <div><label className="label">From (YYYY-MM-DD)</label><input className="input" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} placeholder="2023-01-01" /></div>
        <div><label className="label">To</label><input className="input" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} placeholder="2024-12-31" /></div>
        <div><label className="label">Document</label>
          <select className="input" value={f.document_id} onChange={(e) => setF({ ...f, document_id: e.target.value })}>
            <option value="">All documents</option>{(docs.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.original_filename}</option>)}
          </select></div>
        <div><label className="label">Verification</label>
          <select className="input" value={f.verification} onChange={(e) => setF({ ...f, verification: e.target.value })}>
            <option value="">Any</option><option value="unverified">Unverified</option><option value="human_verified">Human verified</option><option value="corrected">Corrected</option>
          </select></div>
        <div><label className="label">Search</label><input className="input" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="e.g. metformin" /></div>
        <div className="flex gap-2"><button className="btn-primary">Apply</button><button type="button" className="btn-secondary" onClick={() => { const z = { types: "", date_from: "", date_to: "", document_id: "", verification: "", q: "" }; setF(z); setApplied(z); }}>Reset</button></div>
      </form>
      <div className="space-y-4 min-w-0">
        {data && <Notice>{data.note}</Notice>}
        {loading && !data && <Spinner />}
        {error && <ErrorBox error={error} />}
        {data && data.dated.length === 0 && data.undated_or_ambiguous.length === 0 && <div className="card"><Empty>No entries match.</Empty></div>}
        {Object.entries(years).map(([y, list]) => (
          <section key={y}>
            <h3 className="text-sm font-semibold text-slate-500 mb-2">{y}</h3>
            <ol className="space-y-2 border-l border-slate-200 ml-1">{list.map((e) => <Row key={e.id} e={e} openEvidence={openEvidence} />)}</ol>
          </section>
        ))}
        {data && data.undated_or_ambiguous.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-amber-700 mb-1">Undated or ambiguous ({data.undated_or_ambiguous.length})</h3>
            <p className="text-xs muted mb-2">These entries could not be placed in time without guessing. Their position is intentionally not inferred.</p>
            <ol className="space-y-2 border-l border-amber-200 ml-1">{data.undated_or_ambiguous.map((e) => <Row key={e.id} e={e} openEvidence={openEvidence} />)}</ol>
          </section>
        )}
      </div>
    </div>
  );
}
