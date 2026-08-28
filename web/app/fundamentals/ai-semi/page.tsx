import { notFound } from "next/navigation";

import { CapexContextStrip } from "@/components/fundamentals/CapexContextStrip";
import { ChainCalendar } from "@/components/fundamentals/ChainCalendar";
import { ChainMetricMatrix } from "@/components/fundamentals/ChainMetricMatrix";
import { DeltaRail } from "@/components/fundamentals/DeltaRail";
import { DeskLimits } from "@/components/fundamentals/DeskLimits";
import { ProfitPoolStrip } from "@/components/fundamentals/ProfitPoolStrip";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

/** The one section this route serves. A section is a registry row on the API
 *  side (`SECTIONS` in `api/routers/fundamentals_desk.py`); this page is the
 *  `ai-semi` consumer of it. */
export const SECTION = "ai-semi";

export function message(error: unknown): string {
  return error instanceof Error ? error.message : "unknown API error";
}

/** Resolve to a value OR an error, never to a rejection.
 *
 *  EVERY panel settles independently and on purpose. The desk's job is to show
 *  which halves of the picture it holds, so one endpoint failing must leave the
 *  other five standing — a page-level `Promise.all` rejection would replace a
 *  partial answer with no answer, which is strictly less information.
 *
 *  The error must then reach the component. A failed request rendered through
 *  `?? []` becomes "no upcoming print is held for any member of this section" —
 *  an affirmative coverage claim manufactured out of a failure, and the exact
 *  defect the node page's review caught one layer down. */
export async function settle<T>(
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

const NAV = [
  ["delta", "Since you looked"],
  ["calendar", "Next prints"],
  ["matrix", "Chain × metric"],
  ["profit-pool", "Profit pool"],
  ["capex", "Capex context"],
  ["limits", "Limits"],
] as const;

export default async function AiSemiDeskPage() {
  const [delta, calendar, matrix, pool, limits] = await Promise.all([
    settle(api.deskDelta(SECTION)),
    settle(api.deskCalendar(SECTION)),
    settle(api.deskMatrix(SECTION)),
    settle(api.deskProfitPool(SECTION)),
    settle(api.deskLimits(SECTION)),
  ]);

  // `deskCalendar` allows a 404 through as null, because the node page passes a
  // chain that may not exist. Here the section is fixed, so a null means THIS
  // SECTION is not registered — a different fact from an empty desk, and one
  // that must not render as "nothing is happening in AI/semi".
  if (calendar.value === null) notFound();

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <header>
        <h1 className="text-lg font-semibold text-zinc-100">
          AI / semiconductors
        </h1>
        <p className="mt-1 text-xs text-zinc-500">
          Computed from what Argon already holds. Every panel below abstains out
          loud rather than filling a gap: this desk lists names and their filed
          figures, and it does not rank them.
        </p>
        {/* Anchors, not routes: the desk is one page and the reader scrolls
            it. Six tabs that each refetch a fifth of the same answer would
            make the panels look independent when they share one as-of. */}
        <nav className="mt-3 flex flex-wrap gap-3 border-b border-zinc-900 pb-2">
          {NAV.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className="text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300"
            >
              {label}
            </a>
          ))}
        </nav>
      </header>

      <div id="delta">
        <DeltaRail
          data={delta.value ?? null}
          error={delta.error ? message(delta.error) : undefined}
        />
      </div>
      <div id="calendar">
        <ChainCalendar
          data={calendar.value ?? null}
          error={calendar.error ? message(calendar.error) : undefined}
        />
      </div>
      <div id="matrix">
        <ChainMetricMatrix
          data={matrix.value ?? null}
          error={matrix.error ? message(matrix.error) : undefined}
        />
      </div>
      <div id="profit-pool">
        <ProfitPoolStrip
          layers={pool.value ?? null}
          error={pool.error ? message(pool.error) : undefined}
        />
      </div>
      <div id="capex">
        <CapexContextStrip />
      </div>
      <div id="limits">
        <DeskLimits
          data={limits.value ?? null}
          error={limits.error ? message(limits.error) : undefined}
        />
      </div>
    </main>
  );
}
