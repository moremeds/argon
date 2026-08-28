import { notFound } from "next/navigation";

import { NodeAliasQuestions } from "@/components/fundamentals/NodeAliasQuestions";
import type { AliasExposure } from "@/components/fundamentals/NodeAliasQuestions";
import { NodeCalendarStrip } from "@/components/fundamentals/NodeCalendarStrip";
import { NodeLimits } from "@/components/fundamentals/NodeLimits";
import { NodeUnderwritingPanel } from "@/components/fundamentals/NodeUnderwritingPanel";
import { ReportView } from "@/components/reports/ReportView";
import { api } from "@/lib/api";
import type {
  DeskCalendarResponse,
  NodeUnderwritingRow,
  ReportResponse,
} from "@/lib/api";

export const dynamic = "force-dynamic";

/** The one section this route serves. A section is a registry row on the API
 *  side; this page is the `ai-semi` consumer of it. */
export const SECTION = "ai-semi";

/**
 * A CATCH-ALL route, because 20 of the desk's 38 chain names contain a slash
 * (`Networking/Optical`, `Semi-Logic/ASIC`, `Cooling/Thermal`, …) and a single
 * dynamic segment cannot match one. Next hands the segments already decoded, so
 * rejoining with "/" recovers the chain name exactly, and a chain WITHOUT a
 * slash arrives as a one-element array and resolves the same way.
 */
export function chainFromSegments(segments: string[]): string {
  return segments.join("/");
}

/** `_fetch` throws `API <status> for <path>: <body>` and exposes nothing else.
 *  A 404 from the reports route is structurally different from a missing
 *  report — see the report slot below — so the status has to be recovered. */
function isNotFound(error: unknown): boolean {
  return error instanceof Error && /^API 404 /.test(error.message);
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "unknown API error";
}

async function settle<T>(
  p: Promise<T>,
): Promise<
  { value: T; error?: undefined } | { value?: undefined; error: unknown }
> {
  try {
    return { value: await p };
  } catch (error) {
    return { error };
  }
}

/** The `chain_exposure` block's rows, or null when no block can be read.
 *  Null is not an empty list: "the report has no exposures" and "we could not
 *  read the report" are different facts and the alias panel renders them
 *  differently. */
function aliasExposures(
  data: ReportResponse | undefined,
): AliasExposure[] | null {
  const blocks = data?.report?.blocks;
  if (!blocks) return null;
  const block = blocks.find((b) => b.block_kind === "chain_exposure");
  if (!block) return null;
  const rows = (block.payload as { exposures?: unknown }).exposures;
  if (!Array.isArray(rows)) return null;
  return rows.map((r) => {
    const row = r as Record<string, unknown>;
    return {
      ticker: String(row.ticker ?? ""),
      magnitude: typeof row.magnitude === "number" ? row.magnitude : null,
      basis: typeof row.basis === "string" ? row.basis : null,
      is_member: row.is_member === true,
    };
  });
}

/** The report slot is THREE-state, and the third state is the one that matters.
 *
 *  `GET /api/research/reports/{type}/{key}` answers 200 with `state:
 *  "no_report"` when nothing has been assembled — so a 404 from it never means
 *  "no report". It means the route did not match, which for a chain whose name
 *  contains a slash is guaranteed: uvicorn unquotes the raw path before
 *  Starlette routes it, so `%2F` arrives as a real separator and no
 *  single-segment `{key}` route matches (verified 2026-08-28).
 *
 *  Rendering that as "no published report backs this node" would be a false
 *  statement about our coverage, so it renders as an ADDRESSING failure
 *  instead. Either way this page never assembles: a report REPLAYS from its
 *  stored blocks, and re-assembling under today's data is a different answer
 *  wearing an old version number.
 */
function ReportSlot({
  data,
  error,
  chain,
}: {
  data: ReportResponse | undefined;
  error: unknown;
  chain: string;
}) {
  if (data && data.state === "ok" && data.report) {
    return <ReportView data={data} reportType="chain" reportKey={chain} />;
  }
  if (error != null && isNotFound(error)) {
    return (
      <section data-testid="node-report-unaddressable" className="p-6 pb-0">
        <h1 className="text-xl font-semibold text-zinc-200">{chain}</h1>
        <p className="mt-2 text-xs text-amber-300/80">
          The report route cannot address this chain name: a chain name
          containing a slash is not reachable as a path segment, so whether a
          report exists for it is unknown from here. This is an addressing
          failure, not a statement that no report was published.
        </p>
      </section>
    );
  }
  return (
    <section data-testid="node-report-absent" className="p-6 pb-0">
      <h1 className="text-xl font-semibold text-zinc-200">{chain}</h1>
      <p className="mt-2 text-xs text-zinc-500">
        {error != null
          ? `The report request failed: ${message(error)}`
          : `No published report backs this node${
              data?.reason ? ` — ${data.reason}` : "."
            }`}
      </p>
      <p className="mt-1 text-[11px] text-zinc-600">
        The rest of this page is unaffected: the calendar, the underwriting
        table and the limits below read the warm store directly. An absent
        report is a fact about our coverage, not an error, and this page does
        not assemble one.
      </p>
    </section>
  );
}

export default async function NodePage({
  params,
}: {
  params: Promise<{ node: string[] }>;
}) {
  const { node } = await params;
  const chain = chainFromSegments(node);

  const [calendar, underwriting, report] = await Promise.all([
    settle<DeskCalendarResponse | null>(api.deskCalendar(SECTION, chain)),
    settle<NodeUnderwritingRow[] | null>(api.nodeUnderwriting(SECTION, chain)),
    settle<ReportResponse>(api.researchReport("chain", chain)),
  ]);

  // A 404 from the desk endpoints means the chain is not on this desk at all.
  // An unknown chain must NOT render as an empty node — an empty node is the
  // claim that this desk contains it and it holds nothing, which is a
  // different and false statement. A chain that DOES exist and holds no rows
  // answers 200 [] and renders as the real, empty node it is.
  if (calendar.value === null || underwriting.value === null) {
    notFound();
  }

  return (
    <div className="text-zinc-200">
      <ReportSlot data={report.value} error={report.error} chain={chain} />
      <div className="px-6 pb-8">
        <NodeCalendarStrip
          data={calendar.value ?? null}
          error={calendar.error == null ? undefined : message(calendar.error)}
        />
        <NodeUnderwritingPanel
          rows={underwriting.value ?? []}
          error={
            underwriting.error == null ? undefined : message(underwriting.error)
          }
        />
        <NodeAliasQuestions exposures={aliasExposures(report.value)} />
        <NodeLimits />
      </div>
    </div>
  );
}
