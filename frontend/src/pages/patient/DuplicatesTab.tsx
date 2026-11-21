import { useState } from "react";
import { Link } from "react-router-dom";
import { api, P } from "../../api";
import { Badge, Empty, ErrorBox, Notice, Spinner, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

interface DocSide { id: string; original_filename: string; doc_type: string; document_date_text: string | null }
interface FindSide { id: string; summary: string; document_filename: string; page: number; passage: string; date_text: string | null; document_id: string }
interface Dup { id: string; level: string; kind: string; similarity: number; review_status: string; details_json: Record<string, unknown>; a: DocSide & FindSide; b: DocSide & FindSide }

const KIND_TONE: Record<string, string> = { exact_duplicate: "red", near_duplicate: "amber", similar_distinct: "gray", duplicate_finding: "amber", related_finding: "gray" };

export default function DuplicatesTab({ pid, canWrite, refreshKey, openEvidence }: TabProps) {
  const [level, setLevel] = useState<"document" | "finding">("document");
  const { data, error, loading, reload } = useAsync(() => api.get<Dup[]>(`${P(pid)}/duplicates?level=${level}`), [pid, level, refreshKey]);
  const review = async (id: string, decision: string) => { await api.post(`${P(pid)}/duplicates/${id}/review`, { decision }); reload(); };
  return (
    <div className="space-y-3">
      <Notice>Duplicates are proposed using file hashes, text similarity (OCR-tolerant), document dates and structured fact keys. Nothing is merged or deleted automatically — a reviewer confirms or rejects each candidate, and all originals are preserved.</Notice>
      <div className="flex gap-1">
        {(["document", "finding"] as const).map((l) => <button key={l} className={level === l ? "btn-primary" : "btn-secondary"} onClick={() => setLevel(l)}>{l} level</button>)}
      </div>
      {loading && !data && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && data.length === 0 && <div className="card"><Empty>No duplicate candidates.</Empty></div>}
      {data?.map((d) => (
        <div key={d.id} className="card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={KIND_TONE[d.kind]}>{label(d.kind)}</Badge>
            <span className="text-xs muted">similarity {d.similarity.toFixed(3)}</span>
            <Badge tone={d.review_status === "pending" ? "amber" : "green"}>{label(d.review_status)}</Badge>
            {canWrite && d.review_status === "pending" && (
              <span className="ml-auto flex gap-2">
                <button className="btn-secondary" onClick={() => review(d.id, "confirmed_duplicate")}>Confirm duplicate</button>
                <button className="btn-secondary" onClick={() => review(d.id, "not_duplicate")}>Not a duplicate</button>
              </span>
            )}
          </div>
          <div className="mt-2 grid md:grid-cols-2 gap-3 text-sm">
            {[d.a, d.b].map((s, i) => s && (
              level === "document" ? (
                <div key={i} className="rounded-md bg-slate-50 border border-slate-200 p-3">
                  <Link className="font-medium text-brand-700 hover:underline" to={`/patients/${pid}/documents/${s.id}`}>{s.original_filename}</Link>
                  <div className="text-xs muted">{label(s.doc_type)} · {s.document_date_text ?? "undated"}</div>
                  {(d.details_json[i === 0 ? "lines_only_in_a" : "lines_only_in_b"] as string[] | undefined)?.length ? (
                    <div className="mt-2 text-xs"><div className="font-semibold text-slate-600">Lines only in this document</div>
                      {(d.details_json[i === 0 ? "lines_only_in_a" : "lines_only_in_b"] as string[]).map((l, k) => <div key={k} className="font-mono text-[11px] text-slate-700">{l}</div>)}</div>
                  ) : <div className="mt-2 text-xs text-slate-500">No unique lines.</div>}
                </div>
              ) : (
                <button key={i} className="text-left rounded-md bg-slate-50 border border-slate-200 p-3 hover:border-brand-300" onClick={() => openEvidence(s.id)}>
                  <div className="font-medium">{s.summary}</div>
                  <div className="text-xs muted">{s.document_filename} · p.{s.page} · {s.date_text ?? "undated"}</div>
                  <div className="font-mono text-[11px] text-slate-700 mt-1">“{s.passage}”</div>
                </button>
              )
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
