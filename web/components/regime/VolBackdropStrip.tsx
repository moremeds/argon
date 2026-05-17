"use client";

import { fmtDecimal } from "@/lib/formatters";
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
}: {
  data: VolBackdropData | null;
}) {
  if (!data) return null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${SYMBOLS.length + 1}, 1fr)`,
        gap: 8,
        padding: "12px 16px",
        borderTop: "1px solid var(--border-dim)",
        borderBottom: "1px solid var(--border-dim)",
        background: "var(--bg-panel)",
      }}
    >
      {SYMBOLS.map((s) => {
        const close = lastClose(data.series[s]);
        const chg = pctChange(data.series[s]);
        return (
          <div key={s} title={tooltips[s]}>
            <div
              style={{
                fontSize: 10,
                letterSpacing: "0.15em",
                color: "var(--text-muted)",
                textTransform: "uppercase",
              }}
            >
              {labels[s]}
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
          </div>
        );
      })}

      <div>
        <div
          style={{
            fontSize: 10,
            letterSpacing: "0.15em",
            color: "var(--text-muted)",
            textTransform: "uppercase",
          }}
        >
          Term Structure
        </div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 600,
            fontFamily: "var(--font-mono)",
            color:
              data.term_structure_state === "backwardation"
                ? "var(--warning)"
                : "var(--text-primary)",
          }}
        >
          {data.term_structure_ratio != null
            ? fmtDecimal(data.term_structure_ratio, 3)
            : "—"}
        </div>
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color:
              data.term_structure_state === "backwardation"
                ? "var(--warning)"
                : "var(--text-secondary)",
          }}
        >
          {data.term_structure_state ?? "—"}
        </div>
      </div>
    </div>
  );
}

export default function VolBackdropStrip() {
  const { data } = useVolBackdrop();
  return <VolBackdropStripView data={data ?? null} />;
}
