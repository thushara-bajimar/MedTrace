import { Link } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Badge, ErrorBox, Spinner, Stat, fmtDateTime, label, useAsync } from "../components/ui";

interface Dash {
  patients: number; documents: number; documents_by_status: Record<string, number>; timeline_events: number; unverified_findings: number;
  conflicts_unresolved: number; duplicates_pending: number; gaps: number; findings_by_type: Record<string, number>;
  recent_uploads: { id: string; patient_id: string; patient_name: string; original_filename: string; doc_type: string; upload_date: string; extraction_status: string; ocr_status: string }[];
}

export default function DashboardPage() {
  const { data, error, loading } = useAsync(() => api.get<Dash>("/api/dashboard"), []);
  if (loading) return <Spinner />;
  if (error || !data) return <div className="p-6"><ErrorBox error={error ?? "Failed to load"} /></div>;
  const chart = Object.entries(data.findings_by_type).map(([k, v]) => ({ type: k, count: v }));
  const processing = (data.documents_by_status.pending ?? 0) + (data.documents_by_status.processing ?? 0);
  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="h1">Dashboard</h1>
        <p className="text-sm muted">Across all patients you can access.</p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Stat label="Patients" value={data.patients} />
        <Stat label="Documents" value={data.documents} hint={`${data.documents_by_status.completed ?? 0} processed`} />
        <Stat label="Processing" value={processing} hint={`${data.documents_by_status.failed ?? 0} failed`} tone={data.documents_by_status.failed ? "red" : undefined} />
        <Stat label="Timeline entries" value={data.timeline_events} tone="teal" />
        <Stat label="Unverified findings" value={data.unverified_findings} tone="amber" hint="machine extracted" />
        <Stat label="Open conflicts" value={data.conflicts_unresolved} tone={data.conflicts_unresolved ? "red" : undefined} />
        <Stat label="Possible duplicates" value={data.duplicates_pending} hint="documents, pending review" />
        <Stat label="Documentation gaps" value={data.gaps} />
      </div>
      <div className="grid lg:grid-cols-[1fr_1.6fr] gap-4">
        <div className="card p-4">
          <div className="h2 mb-2">Findings by type</div>
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ left: -20 }}>
                <XAxis dataKey="type" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#1f8a83" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card">
          <div className="h2 px-4 pt-4 pb-2">Recent uploads</div>
          <table className="w-full">
            <thead><tr><th className="th">Document</th><th className="th">Patient</th><th className="th">Type</th><th className="th">Status</th><th className="th">Uploaded</th></tr></thead>
            <tbody>
              {data.recent_uploads.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <td className="td"><Link className="text-brand-700 hover:underline" to={`/patients/${d.patient_id}/documents/${d.id}`}>{d.original_filename}</Link></td>
                  <td className="td">{d.patient_name}</td>
                  <td className="td">{label(d.doc_type)}</td>
                  <td className="td"><Badge tone={d.extraction_status === "completed" ? "green" : d.extraction_status === "failed" ? "red" : "amber"}>{d.extraction_status}</Badge> {d.ocr_status !== "not_required" && <Badge tone="blue">OCR {d.ocr_status}</Badge>}</td>
                  <td className="td text-xs text-slate-500">{fmtDateTime(d.upload_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
