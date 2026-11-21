import { useState } from "react";
import { api, P } from "../../api";
import { Badge, ConfidenceBadge, DateCell, Empty, ErrorBox, Spinner, fmtDateTime, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

interface Slim { id: string; finding_type: string; summary: string; document_filename: string; page_number: number; source_passage: string; date_text: string | null; date_status: string; confidence_label: string; confidence_score: number; confidence_reasons: string[]; verification_status: string; provenance_type: string }
interface Queue { unverified: Slim[]; low_confidence: Slim[]; date_ambiguities: Slim[]; duplicates_pending: unknown[]; conflicts_open: unknown[]; human_reviews: { finding_id: string; version: number; reason: string; created_at: string; reviewer: string; finding_type: string }[] }

export default function ReviewTab({ pid, refreshKey, openEvidence }: TabProps) {
  const { data, error, loading } = useAsync(() => api.get<Queue>(`${P(pid)}/review`), [pid, refreshKey]);
  const [tab, setTab] = useState<"low_confidence" | "date_ambiguities" | "unverified" | "human_reviews">("low_confidence");
  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorBox error={error ?? "failed"} />;
  const lists: [typeof tab, string, number][] = [
    ["low_confidence", "Low confidence", data.low_confidence.length],
    ["date_ambiguities", "Date ambiguities", data.date_ambiguities.length],
    ["unverified", "All unverified", data.unverified.length],
    ["human_reviews", "Human reviews & corrections", data.human_reviews.length],
  ];
  const items = tab === "human_reviews" ? [] : data[tab];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-6 gap-2 text-sm">
        {lists.map(([k, n, c]) => <button key={k} className={`card px-3 py-2 text-left ${tab === k ? "border-brand-500 ring-1 ring-brand-200" : ""}`} onClick={() => setTab(k)}><div className="text-xs muted">{n}</div><div className="text-lg font-semibold tabular-nums">{c}</div></button>)}
        <div className="card px-3 py-2"><div className="text-xs muted">Open conflicts</div><div className="text-lg font-semibold tabular-nums text-red-700">{data.conflicts_open.length}</div></div>
        <div className="card px-3 py-2"><div className="text-xs muted">Duplicates pending</div><div className="text-lg font-semibold tabular-nums">{data.duplicates_pending.length}</div></div>
      </div>
      <p className="text-xs muted">Machine-extracted findings remain “unverified” until a reviewer compares them with the source and verifies, corrects or rejects them. Click a row to open the evidence viewer.</p>
      {tab === "human_reviews" ? (
        <div className="card">{data.human_reviews.length === 0 ? <Empty>No human reviews yet.</Empty> : (
          <table className="w-full"><thead><tr>{["When", "Reviewer", "Finding", "Version", "Reason"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{data.human_reviews.map((h, i) => (
              <tr key={i} className="hover:bg-slate-50 cursor-pointer" onClick={() => openEvidence(h.finding_id)}>
                <td className="td text-xs">{fmtDateTime(h.created_at)}</td><td className="td">{h.reviewer}</td><td className="td"><Badge>{h.finding_type}</Badge></td><td className="td">v{h.version}</td><td className="td">{h.reason}</td>
              </tr>))}</tbody></table>)}
        </div>
      ) : (
        <div className="card overflow-x-auto">{items.length === 0 ? <Empty>Nothing in this queue.</Empty> : (
          <table className="w-full"><thead><tr>{["Finding", "Date", "Confidence", "Why", "Source passage", "Status"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{items.map((f) => (
              <tr key={f.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => openEvidence(f.id)}>
                <td className="td"><Badge>{f.finding_type}</Badge> <span className="font-medium">{f.summary}</span></td>
                <td className="td"><DateCell text={f.date_text} iso={null} status={f.date_status} /></td>
                <td className="td"><ConfidenceBadge label={f.confidence_label} score={f.confidence_score} reasons={f.confidence_reasons} /></td>
                <td className="td text-[11px] text-slate-600 max-w-[16rem]">{f.confidence_reasons.slice(1).join("; ")}</td>
                <td className="td text-xs"><span className="font-mono">“{f.source_passage}”</span><div className="muted">{f.document_filename} · p.{f.page_number}</div></td>
                <td className="td text-xs">{label(f.verification_status)}<div className="muted">{label(f.provenance_type)}</div></td>
              </tr>))}</tbody></table>)}
        </div>
      )}
    </div>
  );
}
