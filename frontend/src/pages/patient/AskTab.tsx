import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, P } from "../../api";
import type { Answer } from "../../types";
import { Badge, ErrorBox, Notice, Spinner, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

const EXAMPLES = [
  "Which medications are documented in the uploaded records?",
  "Were any medication changes documented?",
  "When was the last laboratory test documented?",
  "Which allergy statements appear in the records?",
  "What medications were documented in the discharge summary?",
  "What investigations are recorded?",
  "Are there conflicting statements about allergies?",
  "What information is missing from the records?",
  "Should the patient increase the dose?",
];

const STATUS_TONE = (s: string) => (s.startsWith("answered_with") ? "amber" : s.startsWith("answered") ? "green" : s.startsWith("declined") ? "violet" : "red");

export default function AskTab({ pid, openEvidence }: TabProps) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [ans, setAns] = useState<Answer | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const history = useAsync(() => api.get<{ id: string; question: string; retrieval_status: string; created_at: string }[]>(`${P(pid)}/ask/history`), [pid, ans?.id]);
  const ask = async (question: string, e?: FormEvent) => {
    e?.preventDefault();
    if (!question.trim()) return;
    setBusy(true); setErr(null);
    try { setAns(await api.post<Answer>(`${P(pid)}/ask`, { question })); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  const open = async (id: string) => setAns(await api.get<Answer>(`${P(pid)}/ask/${id}`));
  return (
    <div className="grid xl:grid-cols-[1fr_18rem] gap-4">
      <div className="space-y-3 min-w-0">
        <Notice>Answers come only from this patient's uploaded records, assembled from stored findings and verbatim passages — no general medical knowledge is used. MedTrace abstains when evidence is missing, conflicting or ambiguous, and declines diagnosis or treatment questions.</Notice>
        <form className="flex gap-2" onSubmit={(e) => ask(q, e)}>
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} placeholder="Ask a factual question about the records…" aria-label="Question" />
          <button className="btn-primary" disabled={busy}>{busy ? "Searching…" : "Ask"}</button>
        </form>
        <div className="flex flex-wrap gap-1.5">{EXAMPLES.map((x) => <button key={x} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 hover:border-brand-300" onClick={() => { setQ(x); ask(x); }}>{x}</button>)}</div>
        {busy && <Spinner text="Retrieving evidence…" />}
        {err && <ErrorBox error={err} />}
        {ans && !busy && (
          <div className="card p-4 space-y-3">
            <div className="text-xs muted">Question</div>
            <div className="font-medium text-slate-900">{ans.question}</div>
            <div className="flex flex-wrap items-center gap-2"><Badge tone={STATUS_TONE(ans.retrieval_status)}>{label(ans.retrieval_status)}</Badge><span className="text-[11px] muted">intent: {label(ans.intent)} · methods: {ans.retrieval.methods.join(", ")} · {ans.retrieval.findings_considered} findings / {ans.retrieval.lines_searched} lines searched</span></div>
            <div className="text-[15px] text-slate-900">{ans.answer}</div>
            {ans.conflicts.length > 0 && (
              <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm">
                <div className="font-semibold text-red-800">Conflicting statements</div>
                {ans.conflicts.map((c) => (
                  <div key={c.conflict_id} className="mt-1">• {c.explanation}
                    <div className="grid md:grid-cols-2 gap-2 mt-1">{c.evidence.map((e) => <button key={e.finding_id} className="text-left rounded border border-red-100 bg-white p-2 text-xs hover:border-red-300" onClick={() => openEvidence(e.finding_id)}><b>{e.value}</b> — {e.document_filename}, p.{e.page}<div className="font-mono text-[11px]">“{e.passage}”</div></button>)}</div>
                  </div>
                ))}
              </div>
            )}
            {ans.uncertainty.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">{ans.uncertainty.map((u, i) => <div key={i}>⚠ {u}</div>)}</div>}
            {ans.facts.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-slate-500 mb-1">Documented facts ({ans.facts.length})</div>
                <ol className="space-y-1.5">{ans.facts.map((f, i) => (
                  <li key={i} className="rounded-md border border-slate-200 p-2 text-sm">
                    <div className="flex flex-wrap items-center gap-1.5"><span className="font-medium">{f.statement}</span>
                      <Badge tone={f.verification_status === "unverified" ? "amber" : "green"}>{label(f.verification_status)}</Badge>
                      {f.confidence_label === "low" && <Badge tone="red">low confidence</Badge>}</div>
                    {f.normalized && <div className="text-[11px] text-violet-700">{Object.entries(f.normalized).filter(([k]) => k !== "note").map(([k, v]) => `${label(k)}: ${v}`).join(" · ")} — {f.normalized.note}</div>}
                    <button className="mt-1 text-left text-xs text-slate-600 hover:text-brand-700" onClick={() => f.citation.finding_id && openEvidence(f.citation.finding_id)}>
                      [{f.citation.document_filename}, p.{f.citation.page}] <span className="font-mono">“{f.citation.passage}”</span>
                    </button>
                  </li>))}</ol>
              </div>
            )}
            {ans.related_passages.length > 0 && (
              <div>
                <div className="text-xs font-semibold text-slate-500 mb-1">Verbatim passages</div>
                {ans.related_passages.map((p, i) => <div key={i} className="text-xs"><Link className="text-brand-700 hover:underline" to={`/patients/${pid}/documents/${p.document_id}?page=${p.page}&line=${p.line}`}>[{p.document_filename}, p.{p.page}]</Link> <span className="font-mono">“{p.passage}”</span></div>)}
              </div>
            )}
            {ans.notes.length > 0 && <div className="text-xs text-slate-600 space-y-0.5">{ans.notes.map((n, i) => <div key={i}>ℹ {n}</div>)}</div>}
            <div className="text-[11px] text-slate-500 border-t border-slate-100 pt-2">{ans.boundary}</div>
          </div>
        )}
      </div>
      <div className="card p-3 h-fit">
        <div className="h2 mb-2">Your recent questions</div>
        {(history.data ?? []).length === 0 && <div className="text-xs muted">None yet.</div>}
        <ul className="space-y-1">{(history.data ?? []).map((h) => <li key={h.id}><button className="text-left text-xs hover:text-brand-700" onClick={() => open(h.id)}><Badge tone={STATUS_TONE(h.retrieval_status)}>{label(h.retrieval_status)}</Badge> {h.question}</button></li>)}</ul>
      </div>
    </div>
  );
}
