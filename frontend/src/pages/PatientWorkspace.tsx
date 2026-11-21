import { useState } from "react";
import { NavLink, useParams } from "react-router-dom";
import { api, P } from "../api";
import { useAuth } from "../App";
import type { Patient } from "../types";
import EvidenceDrawer from "../components/EvidenceDrawer";
import { Badge, ErrorBox, Spinner, useAsync } from "../components/ui";
import DocumentsTab from "./patient/DocumentsTab";
import TimelineTab from "./patient/TimelineTab";
import MedicationsTab from "./patient/MedicationsTab";
import AllergiesTab from "./patient/AllergiesTab";
import InvestigationsTab from "./patient/InvestigationsTab";
import ConditionsEventsTab from "./patient/ConditionsEventsTab";
import ConflictsTab from "./patient/ConflictsTab";
import DuplicatesTab from "./patient/DuplicatesTab";
import ReviewTab from "./patient/ReviewTab";
import AskTab from "./patient/AskTab";
import OverviewTab from "./patient/OverviewTab";

export interface TabProps { pid: string; canWrite: boolean; openEvidence: (findingId: string) => void; refreshKey: number; bump: () => void }

const TABS: [string, string, (p: TabProps) => JSX.Element][] = [
  ["overview", "Overview", OverviewTab],
  ["documents", "Documents", DocumentsTab],
  ["timeline", "Timeline", TimelineTab],
  ["medications", "Medications", MedicationsTab],
  ["allergies", "Allergies", AllergiesTab],
  ["investigations", "Investigations", InvestigationsTab],
  ["conditions", "Conditions & events", ConditionsEventsTab],
  ["conflicts", "Contradictions", ConflictsTab],
  ["duplicates", "Duplicates", DuplicatesTab],
  ["review", "Review centre", ReviewTab],
  ["ask", "Ask the records", AskTab],
];

export default function PatientWorkspace() {
  const { pid = "", tab = "overview" } = useParams();
  const { user } = useAuth();
  const [refreshKey, setRefreshKey] = useState(0);
  const [evidence, setEvidence] = useState<string | null>(null);
  const { data: p, error, loading } = useAsync(() => api.get<Patient>(P(pid)), [pid, refreshKey]);
  const canWrite = user?.role !== "viewer";
  const Comp = (TABS.find((t) => t[0] === tab) ?? TABS[0])[2];
  const props: TabProps = { pid, canWrite, openEvidence: setEvidence, refreshKey, bump: () => setRefreshKey((k) => k + 1) };
  if (loading && !p) return <Spinner />;
  if (error || !p) return <div className="p-6"><ErrorBox error={error ?? "Patient not found"} /></div>;
  return (
    <div>
      <div className="border-b border-slate-200 bg-white px-6 pt-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-xs text-slate-500">Patient record space</div>
            <h1 className="h1">{p.display_name} {p.is_synthetic ? <Badge>synthetic</Badge> : null}</h1>
            <div className="text-xs text-slate-500">{p.synthetic_label} {p.date_of_birth_text ? `· born ${p.date_of_birth_text}` : ""} {p.sex ? `· ${p.sex}` : ""}</div>
          </div>
          <div className="flex gap-2 text-xs">
            <Badge>{p.counts.documents} documents</Badge>
            <Badge tone="amber">{p.counts.unverified} unverified</Badge>
            <Badge tone={p.counts.conflicts_unresolved ? "red" : "gray"}>{p.counts.conflicts_unresolved} open conflicts</Badge>
            {p.counts.processing > 0 && <Badge tone="blue">{p.counts.processing} processing</Badge>}
          </div>
        </div>
        <nav className="mt-3 -mb-px flex gap-1 overflow-x-auto">
          {TABS.map(([key, name]) => (
            <NavLink key={key} to={`/patients/${pid}/${key}`} className={() => `tab ${tab === key ? "tab-active" : ""}`}>{name}</NavLink>
          ))}
        </nav>
      </div>
      <div className="p-6"><Comp {...props} /></div>
      {evidence && <EvidenceDrawer pid={pid} findingId={evidence} canWrite={canWrite} onClose={() => setEvidence(null)} onChanged={props.bump} />}
    </div>
  );
}
