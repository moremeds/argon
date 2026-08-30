import { GOLD_STRUCTURAL_WIDTH } from "@/components/macro/chartGeometry";
import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

import { Tile } from "../Tile";

import { GoldHoldingsVsPriceChart } from "./GoldHoldingsVsPriceChart";

type S = components["schemas"]["GoldStructuralPostureModel"];

/** Tonnes, signed, one decimal — the board's own unit and precision for these buckets. */
function tonnes(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}t`;
}

function toneOf(v: string | number | null | undefined) {
  if (v == null) return "default" as const;
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n) || n === 0) return "default" as const;
  return n > 0 ? ("positive" as const) : ("negative" as const);
}

const BUCKETS = [
  {
    key: "strategic" as const,
    label: "Strategic accumulators",
    field: "cb_strategic_12m_sum_t" as const,
  },
  {
    key: "tactical" as const,
    label: "Tactical defenders",
    field: "cb_tactical_12m_sum_t" as const,
  },
  {
    key: "diversifier" as const,
    label: "Reserve diversifiers",
    field: "cb_diversifier_12m_sum_t" as const,
  },
];

/**
 * Board t5 — "Central banks · 12M net, three buckets" (Q5).
 *
 * ### Why this is its own panel
 *
 * It used to be one tile inside `StructuralPanel`, printing all three bucket totals as a
 * single run-on sub-line under a headline that was the strategic figure alone. The board
 * gives the three buckets equal weight and a panel of their own, and it is right to: the
 * panel exists to make one comparison, and a layout that promotes one of the three
 * answers the comparison before the reader makes it.
 *
 * ### Why the standfirst is derived
 *
 * The board's reads "the strategic accumulators … were net *sellers* over 12 months; the
 * buying came from the diversifier bucket". That was true at its capture instant and is
 * a claim about signs that can invert on any WGC release. So the sentence is built from
 * the signs actually present, and the "unbundling" framing — which is what binds — is
 * stated whichever way the buckets fall.
 */
export function CbReservesPanel({ structural }: { structural: S }) {
  const values = BUCKETS.map((b) => {
    const raw = structural[b.field];
    const n = raw == null ? null : Number(raw);
    return {
      ...b,
      raw,
      n: Number.isFinite(n as number) ? (n as number) : null,
    };
  });
  const known = values.filter((v) => v.n !== null);
  const buyers = known.filter((v) => (v.n as number) > 0);
  const sellers = known.filter((v) => (v.n as number) < 0);

  return (
    <BoardPanel
      id="cb-reserves"
      title="Central-bank flows"
      questions={["Q5"]}
      basis="REAL"
      source={
        <>
          /api/gold/state structural · WGC official-sector series, summed over
          12 months per bucket · {known.length} of {BUCKETS.length} buckets
          reported
        </>
      }
    >
      <div className="chart">
        <GoldHoldingsVsPriceChart
          goldHistory={structural.gold_history ?? []}
          gldHistory={structural.gld_history ?? []}
          cbCountryHistory={structural.cb_country_history ?? []}
          width={GOLD_STRUCTURAL_WIDTH}
          height={Math.round((GOLD_STRUCTURAL_WIDTH * 200) / 1040)}
        />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 8,
        }}
      >
        {values.map((b) => (
          <Tile
            key={b.key}
            label={b.label}
            value={tonnes(b.raw)}
            tone={toneOf(b.raw)}
            sub="12M NET"
          />
        ))}
      </div>

      <p data-testid="cb-bucket-read" className="read">
        12-month net flows.{" "}
        {known.length === 0 ? (
          <>
            No bucket has a 12-month total.
          </>
        ) : (
          <>
            Over 12 months{" "}
            {buyers.length > 0 ? (
              <>
                <b>{buyers.map((b) => b.label.toLowerCase()).join(" and ")}</b>{" "}
                added
              </>
            ) : (
              <>no bucket added</>
            )}
            {sellers.length > 0 && (
              <>
                {" "}
                while{" "}
                <b>
                  {sellers.map((b) => b.label.toLowerCase()).join(" and ")}
                </b>{" "}
                were net sellers
              </>
            )}
            . Behaviour buckets remain separate.
          </>
        )}
      </p>
    </BoardPanel>
  );
}
