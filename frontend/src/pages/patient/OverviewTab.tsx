import { Link } from "react-router-dom";
import { api, P } from "../../api";
import type { Conflict, DocumentRow } from "../../types";
import { Badge, DateCell, Notice, Spinner, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

interface Gap { id: string; gap_type: string; description: string; document_filename: string | null; finding_id: string | null }

export default function OverviewTab({ pid, refreshKey, openEvidence }: TabProps) {
  const docs = useAsync(() => api.get<DocumentRow[]>(`${P(pid)}/documents`), [pid, refreshKey]);
  const conflicts = useAsync(() => api.get<Conflict[]>(`${P(pid)}/conflicts`), [pid, refreshKey]);
  const gaps = useAsync(() => api.get<Gap[]>(`${P(pid)}/gaps`), [pid, refreshKey]);
  if (docs.loading || conflicts.loading || gaps.loading) return <Spinner />;
  const gapCounts: Record<string, number> = {};
  (gaps.data ?? []).forEach((g) => (gapCounts[g.gap_type] = (gapCounts[g.gap_type] ?? 0) + 1));
  return (
    <div className="grid xl:grid-cols-[1.4fr_1fr] gap-4">
      <div className="space-y-4">
        <Notice>This overview organises what the uploaded records document. It is not a clinical summary: statuses such as “prescribed” or “suspected” are reported exactly as documented, and missing documentation is never treated as a negative finding.</Notice>
        <div className="card">
          <div className="h2 px-4 pt-4 pb-2">Documents (chronological by document date)</div>
          <table className="w-full">
            <thead><tr><th className="th">Document date</th><th className="th">Document</th><th className="th">Type</th><th className="th">Findings</th><th className="th">Flags</th></tr></thead>
            <tbody>
              {(docs.data ?? []).map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <td className="td"><DateCell text={d.document_date_text} iso={d.document_date_iso} status={d.document_date_status} /></td>
                  <td className="td"><Link className="text-brand-700 hover:underline" to={`/patients/${pid}/documents/${d.id}`}>{d.original_filename}</Link><div className="text-[11px] text-slate-500">{d.provider}</div></td>
                  <td className="td">{label(d.doc_type)}</td>
                  <td className="td tabular-nums">{d.findings_count}</td>
                  <td className="td space-x-1">
                    {d.conflicts_count > 0 && <Badge tone="red">{d.conflicts_count} conflict</Badge>}
                    {d.duplicate_flags.some((x) => x.kind !== "similar_distinct") && <Badge tone="amber">possible duplicate</Badge>}
                    {d.text_source_summary === "ocr" && <Badge tone="blue">OCR</Badge>}
                    {d.injection_flags && <Badge tone="violet" title="Instruction-like text was found and treated as data">instruction-like text</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="space-y-4">
        <div className="card p-4">
          <div className="flex items-center justify-between"><div className="h2">Contradictions</div><Link className="text-xs text-brand-700" to={`/patients/${pid}/conflicts`}>Open centre →</Link></div>
          {(conflicts.data ?? []).length === 0 ? <p className="text-sm muted mt-2">No contradictions detected.</p> : (
            <ul className="mt-2 space-y-2">{conflicts.data!.map((c) => (
              <li key={c.id} className="text-sm"><Badge tone="red">{label(c.category)}</Badge> <span className="ml-1">{c.explanation}</span> <Badge>{label(c.status)}</Badge></li>
            ))}</ul>
          )}
        </div>
        <div className="card p-4">
          <div className="h2">Documentation gaps</div>
          <p className="text-xs muted">Statements about what the records do not document — not about the patient.</p>
          <div className="mt-2 flex flex-wrap gap-1.5">{Object.entries(gapCounts).map(([k, v]) => <Badge key={k} tone="amber">{label(k)} · {v}</Badge>)}</div>
          <ul className="mt-3 space-y-1 max-h-72 overflow-y-auto text-sm">
            {(gaps.data ?? []).slice(0, 40).map((g) => (
              <li key={g.id} className="flex gap-2">
                <span className="text-slate-400">•</span>
                <span>{g.description} {g.document_filename && <span className="text-[11px] text-slate-500">({g.document_filename})</span>}
                  {g.finding_id && <button className="ml-1 text-[11px] text-brand-700 hover:underline" onClick={() => openEvidence(g.finding_id!)}>evidence</button>}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
