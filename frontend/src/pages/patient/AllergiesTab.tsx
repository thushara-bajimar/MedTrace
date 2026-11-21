import { api, P } from "../../api";
import type { Conflict } from "../../types";
import { Badge, DateCell, Empty, ErrorBox, Notice, Spinner, VerificationBadge, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

interface Statement { finding_id: string; assertion: string; assertion_label: string; substance: string | null; reaction: string | null; severity: string | null; date_text: string | null; date_iso: string | null; document_filename: string; document_type: string; page: number; passage: string; verification_status: string; conflict_ids: string[] }
interface Summary { statements: Statement[]; per_document: { document_id: string; document_filename: string; document_type: string; document_date_text: string | null; allergy_documentation: string }[]; conflicts: Conflict[]; note: string }

const A_TONE: Record<string, string> = { documented_allergy: "red", explicitly_denied_general: "green", explicitly_denied_specific: "green", status_not_recorded: "amber" };
const DOC_LABEL: Record<string, [string, string]> = {
  allergy_documented: ["Allergy documented", "red"], explicit_negative: ["Explicit negative", "green"],
  not_documented: ["Not documented", "gray"], status_not_recorded: ["Status explicitly not recorded", "amber"],
};

export default function AllergiesTab({ pid, refreshKey, openEvidence }: TabProps) {
  const { data, error, loading } = useAsync(() => api.get<Summary>(`${P(pid)}/allergies`), [pid, refreshKey]);
  if (loading && !data) return <Spinner />;
  if (error || !data) return <ErrorBox error={error ?? "failed"} />;
  return (
    <div className="space-y-4">
      <Notice>{data.note}</Notice>
      {data.conflicts.length > 0 && (
        <div className="card border-red-200 p-4">
          <div className="h2 text-red-800">Conflicting allergy statements ({data.conflicts.length})</div>
          <p className="text-xs muted">Shown side by side. MedTrace does not decide which statement is correct.</p>
          <ul className="mt-2 space-y-1 text-sm">{data.conflicts.map((c) => <li key={c.id}>• {c.explanation} <Badge>{label(c.status)}</Badge></li>)}</ul>
        </div>
      )}
      <div className="grid xl:grid-cols-[1.5fr_1fr] gap-4">
        <div className="card overflow-x-auto">
          <div className="h2 px-4 pt-4 pb-2">Allergy statements</div>
          {data.statements.length === 0 ? <Empty>No allergy statements in the records. This is not evidence of no allergies.</Empty> : (
            <table className="w-full">
              <thead><tr>{["Statement", "Substance", "Reaction", "Severity", "Record date", "Source", "Verification"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{data.statements.map((s) => (
                <tr key={s.finding_id} className="hover:bg-slate-50 cursor-pointer" onClick={() => openEvidence(s.finding_id)}>
                  <td className="td"><Badge tone={A_TONE[s.assertion]}>{s.assertion_label}</Badge>{s.conflict_ids.length > 0 && <Badge tone="red">conflict</Badge>}</td>
                  <td className="td font-medium">{s.substance ?? <span className="text-slate-500 italic">(no substance – general statement)</span>}</td>
                  <td className="td">{s.reaction ?? <span className="text-slate-400 italic">not documented</span>}</td>
                  <td className="td">{s.severity ?? <span className="text-slate-400 italic">not documented</span>}</td>
                  <td className="td"><DateCell text={s.date_text} iso={s.date_iso} status="document_date" /></td>
                  <td className="td text-xs">{s.document_filename}<div className="text-slate-500 font-mono">“{s.passage}”</div></td>
                  <td className="td"><VerificationBadge status={s.verification_status} /></td>
                </tr>))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <div className="h2 px-4 pt-4 pb-2">Allergy documentation per document</div>
          <table className="w-full">
            <tbody>{data.per_document.map((d) => (
              <tr key={d.document_id}><td className="td text-xs">{d.document_filename}<div className="text-slate-500">{label(d.document_type)} · {d.document_date_text ?? "undated"}</div></td>
                <td className="td text-right"><Badge tone={DOC_LABEL[d.allergy_documentation][1]}>{DOC_LABEL[d.allergy_documentation][0]}</Badge></td></tr>))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
