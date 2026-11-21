import { useEffect, useState } from "react";
import { api } from "../api";
import type { Patient } from "../types";
import { Badge, ErrorBox, Notice, fmtDateTime, label, useAsync } from "../components/ui";

interface Session { id: string; patient_id: string; mode: string; participant_kind: string; started_at: string; finished_at: string | null; duration_seconds: number | null; tasks_total: number; tasks_correct: number | null; missed_findings: number | null; corrections_made: number | null }

export default function StudyPage() {
  const patients = useAsync(() => api.get<Patient[]>("/api/patients"), []);
  const sessions = useAsync(() => api.get<Session[]>("/api/review-sessions"), []);
  const [pid, setPid] = useState("");
  const [mode, setMode] = useState<"baseline_raw_documents" | "medtrace">("baseline_raw_documents");
  const [active, setActive] = useState<{ id: string; tasks: string[]; started: number } | null>(null);
  const [answers, setAnswers] = useState({ medications: "", allergies: "", last_lab_date: "", conflicts: "" });
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!active) return; const t = setInterval(() => setElapsed(Math.round((Date.now() - active.started) / 1000)), 1000); return () => clearInterval(t); }, [active]);

  const start = async () => {
    setErr(null); setResult(null);
    try { const s = await api.post<{ id: string; tasks: string[] }>("/api/review-sessions", { patient_id: pid, mode }); setActive({ ...s, started: Date.now() }); }
    catch (e) { setErr((e as Error).message); }
  };
  const finish = async () => {
    if (!active) return;
    const r = await api.post<{ duration_seconds: number; correct: number; missed: number; missed_items: string[] }>(`/api/review-sessions/${active.id}/finish`, { answers });
    setResult(`Recorded: ${r.duration_seconds.toFixed(0)} s · ${r.correct}/2 auto-scored tasks fully correct · missed items: ${r.missed_items.join(", ") || "none"}`);
    setActive(null); setAnswers({ medications: "", allergies: "", last_lab_date: "", conflicts: "" }); sessions.reload();
  };
  return (
    <div className="p-6 space-y-4">
      <div><h1 className="h1">Review-time study</h1><p className="text-sm muted">Record real, timed reviewer sessions to compare reading raw documents (baseline) against using MedTrace.</p></div>
      <Notice tone="warn">No human study results are reported by the project unless sessions are recorded here. The Evaluation page's review-time chart is an automated estimate, clearly labelled as such.</Notice>
      <div className="card p-4 space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div><label className="label">Patient</label><select className="input" value={pid} onChange={(e) => setPid(e.target.value)} disabled={!!active}><option value="">Select…</option>{(patients.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}</select></div>
          <div><label className="label">Condition</label><select className="input" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)} disabled={!!active}><option value="baseline_raw_documents">Baseline: raw documents only</option><option value="medtrace">MedTrace: timeline + evidence viewer</option></select></div>
          {!active ? <button className="btn-primary" disabled={!pid} onClick={start}>Start timer</button> : <div className="text-2xl font-semibold tabular-nums">{elapsed}s</div>}
        </div>
        {err && <ErrorBox error={err} />}
        {active && (
          <div className="space-y-2">
            <p className="text-xs muted">{mode === "baseline_raw_documents" ? "Open only the original documents (Download original / page images). Do not use the structured tabs." : "Use the timeline, medication and allergy tabs and the evidence viewer."}</p>
            {([["medications", 0], ["allergies", 1], ["last_lab_date", 2], ["conflicts", 3]] as const).map(([k, i]) => (
              <div key={k}><label className="label">{active.tasks[i]}</label><textarea className="input h-16" value={answers[k]} onChange={(e) => setAnswers({ ...answers, [k]: e.target.value })} /></div>
            ))}
            <button className="btn-primary" onClick={finish}>Stop timer &amp; submit</button>
          </div>
        )}
        {result && <Notice>{result}</Notice>}
      </div>
      <div className="card overflow-x-auto">
        <div className="h2 px-4 pt-4 pb-2">Recorded sessions</div>
        <table className="w-full text-sm"><thead><tr>{["Started", "Patient", "Condition", "Participant", "Duration", "Correct", "Missed"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>{(sessions.data ?? []).map((s) => (
            <tr key={s.id}><td className="td text-xs">{fmtDateTime(s.started_at)}</td><td className="td text-xs">{(patients.data ?? []).find((p) => p.id === s.patient_id)?.display_name ?? s.patient_id}</td>
              <td className="td"><Badge>{label(s.mode)}</Badge></td><td className="td">{s.participant_kind}</td><td className="td tabular-nums">{s.duration_seconds != null ? `${s.duration_seconds.toFixed(0)} s` : "in progress"}</td>
              <td className="td tabular-nums">{s.tasks_correct ?? "—"}</td><td className="td tabular-nums">{s.missed_findings ?? "—"}</td></tr>))}
          </tbody></table>
      </div>
    </div>
  );
}
