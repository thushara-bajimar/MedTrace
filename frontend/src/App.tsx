import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api";
import type { User } from "./types";
import { Spinner } from "./components/ui";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import PatientsPage from "./pages/PatientsPage";
import PatientWorkspace from "./pages/PatientWorkspace";
import DocumentViewer from "./pages/DocumentViewer";
import EvaluationPage from "./pages/EvaluationPage";
import StudyPage from "./pages/StudyPage";
import AdminPage from "./pages/AdminPage";

interface AuthCtx { user: User | null; setUser: (u: User | null) => void }
const Ctx = createContext<AuthCtx>({ user: null, setUser: () => {} });
export const useAuth = () => useContext(Ctx);

function Shell({ children }: { children: ReactNode }) {
  const { user, setUser } = useAuth();
  const nav = useNavigate();
  const logout = async () => {
    await api.post("/api/auth/logout").catch(() => {});
    setUser(null);
    nav("/login");
  };
  const link = ({ isActive }: { isActive: boolean }) =>
    `block rounded-md px-3 py-2 text-sm font-medium ${isActive ? "bg-brand-50 text-brand-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"}`;
  return (
    <div className="min-h-screen flex">
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-white flex flex-col">
        <div className="px-4 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <div>
              <div className="font-semibold text-slate-900 leading-tight">MedTrace</div>
              <div className="text-[10px] text-slate-500 leading-tight">Every medical fact, traced to its source</div>
            </div>
          </div>
        </div>
        <nav className="p-2 space-y-0.5 flex-1">
          <NavLink to="/" end className={link}>Dashboard</NavLink>
          <NavLink to="/patients" className={link}>Patients</NavLink>
          <NavLink to="/evaluation" className={link}>Evaluation</NavLink>
          <NavLink to="/study" className={link}>Review-time study</NavLink>
          {user?.role === "admin" && <NavLink to="/admin" className={link}>Users &amp; access</NavLink>}
        </nav>
        <div className="p-3 border-t border-slate-100 text-xs text-slate-500 space-y-2">
          <div>Signed in as <span className="font-medium text-slate-700">{user?.username}</span> ({user?.role})</div>
          <button className="btn-secondary w-full justify-center" onClick={logout}>Sign out</button>
          <p className="text-[10px] leading-snug">Records organisation only. MedTrace does not diagnose, interpret results clinically or recommend treatment.</p>
        </div>
      </aside>
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}

function Protected({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    api.get<User>("/api/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setReady(true));
    const onUnauth = () => setUser(null);
    window.addEventListener("medtrace:unauthorized", onUnauth);
    return () => window.removeEventListener("medtrace:unauthorized", onUnauth);
  }, []);
  if (!ready) return <Spinner text="Starting MedTrace…" />;
  return (
    <Ctx.Provider value={{ user, setUser }}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
          <Route path="/" element={<Protected><DashboardPage /></Protected>} />
          <Route path="/patients" element={<Protected><PatientsPage /></Protected>} />
          <Route path="/patients/:pid" element={<Protected><PatientWorkspace /></Protected>} />
          <Route path="/patients/:pid/:tab" element={<Protected><PatientWorkspace /></Protected>} />
          <Route path="/patients/:pid/documents/:did" element={<Protected><DocumentViewer /></Protected>} />
          <Route path="/evaluation" element={<Protected><EvaluationPage /></Protected>} />
          <Route path="/study" element={<Protected><StudyPage /></Protected>} />
          <Route path="/admin" element={<Protected><AdminPage /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </Ctx.Provider>
  );
}
