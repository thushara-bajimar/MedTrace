import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../App";
import type { Patient } from "../types";
import { Badge, Empty, ErrorBox, Spinner, useAsync } from "../components/ui";

export default function PatientsPage() {
  const { user } = useAuth();
  const nav = useNavigate();
  const { data, error, loading } = useAsync(() => api.get<Patient[]>("/api/patients"), []);
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({ display_name: "", synthetic_label: "", date_of_birth_text: "", sex: "" });
  const [err, setErr] = useState<string | null>(null);
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const p = await api.post<Patient>("/api/patients", form);
      nav(`/patients/${p.id}/documents`);
    } catch (e2) {
      setErr((e2 as Error).message);
    }
  };
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h1">Patients</h1>
          <p className="text-sm muted">Each patient has an isolated record space. Use synthetic patients only.</p>
        </div>
        {user?.role !== "viewer" && <button className="btn-primary" onClick={() => setShow(!show)}>New synthetic patient</button>}
      </div>
      {show && (
        <form onSubmit={create} className="card p-4 grid md:grid-cols-5 gap-3 items-end">
          <div className="md:col-span-2"><label className="label">Display name</label><input className="input" required value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="e.g. Test Patient (Synthetic)" /></div>
          <div><label className="label">Scenario label</label><input className="input" value={form.synthetic_label} onChange={(e) => setForm({ ...form, synthetic_label: e.target.value })} /></div>
          <div><label className="label">Birth year (text)</label><input className="input" value={form.date_of_birth_text} onChange={(e) => setForm({ ...form, date_of_birth_text: e.target.value })} /></div>
          <div className="flex gap-2"><button className="btn-primary">Create</button><button type="button" className="btn-secondary" onClick={() => setShow(false)}>Cancel</button></div>
          {err && <div className="md:col-span-5"><ErrorBox error={err} /></div>}
        </form>
      )}
      {loading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && (
        <div className="card overflow-hidden">
          {data.length === 0 ? <Empty>No patients visible to you.</Empty> : (
            <table className="w-full">
              <thead><tr><th className="th">Patient</th><th className="th">Scenario</th><th className="th">Documents</th><th className="th">Findings</th><th className="th">Unverified</th><th className="th">Conflicts</th><th className="th">Duplicates</th><th className="th">Gaps</th></tr></thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50">
                    <td className="td"><Link to={`/patients/${p.id}`} className="font-medium text-brand-700 hover:underline">{p.display_name}</Link>{p.is_synthetic ? <span className="ml-2"><Badge>synthetic</Badge></span> : null}</td>
                    <td className="td text-slate-600">{p.synthetic_label ?? "—"}</td>
                    <td className="td tabular-nums">{p.counts.documents}{p.counts.processing ? <span className="ml-1"><Badge tone="amber">{p.counts.processing} processing</Badge></span> : null}</td>
                    <td className="td tabular-nums">{p.counts.findings}</td>
                    <td className="td tabular-nums">{p.counts.unverified}</td>
                    <td className="td">{p.counts.conflicts_unresolved ? <Badge tone="red">{p.counts.conflicts_unresolved} open</Badge> : <span className="text-slate-400">0</span>}</td>
                    <td className="td">{p.counts.duplicates_pending ? <Badge tone="amber">{p.counts.duplicates_pending}</Badge> : <span className="text-slate-400">0</span>}</td>
                    <td className="td tabular-nums">{p.counts.gaps}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
