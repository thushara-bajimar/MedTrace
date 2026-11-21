import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../App";
import type { User } from "../types";

export default function LoginPage() {
  const { setUser } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setUser(await api.post<User>("/api/auth/login", { username, password }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="min-h-screen grid place-items-center bg-slate-100 px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2 mb-6 justify-center">
          <img src="/favicon.svg" alt="" className="h-9 w-9" />
          <div>
            <div className="text-lg font-semibold text-slate-900">MedTrace</div>
            <div className="text-xs text-slate-500">Every medical fact, traced to its source</div>
          </div>
        </div>
        <form onSubmit={submit} className="card p-5 space-y-3">
          <div>
            <label className="label" htmlFor="u">Username</label>
            <input id="u" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div>
            <label className="label" htmlFor="p">Password</label>
            <input id="p" type="password" className="input" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <div className="text-sm text-red-700">{error}</div>}
          <button className="btn-primary w-full justify-center" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        <p className="mt-4 text-center text-[11px] text-slate-500 leading-relaxed">
          Local MVP for synthetic records only. Not a diagnostic or clinical decision support system.
        </p>
      </div>
    </div>
  );
}
