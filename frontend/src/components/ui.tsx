import { useCallback, useEffect, useState, type ReactNode } from "react";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);
  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    run().then(setData).catch((e: Error) => setError(e.message)).finally(() => setLoading(false));
  }, [run]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

const TONES: Record<string, string> = {
  gray: "bg-slate-100 text-slate-700 ring-slate-200",
  green: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-800 ring-red-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
  teal: "bg-brand-50 text-brand-800 ring-brand-200",
  violet: "bg-violet-50 text-violet-800 ring-violet-200",
};

export function Badge({ children, tone = "gray", title }: { children: ReactNode; tone?: keyof typeof TONES | string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap ${TONES[tone] ?? TONES.gray}`}>
      {children}
    </span>
  );
}

export const label = (s: string | null | undefined) => (s ? s.replace(/_/g, " ") : "—");

export function VerificationBadge({ status }: { status: string }) {
  const tone = status === "human_verified" ? "green" : status === "corrected" ? "blue" : status === "rejected" ? "red" : "amber";
  const text = status === "unverified" ? "machine extracted · unverified" : label(status);
  return <Badge tone={tone}>{text}</Badge>;
}

export function ConfidenceBadge({ label: l, score, reasons }: { label: string; score?: number; reasons?: string[] }) {
  const tone = l === "high" ? "teal" : l === "medium" ? "amber" : "red";
  const title = `Extraction confidence ${score?.toFixed(2) ?? ""} - a heuristic score, not a guarantee of correctness.${reasons?.length ? "\n• " + reasons.join("\n• ") : ""}`;
  return <Badge tone={tone} title={title}>{l} conf.</Badge>;
}

export function DateCell({ text, iso, status, candidates }: { text: string | null; iso: string | null; status: string; candidates?: string[] | null }) {
  if (!text && !iso) return <span className="text-slate-400 italic">date not documented</span>;
  return (
    <span className="whitespace-nowrap">
      <span className="font-medium text-slate-800">{text ?? iso}</span>
      {status === "ambiguous" && (
        <Badge tone="red" title={candidates?.length ? `Possible readings: ${candidates.join(" or ")}` : "Ambiguous date"}>ambiguous</Badge>
      )}
      {status === "document_date" && <span className="ml-1 text-[11px] text-slate-500">(record date)</span>}
      {status === "partial" && <span className="ml-1 text-[11px] text-slate-500">(partial)</span>}
    </span>
  );
}

export function Spinner({ text = "Loading…" }: { text?: string }) {
  return <div className="p-6 text-sm text-slate-500 flex items-center gap-2"><span className="h-3 w-3 rounded-full border-2 border-brand-500 border-t-transparent animate-spin" />{text}</div>;
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="p-6 text-center text-sm text-slate-500">{children}</div>;
}

export function Stat({ label: l, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "red" | "amber" | "teal" }) {
  const color = tone === "red" ? "text-red-700" : tone === "amber" ? "text-amber-700" : tone === "teal" ? "text-brand-700" : "text-slate-900";
  return (
    <div className="card px-4 py-3">
      <div className="text-xs font-medium text-slate-500">{l}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="text-[11px] text-slate-500 mt-0.5">{hint}</div>}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  const cls = tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-sky-200 bg-sky-50 text-sky-900";
  return <div className={`rounded-md border px-3 py-2 text-xs ${cls}`}>{children}</div>;
}

export const TYPE_TONE: Record<string, string> = {
  medication: "teal", condition: "violet", allergy: "red", investigation: "blue", event: "gray",
  admission: "gray", discharge: "gray", surgery: "gray", procedure: "gray", consultation: "gray", follow_up: "gray",
};

export function fmtDateTime(s: string) {
  try { return new Date(s).toLocaleString(); } catch { return s; }
}
