import { useMemo, useState } from "react";
import { api, P } from "../../api";
import type { Finding } from "../../types";
import { Badge, DateCell, Empty, ErrorBox, Notice, Spinner, VerificationBadge, label, useAsync } from "../../components/ui";
import type { TabProps } from "../PatientWorkspace";

export default function InvestigationsTab({ pid, refreshKey, openEvidence }: TabProps) {
  const { data, error, loading } = useAsync(() => api.get<Finding[]>(`${P(pid)}/investigations`), [pid, refreshKey]);
  const [test, setTest] = useState("");
  const tests = useMemo(() => Array.from(new Set((data ?? []).map((f) => String(f.details.normalized_test ?? f.details.test_name)))).sort(), [data]);
  const unitsByTest = useMemo(() => {
    const m: Record<string, Set<string>> = {};
    (data ?? []).forEach((f) => { if (f.details.unit) (m[String(f.details.normalized_test)] ??= new Set()).add(String(f.details.unit)); });
    return m;
  }, [data]);
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  const rows = (data ?? []).filter((f) => !test || String(f.details.normalized_test ?? f.details.test_name) === test);
  return (
    <div className="space-y-3">
      <Notice>Values, units and reference ranges are shown exactly as written. Converted values (where an explicit rule exists) are display-only and labelled; they never replace the original. MedTrace does not interpret results.</Notice>
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-600">Test</label>
        <select className="input max-w-xs" value={test} onChange={(e) => setTest(e.target.value)}>
          <option value="">All tests</option>{tests.map((t) => <option key={t} value={t}>{t}{unitsByTest[t]?.size > 1 ? " (multiple units)" : ""}</option>)}
        </select>
      </div>
      <div className="card overflow-x-auto">
        {rows.length === 0 ? <Empty>No investigations extracted.</Empty> : (
          <table className="w-full min-w-[56rem]">
            <thead><tr>{["Date", "Test (as written)", "Value", "Unit (original)", "Reference range (as written)", "Flag as printed", "Converted (display only)", "Source", "Verification"].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>{rows.map((f) => {
              const d = f.details;
              const multi = unitsByTest[String(d.normalized_test)]?.size > 1;
              return (
                <tr key={f.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => openEvidence(f.id)}>
                  <td className="td"><DateCell text={f.date_text} iso={f.date_iso} status={f.date_status} candidates={f.date_candidates} /></td>
                  <td className="td font-medium">{String(d.test_name)}<div className="text-[11px] text-slate-500">{label(String(d.category))}</div></td>
                  <td className="td tabular-nums font-semibold">{d.value_text ?? <span className="text-slate-400 italic font-normal">not documented</span>}</td>
                  <td className="td">{d.unit ?? <span className="text-slate-400 italic">—</span>} {multi && <Badge tone="amber" title="This test appears in different units across records">units differ</Badge>}</td>
                  <td className="td">{d.reference_range ?? <span className="text-slate-400 italic">not documented</span>}</td>
                  <td className="td">{d.flag_as_written ?? ""}</td>
                  <td className="td text-xs text-violet-700">{d.converted_value != null ? <span title={String(d.conversion_rule)}>{d.converted_value} {d.converted_unit}<div className="text-[10px] text-slate-500">{String(d.conversion_rule)}</div></span> : ""}</td>
                  <td className="td text-xs">{f.document_filename}<div className="text-slate-500">p.{f.page_number}</div></td>
                  <td className="td"><VerificationBadge status={f.verification_status} /></td>
                </tr>
              );
            })}</tbody>
          </table>
        )}
      </div>
    </div>
  );
}
