import Link from "next/link";

import { api } from "@/lib/api";
import type { ReportListResponse } from "@/lib/api";

export const metadata = { title: "Research Reports" };
export const dynamic = "force-dynamic";

export default async function ReportsPage() {
  let data: ReportListResponse;
  try {
    data = await api.researchReports(50);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return (
      <div className="p-6 text-sm text-red-300" role="alert">
        The report listing request failed: {detail}
      </div>
    );
  }

  return (
    <div className="p-6 text-zinc-200">
      <h1 className="text-xl font-semibold">Research reports</h1>
      <p className="mt-1 text-xs text-zinc-500">
        Every report is versioned and append-only. Re-assembling publishes a new
        version beside the old one; the delta between them is what a returning
        reader is actually after.
      </p>
      {data.reports.length === 0 ? (
        <p className="mt-6 text-sm text-zinc-500">
          No report has been assembled yet. Open a{" "}
          <Link className="underline" href="/chains">
            chain
          </Link>{" "}
          or a stock page and assemble one.
        </p>
      ) : (
        <table className="mt-4 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-500">
              <th className="px-2 py-2 text-left">Report</th>
              <th className="px-2 py-2 text-left">Type</th>
              <th className="px-2 py-2 text-right">Version</th>
              <th className="px-2 py-2 text-left">Status</th>
              <th className="px-2 py-2 text-left">Published</th>
            </tr>
          </thead>
          <tbody>
            {data.reports.map((r) => {
              const key = r.report_key.slice(r.report_key.indexOf(":") + 1);
              return (
                <tr key={r.report_key} className="border-b border-zinc-900">
                  <td className="px-2 py-1">
                    <a
                      className="hover:underline"
                      href={`/reports/${r.report_type}/${encodeURIComponent(key)}`}
                    >
                      {r.title}
                    </a>
                  </td>
                  <td className="px-2 py-1 text-zinc-500">{r.report_type}</td>
                  <td className="px-2 py-1 text-right tabular-nums">
                    v{r.version_no}
                  </td>
                  <td className="px-2 py-1 text-zinc-400">{r.status}</td>
                  <td className="px-2 py-1 text-xs text-zinc-500">
                    {new Date(r.created_at).toISOString().slice(0, 16)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
