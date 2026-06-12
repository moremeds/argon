"use client";

import { fmtDecimal } from "@/lib/formatters";
import CardSparkline from "./primitives/CardSparkline";
import {
  quoteIsFresh,
  useRegimeQuotes,
  type RegimeQuotesResponse,
} from "@/lib/regime/useRegimeQuotes";
import {
  useVolBackdrop,
  type VolBackdropData,
} from "@/lib/regime/useVolBackdrop";

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

function lastClose(points: { close: number }[] | undefined): number | null {
  if (!points || !points.length) return null;
  return points[points.length - 1].close;
}

function pctChange(points: { close: number }[] | undefined): number | null {
  if (!points || points.length < 2) return null;
  const prev = points[points.length - 2].close;
  const last = points[points.length - 1].close;
  if (!prev) return null;
  return ((last - prev) / prev) * 100;
}

export function VolBackdropStripView({
  data,
  quotes,
}: {
  data: VolBackdropData | null;
  quotes: RegimeQuotesResponse | null;
}) {
  if (!data) return null;

  // Live term structure when both legs are fresh; falls back to daily ratio.
  const freshWindow = quotes?.fresh_within_seconds;
  const qv = quotes?.quotes?.VIX;
  const q3 = quotes?.quotes?.VIX3M;
  const liveRatio =
    qv &&
    q3 &&
    quoteIsFresh(qv.quoted_at, freshWindow) &&
    quoteIsFresh(q3.quoted_at, freshWindow) &&
    q3.price
      ? qv.price / q3.price
      : null;
  const ratio = liveRatio ?? data.term_structure_ratio;
  const state =
    ratio != null
      ? ratio < 1
        ? "contango"
        : "backwardation"
      : data.term_structure_state;

  // Daily VIX/VIX3M ratio series for the term-structure sparkline, joined by
  // date (the two series can have mismatched holidays/backfill gaps).
  const vix3mByDate = new Map(
    (data.series.VIX3M ?? []).map((p) => [p.date, p.close]),
  );
  const ratioSeries = (data.series.VIX ?? []).map((p) => {
    const v3 = vix3mByDate.get(p.date);
    return v3 ? p.close / v3 : null;
  });

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
        const q = quotes?.quotes?.[s];
        const live = q != null && quoteIsFresh(q.quoted_at, freshWindow);
        const dailyClose = lastClose(data.series[s]);
        // Live: current quote with change vs last daily close (intraday
        // ret_1d convention, same as TickerCards). Daily: close-over-close.
        const close = live ? q.price : dailyClose;
        const chg =
          live && dailyClose
            ? ((q.price - dailyClose) / dailyClose) * 100
            : pctChange(data.series[s]);
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
