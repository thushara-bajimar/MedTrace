import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { Patient } from "../types";
import { Badge, ErrorBox, Notice, useAsync } from "../components/ui";

interface U { id: string; username: string; role: string; created_at: string; access: { patient_id: string; permission: string }[] }

export default function AdminPage() {
  const users = useAsync(() => api.get<U[]>("/api/users"), []);
  const patients = useAsync(() => api.get<Patient[]>("/api/patients"), []);
  const [form, setForm] = useState({ username: "", password: "", role: "reviewer" });
  const [err, setErr] = useState<string | null>(null);
  const create = async (e: FormEvent) => {
    e.preventDefault(); setErr(null);
    try { await api.post("/api/users", form); setForm({ username: "", password: "", role: "reviewer" }); users.reload(); } catch (x) { setErr((x as Error).message); }
  };
  const toggle = async (u: U, pid: string, has: boolean) => {
    if (has) await api.del(`/api/users/${u.id}/access/${pid}`);
    else await api.post(`/api/users/${u.id}/access`, { patient_id: pid, permission: u.role === "viewer" ? "read" : "write" });
    users.reload();
  };
  const name = (id: string) => (patients.data ?? []).find((p) => p.id === id)?.display_name ?? id;
  return (
    <div className="p-6 space-y-4">
      <div><h1 className="h1">Users &amp; patient access</h1><p className="text-sm muted">Patient isolation is enforced on the backend: non-admin users can only reach patients granted here.</p></div>
      <Notice>Roles: <b>admin</b> — all patients and user management; <b>reviewer</b> — read/write on granted patients; <b>viewer</b> — read-only on granted patients.</Notice>
      <form onSubmit={create} className="card p-4 flex flex-wrap items-end gap-3">
        <div><label className="label">Username</label><input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></div>
        <div><label className="label">Password (≥ 10 chars, mixed)</label><input className="input" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></div>
        <div><label className="label">Role</label><select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option>reviewer</option><option>viewer</option><option>admin</option></select></div>
        <button className="btn-primary">Create user</button>
        {err && <div className="w-full"><ErrorBox error={err} /></div>}
      </form>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm"><thead><tr><th className="th">User</th><th className="th">Role</th>{(patients.data ?? []).map((p) => <th key={p.id} className="th">{p.display_name.replace(/\s*\(Synthetic.*\)/, "")}</th>)}</tr></thead>
          <tbody>{(users.data ?? []).map((u) => (
            <tr key={u.id}><td className="td font-medium">{u.username}</td><td className="td"><Badge>{u.role}</Badge></td>
              {(patients.data ?? []).map((p) => {
                const has = u.access.some((a) => a.patient_id === p.id);
                return <td key={p.id} className="td">{u.role === "admin" ? <span className="text-xs muted">all</span> : <input type="checkbox" aria-label={`${u.username} access to ${name(p.id)}`} checked={has} onChange={() => toggle(u, p.id, has)} />}</td>;
              })}</tr>))}
          </tbody></table>
      </div>
    </div>
  );
}
