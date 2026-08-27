import { ReportView } from "@/components/reports/ReportView";
import { api } from "@/lib/api";
import type { ReportResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ type: string; key: string }>;
  searchParams: Promise<{ version?: string }>;
}) {
  const { type, key } = await params;
  const { version } = await searchParams;
  if (type !== "company" && type !== "chain" && type !== "comparison") {
    return (
      <div className="p-6 text-sm text-red-300" role="alert">
        Unknown report type <code>{type}</code>; expected company, comparison,
        or chain.
      </div>
    );
  }
  const decoded = decodeURIComponent(key);

  let data: ReportResponse;
  try {
    data = await api.researchReport(
      type,
      decoded,
      version ? Number(version) : undefined,
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return (
      <div className="p-6 text-sm text-red-300" role="alert">
        The report request failed: {detail}
      </div>
    );
  }

  return <ReportView data={data} reportType={type} reportKey={decoded} />;
}
