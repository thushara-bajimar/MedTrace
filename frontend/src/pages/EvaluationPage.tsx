import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { useAuth } from "../App";
import { Badge, ErrorBox, Notice, Spinner, Stat, fmtDateTime, useAsync } from "../components/ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
type M = any;
const pct = (x: number | null | undefined) => (x == null ? "—" : `${(x * 100).toFixed(1)}%`);
const SERIES_1 = "#2a78d6"; // categorical slot 1 (validated default palette)
const SERIES_2 = "#eb6834"; // categorical slot 2

function PRTable({ entity, micro }: { entity: Record<string, M>; micro: M }) {
  return (
    <table className="w-full text-sm">
      <thead><tr>{["Type", "Precision", "Recall", "F1", "TP", "FP", "FN"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
      <tbody>
        {Object.entries(entity).map(([k, v]) => <tr key={k}><td className="td capitalize">{k}</td><td className="td tabular-nums">{pct(v.precision)}</td><td className="td tabular-nums">{pct(v.recall)}</td><td className="td tabular-nums font-medium">{pct(v.f1)}</td><td className="td tabular-nums">{v.tp}</td><td className="td tabular-nums">{v.fp}</td><td className="td tabular-nums">{v.fn}</td></tr>)}
        <tr className="bg-slate-50 font-semibold"><td className="td">Micro (all)</td><td className="td">{pct(micro.precision)}</td><td className="td">{pct(micro.recall)}</td><td className="td">{pct(micro.f1)}</td><td className="td">{micro.tp}</td><td className="td">{micro.fp}</td><td className="td">{micro.fn}</td></tr>
      </tbody>
    </table>
  );
}

export default function EvaluationPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api.get<{ created_at: string; duration_ms: number; metrics_json: M }>("/api/evaluation/latest"), []);
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const run = async () => {
    setRunning(true); setRunErr(null);
    try { await api.post("/api/evaluation/run"); reload(); } catch (e) { setRunErr((e as Error).message); } finally { setRunning(false); }
  };
  const header = (
    <div className="flex items-end justify-between">
      <div><h1 className="h1">Evaluation</h1><p className="text-sm muted">Measured against hand-written ground truth for the synthetic dataset. Run in an isolated temporary database.</p></div>
      {user?.role === "admin" && <button className="btn-primary" disabled={running} onClick={run}>{running ? "Running (≈1 min)…" : "Run evaluation"}</button>}
    </div>
  );
  if (loading) return <div className="p-6">{header}<Spinner /></div>;
  if (error || !data) return <div className="p-6 space-y-3">{header}<ErrorBox error={error ?? "No evaluation yet"} />{runErr && <ErrorBox error={runErr} />}</div>;
  const m = data.metrics_json;
  const ex = m.extraction;
  const f1Data = Object.entries(ex.entity).map(([k, v]: [string, M]) => ({ type: k, f1: +(v.f1 * 100).toFixed(1) }));
  const fieldRows: [string, string, M][] = [];
  Object.entries(ex.fields).forEach(([t, fs]: [string, M]) => Object.entries(fs).forEach(([k, v]) => fieldRows.push([t, k, v])));
  const rv = m.review_time;
  const rvData = rv.per_patient.map((p: M) => ({ patient: p.patient, "Raw documents (est.)": p.baseline_seconds_estimate, "MedTrace (est.)": p.medtrace_seconds_estimate }));
  const splits = m.extraction_by_split;
  return (
    <div className="p-6 space-y-5">
      {header}
      {runErr && <ErrorBox error={runErr} />}
      <div className="text-xs muted">Last run {fmtDateTime(data.created_at)} · {(data.duration_ms / 1000).toFixed(1)} s · extractor {m.extractor_version} · dataset {m.dataset.version}: {m.dataset.patients} synthetic patients, {m.dataset.documents} documents, {m.dataset.ground_truth_findings} annotated findings, {m.dataset.questions} questions · hold-out patient(s): {m.dataset.holdout_patients.join(", ")}</div>
      <Notice tone="warn">Rules were developed while viewing the development patients (A–E), so development scores are optimistic. Hold-out patient F was never used to tune rules and is the fairer — but very small — estimate. Ground truth was authored by the developer, not independent clinicians.</Notice>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Stat label="Extraction F1 (all)" value={pct(ex.micro.f1)} tone="teal" />
        <Stat label="F1 dev / hold-out" value={`${pct(splits.development.micro.f1)} / ${pct(splits.holdout.micro.f1)}`} />
        <Stat label="Evidence passage acc." value={pct(ex.evidence.passage_accuracy)} />
        <Stat label="Page reference acc." value={pct(ex.evidence.page_reference_accuracy)} />
        <Stat label="Timeline ordering" value={pct(m.timeline.pairwise_ordering_accuracy)} />
        <Stat label="Conflict recall" value={pct(m.conflicts.recall)} hint={`precision ${pct(m.conflicts.precision)}`} />
        <Stat label="QA abstention acc." value={pct(m.qa.abstention_accuracy)} hint={`unsupported answers ${pct(m.qa.unsupported_answer_rate)}`} />
        <Stat label="OCR char. error rate" value={pct(m.ocr.mean_character_error_rate)} />
      </div>
      <div className="grid xl:grid-cols-[1fr_1.3fr] gap-4">
        <div className="card p-4">
          <div className="h2">F1 by finding type</div>
          <div className="h-60 mt-2">
            <ResponsiveContainer>
              <BarChart data={f1Data} margin={{ left: -16 }}>
                <CartesianGrid vertical={false} stroke="#eef0f2" />
                <XAxis dataKey="type" tick={{ fontSize: 11, fill: "#475569" }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} unit="%" />
                <Tooltip formatter={(v: number) => `${v}%`} cursor={{ fill: "#f1f5f9" }} />
                <Bar dataKey="f1" name="F1" fill={SERIES_1} radius={[4, 4, 0, 0]} maxBarSize={36} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card p-4"><div className="h2 mb-2">Entity detection (all documents)</div><PRTable entity={ex.entity} micro={ex.micro} /></div>
      </div>
      <div className="grid xl:grid-cols-3 gap-4">
        <div className="card p-4 xl:col-span-1">
          <div className="h2 mb-2">Attribute accuracy (matched findings)</div>
          <table className="w-full text-sm"><tbody>{fieldRows.map(([t, k, v]) => <tr key={t + k}><td className="td capitalize">{t}</td><td className="td">{k.replace(/_/g, " ")}</td><td className="td tabular-nums text-right">{v.correct}/{v.total}</td><td className="td tabular-nums text-right font-medium">{pct(v.accuracy)}</td></tr>)}</tbody></table>
        </div>
        <div className="card p-4 space-y-1 text-sm">
          <div className="h2 mb-2">Evidence & timeline</div>
          <div>Evidence completeness (verbatim span present on cited page): <b>{pct(ex.evidence.evidence_completeness)}</b></div>
          <div>Document classification: <b>{pct(ex.document_classification_accuracy)}</b> · document date: <b>{pct(ex.document_date_accuracy)}</b></div>
          <div>Event date accuracy: <b>{pct(m.timeline.event_date_accuracy)}</b> ({m.timeline.dated_items_evaluated} items)</div>
          <div>Pairwise ordering: <b>{pct(m.timeline.pairwise_ordering_accuracy)}</b> ({m.timeline.ordering_pairs} pairs)</div>
          <div>Medication chronology: <b>{pct(m.timeline.medication_chronology_accuracy)}</b></div>
          <div>Historical/current status: <b>{pct(m.timeline.historical_current_status_accuracy)}</b></div>
          <div>No fabricated dates for undated/ambiguous items: <b>{pct(m.timeline.missing_or_ambiguous_date_handling)}</b> ({m.timeline.missing_or_ambiguous_items})</div>
          <div className="pt-2 h2">Duplicates</div>
          <div>Precision {pct(m.duplicates.precision)} · recall {pct(m.duplicates.recall)} · false-positive rate {pct(m.duplicates.false_positive_rate)} · kind accuracy {pct(m.duplicates.kind_accuracy_on_labelled_pairs)}</div>
        </div>
        <div className="card p-4 space-y-1 text-sm">
          <div className="h2 mb-2">Contradictions & QA</div>
          <div>Conflicts: precision {pct(m.conflicts.precision)}, recall {pct(m.conflicts.recall)} (dev {m.conflicts.development_recall.detected}/{m.conflicts.development_recall.total}, hold-out {m.conflicts.holdout_recall.detected}/{m.conflicts.holdout_recall.total}); auto-resolved: 0</div>
          {m.conflicts.missed_conflicts.length > 0 && <div className="text-xs text-red-700">Missed: {m.conflicts.missed_conflicts.map((c: M) => `${c[0]} ${c[1].join("–")}`).join("; ")}</div>}
          <div>QA overall {pct(m.qa.overall_accuracy)} (dev {pct(m.qa.development_accuracy)}, hold-out {pct(m.qa.holdout_accuracy)})</div>
          <div>Evidence-supported answers {pct(m.qa.evidence_supported_answer_accuracy)} · citation accuracy {pct(m.qa.citation_accuracy)}</div>
          <div>Abstention accuracy {pct(m.qa.abstention_accuracy)} · unsupported-answer rate {pct(m.qa.unsupported_answer_rate)} · over-abstention {pct(m.qa.over_abstention_rate)}</div>
          <div>Cross-patient citations: {pct(m.qa.cross_patient_citation_rate)}</div>
          <div className="pt-2 h2">Latency (this machine)</div>
          <div>Native PDF median {m.latency.native_ms_median} ms · OCR median {m.latency.ocr_ms_median} ms</div>
        </div>
      </div>
      <div className="card p-4">
        <div className="flex items-center gap-2"><div className="h2">Review time — automated reading-load estimate</div><Badge tone="amber">not a human study</Badge></div>
        <p className="text-xs muted">Counts words a reviewer would read (all raw document text vs. structured findings) with stated assumptions: {rv.assumptions.reading_wpm} wpm, {rv.assumptions.seconds_per_document_open}s per document opened, {rv.assumptions.seconds_per_fact_check}s per spot-checked fact ({rv.assumptions.fact_spot_check_share * 100}% of facts). Estimated reduction {pct(rv.estimated_reduction)}. Real timed sessions: {rv.human_sessions_recorded} (see Review-time study).</p>
        <div className="h-64 mt-2">
          <ResponsiveContainer>
            <BarChart data={rvData} margin={{ left: -10 }} barGap={2}>
              <CartesianGrid vertical={false} stroke="#eef0f2" />
              <XAxis dataKey="patient" tick={{ fontSize: 11, fill: "#475569" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} unit="s" />
              <Tooltip formatter={(v: number) => `${v} s`} cursor={{ fill: "#f1f5f9" }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Raw documents (est.)" fill={SERIES_1} radius={[4, 4, 0, 0]} maxBarSize={28} />
              <Bar dataKey="MedTrace (est.)" fill={SERIES_2} radius={[4, 4, 0, 0]} maxBarSize={28} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="card overflow-x-auto">
        <div className="h2 px-4 pt-4 pb-2">Records-only questions ({m.qa.questions})</div>
        <table className="w-full text-sm"><thead><tr>{["Pt", "Question", "Expected", "Got", "Status", "Citations", "Correct"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{m.qa.results.map((r: M, i: number) => (
            <tr key={i}><td className="td">{r.patient}</td><td className="td">{r.question}</td><td className="td">{r.expected}</td><td className="td">{r.got}</td><td className="td text-xs">{r.status}</td><td className="td text-xs">{r.cited.join(", ")}</td><td className="td">{r.correct ? <Badge tone="green">yes</Badge> : <Badge tone="red">no</Badge>}</td></tr>))}</tbody></table>
      </div>
      <div className="card overflow-x-auto">
        <div className="h2 px-4 pt-4 pb-2">Error listing</div>
        <table className="w-full text-sm"><thead><tr>{["Doc", "Type", "Item", "Field", "Expected", "Got"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{ex.errors.map((e: M, i: number) => <tr key={i}><td className="td">{e.doc}</td><td className="td">{e.type}</td><td className="td">{e.item}</td><td className="td">{e.field}</td><td className="td text-xs">{String(e.expected ?? "")}</td><td className="td text-xs">{String(e.got ?? "")}</td></tr>)}</tbody></table>
      </div>
    </div>
  );
}
