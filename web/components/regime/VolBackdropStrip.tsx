"use client";

import { fmtDecimal } from "@/lib/formatters";
import CardSparkline from "./primitives/CardSparkline";
import {
  useRegimeQuotes,
  type RegimeQuotesResponse,
} from "@/lib/regime/useRegimeQuotes";
import {
  useVolBackdrop,
  type VolBackdropData,
} from "@/lib/regime/useVolBackdrop";
import {
  termStructureRead,
  ratioSeries as termRatioSeries,
  symbolRead,
} from "@/lib/regime/derive/volBackdrop";

const SYMBOLS = ["VIX", "VIX3M", "VVIX", "COR1M"] as const;

const labels: Record<(typeof SYMBOLS)[number], string> = {
  VIX: "VIX",
  VIX3M: "VIX3M",
  VVIX: "VVIX",
  COR1M: "COR1M",
};

const tooltips: Record<(typeof SYMBOLS)[number], string> = {
  VIX: "S&P 500 30-day implied vol",
  VIX3M: "S&P 500 3-month implied vol",
  VVIX: "Vol-of-vol (VIX of VIX)",
  COR1M: "1-month implied correlation among S&P components",
};

export function VolBackdropStripView({
  data,
  quotes,
}: {
  data: VolBackdropData | null;
  quotes: RegimeQuotesResponse | null;
}) {
  if (!data) return null;

  // Live term structure when both legs are fresh; falls back to daily ratio.
  // Derivations live in @/lib/regime/derive/volBackdrop (verbatim); the clock
  // stays inside the lib calls, like the original quoteIsFresh.
  const { liveRatio, ratio, state } = termStructureRead(data, quotes);

  // Daily VIX/VIX3M ratio series for the term-structure sparkline, joined by
  // date (the two series can have mismatched holidays/backfill gaps).
  const ratioSeries = termRatioSeries(data);

  const cardStyle = {
    border: "1px solid var(--border-dim)",
    background: "var(--bg-panel)",
    padding: "10px 12px",
    minWidth: 0,
  } as const;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${SYMBOLS.length + 1}, 1fr)`,
        gap: 8,
      }}
    >
      {SYMBOLS.map((s) => {
        // Live: current quote with change vs last daily close (intraday
        // ret_1d convention, same as TickerCards). Daily: close-over-close.
        const { live, close, chg } = symbolRead(s, data, quotes);
        return (
          <div key={s} title={tooltips[s]} style={cardStyle}>
            <div
              style={{
                fontSize: 10,
                letterSpacing: "0.15em",
                color: "var(--text-muted)",
                textTransform: "uppercase",
              }}
            >
              {labels[s]}
              {live && (
                <span style={{ color: "var(--positive)", marginLeft: 4 }}>
                  ●
                </span>
              )}
            </div>
            <div
              style={{
                fontSize: 18,
                fontWeight: 600,
                color: "var(--text-primary)",
                fontFamily: "var(--font-mono)",
              }}
            >
              {close != null ? fmtDecimal(close, 2) : "—"}
            </div>
            <div
              style={{
                fontSize: 11,
                color:
                  chg == null
                    ? "var(--text-muted)"
                    : chg >= 0
                      ? "var(--positive)"
                      : "var(--negative)",
              }}
            >
              {chg != null
                ? `${chg >= 0 ? "+" : ""}${fmtDecimal(chg, 2)}%`
                : "—"}
            </div>
            <CardSparkline
              values={(data.series[s] ?? []).map((p) => p.close)}
              label={`${labels[s]} daily closes`}
            />
          </div>
        );
      })}

      <div style={cardStyle}>
        <div
          style={{
            fontSize: 10,
            letterSpacing: "0.15em",
            color: "var(--text-muted)",
            textTransform: "uppercase",
          }}
        >
          Term Structure
          {liveRatio != null && (
            <span style={{ color: "var(--positive)", marginLeft: 4 }}>●</span>
          )}
        </div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 600,
            fontFamily: "var(--font-mono)",
            color:
              state === "backwardation"
                ? "var(--warning)"
                : "var(--text-primary)",
          }}
        >
          {ratio != null ? fmtDecimal(ratio, 3) : "—"}
        </div>
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color:
              state === "backwardation"
                ? "var(--warning)"
                : "var(--text-secondary)",
          }}
        >
          {state ?? "—"}
        </div>
        <CardSparkline
          values={ratioSeries}
          label="VIX/VIX3M daily ratio"
          color="var(--accent-warm, #F5A623)"
        />
      </div>
    </div>
  );
}

export default function VolBackdropStrip() {
  const { data } = useVolBackdrop();
  const { data: quotes } = useRegimeQuotes();
  return <VolBackdropStripView data={data ?? null} quotes={quotes ?? null} />;
}
