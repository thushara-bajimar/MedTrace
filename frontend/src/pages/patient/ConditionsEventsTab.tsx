import { api, P } from "../../api";
import type { Finding } from "../../types";
import { Badge, DateCell, Empty, ErrorBox, Notice, Spinner, VerificationBadge, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

const C_TONE: Record<string, string> = { confirmed_as_documented: "violet", suspected: "amber", possible: "amber", ruled_out: "green", history_of: "gray", known_case: "violet", explicitly_denied: "green" };

export default function ConditionsEventsTab({ pid, refreshKey, openEvidence }: TabProps) {
  const conds = useAsync(() => api.get<Finding[]>(`${P(pid)}/conditions`), [pid, refreshKey]);
  const events = useAsync(() => api.get<Finding[]>(`${P(pid)}/events`), [pid, refreshKey]);
  if ((conds.loading && !conds.data) || (events.loading && !events.data)) return <Spinner />;
  if (conds.error || events.error) return <ErrorBox error={(conds.error || events.error)!} />;
  return (
    <div className="grid xl:grid-cols-2 gap-4">
      <div className="space-y-2">
        <Notice>Conditions exactly as documented. Qualifiers such as <i>suspected</i>, <i>possible</i>, <i>ruled out</i> and <i>history of</i> are preserved and never upgraded to a diagnosis. MedTrace never infers a condition from results.</Notice>
        <div className="card overflow-x-auto">
          {(conds.data ?? []).length === 0 ? <Empty>No condition statements.</Empty> : (
            <table className="w-full"><thead><tr>{["Condition (as written)", "Documented status", "Date", "Source", "Verification"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{conds.data!.map((f) => (
                <tr key={f.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => openEvidence(f.id)}>
                  <td className="td font-medium">{String(f.details.name_as_written)}{f.details.normalized_name ? <div className="text-[11px] text-violet-600">normalised: {String(f.details.normalized_name)}</div> : null}</td>
                  <td className="td"><Badge tone={C_TONE[String(f.details.status_as_documented)]}>{label(String(f.details.status_as_documented))}</Badge></td>
                  <td className="td"><DateCell text={f.date_text} iso={f.date_iso} status={f.date_status} /></td>
                  <td className="td text-xs">{f.document_filename}<div className="text-slate-500">{f.document_date_text ?? "undated"} · p.{f.page_number}</div></td>
                  <td className="td"><VerificationBadge status={f.verification_status} /></td>
                </tr>))}</tbody></table>
          )}
        </div>
      </div>
      <div className="space-y-2">
        <Notice>Documented events. Relative follow-up intervals (e.g. “after 2 weeks”) are kept as text and not converted to dates.</Notice>
        <div className="card overflow-x-auto">
          {(events.data ?? []).length === 0 ? <Empty>No events.</Empty> : (
            <table className="w-full"><thead><tr>{["Date", "Event", "Description", "Source", "Verification"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>{events.data!.map((f) => (
                <tr key={f.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => openEvidence(f.id)}>
                  <td className="td"><DateCell text={f.date_text} iso={f.date_iso} status={f.date_status} candidates={f.date_candidates} /></td>
                  <td className="td"><Badge>{label(String(f.details.event_type))}</Badge></td>
                  <td className="td">{String(f.details.description)}</td>
                  <td className="td text-xs">{f.document_filename}<div className="text-slate-500">p.{f.page_number}</div></td>
                  <td className="td"><VerificationBadge status={f.verification_status} /></td>
                </tr>))}</tbody></table>
          )}
        </div>
      </div>
    </div>
  );
}
