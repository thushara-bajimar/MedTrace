import { api, P } from "../../api";
import { Badge, DateCell, Empty, ErrorBox, Notice, Spinner, VerificationBadge, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

interface Mention {
  finding_id: string; name_as_written: string; normalized_name: string | null; strength: string | null; dosage: string | null; route: string | null;
  frequency: string | null; duration: string | null; start_date_text: string | null; stop_date_text: string | null; status: string; status_label: string;
  date_text: string | null; date_iso: string | null; date_status: string; date_kind: string; document_filename: string; document_type: string; page: number;
  passage: string; verification_status: string; confidence_label: string; conflict_ids: string[];
}
interface Med { medication: string; mentions: Mention[]; documented_changes: { finding_id: string; kind: string; date_text: string | null; passage: string; previous?: string; current?: string }[]; latest_documented_status: string; latest_documented_date: string | null; current_status_note: string }

const STATUS_TONE: Record<string, string> = { prescribed: "teal", documented_ongoing: "green", documented_stopped: "red", documented_changed: "blue", historical: "gray", uncertain: "amber", mentioned_only: "gray", unknown: "gray" };
const ND = () => <span className="text-slate-400 italic">not documented</span>;

export default function MedicationsTab({ pid, refreshKey, openEvidence }: TabProps) {
  const { data, error, loading } = useAsync(() => api.get<{ medications: Med[] }>(`${P(pid)}/medications`), [pid, refreshKey]);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  const meds = data?.medications ?? [];
  return (
    <div className="space-y-4">
      <Notice tone="warn">Medication <b>mentions</b> as documented. A mention or prescription does not establish that the medication is currently taken; MedTrace only reports “ongoing” where a record explicitly says so, as of that record's date. Stop dates and doses are never inferred.</Notice>
      {meds.length === 0 && <div className="card"><Empty>No medication mentions extracted.</Empty></div>}
      {meds.map((m) => (
        <div key={m.medication} className="card">
          <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
            <div className="h2 capitalize">{m.medication}</div>
            <span className="text-xs muted">{m.mentions.length} mention(s) · latest documented: {m.latest_documented_status} ({m.latest_documented_date ?? "date not documented"})</span>
            {m.documented_changes.length > 0 && <Badge tone="blue">{m.documented_changes.length} documented change/stop</Badge>}
            {m.mentions.some((x) => x.conflict_ids.length) && <Badge tone="red">conflict</Badge>}
          </div>
          <div className="px-4 pb-1 text-[11px] text-slate-500">{m.current_status_note}</div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[60rem]">
              <thead><tr>{["Date", "As written", "Strength", "Dosage", "Route", "Frequency", "Duration", "Status", "Source", "Verification"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>
                {m.mentions.map((x) => (
                  <tr key={x.finding_id} className="hover:bg-slate-50 cursor-pointer" onClick={() => openEvidence(x.finding_id)}>
                    <td className="td"><DateCell text={x.date_text} iso={x.date_iso} status={x.date_status} />{x.stop_date_text && <div className="text-[11px] text-red-700">stop: {x.stop_date_text}</div>}{x.start_date_text && <div className="text-[11px]">start: {x.start_date_text}</div>}</td>
                    <td className="td font-medium">{x.name_as_written}</td>
                    <td className="td">{x.strength ?? <ND />}</td>
                    <td className="td">{x.dosage ?? <ND />}</td>
                    <td className="td">{x.route ?? <ND />}</td>
                    <td className="td">{x.frequency ?? <ND />}</td>
                    <td className="td">{x.duration ?? <ND />}</td>
                    <td className="td"><Badge tone={STATUS_TONE[x.status]}>{x.status_label}</Badge>{x.conflict_ids.length > 0 && <Badge tone="red">conflict</Badge>}</td>
                    <td className="td text-xs">{x.document_filename}<div className="text-slate-500">{label(x.document_type)} · p.{x.page}</div></td>
                    <td className="td"><VerificationBadge status={x.verification_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
