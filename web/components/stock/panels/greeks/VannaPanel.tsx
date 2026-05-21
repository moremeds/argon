"use client";

import { useMemo, useState } from "react";
import type { components } from "@/lib/types";
import { fmtMoneyAbbrev } from "@/lib/formatters";
import { CallPutExposureChart } from "./CallPutExposureChart";
import { ExpiryDropdown } from "./ExpiryDropdown";
import { ExposureTile } from "./ExposureTile";
import { NetExposureChart } from "./NetExposureChart";

type StrikeExposureRow = components["schemas"]["StrikeExposureRow"];
type ExposuresSummaryRow = components["schemas"]["ExposuresSummaryRow"];

type Props = {
  ticker: string;
  strikeExposures: StrikeExposureRow[];
  summary: ExposuresSummaryRow[];
};

const toNum = (v: string | number | null | undefined): number | null => {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

// Guards spot values from poisoning charm imbalance / "% from spot" math.
// Mirrors the backend `_safe_spot` rejection of 0/negative/non-finite values.
const toSpot = (v: string | number | null | undefined): number | null => {
  const n = toNum(v);
  return n != null && n > 0 ? n : null;
};

export function VannaPanel({ ticker, strikeExposures, summary }: Props) {
  const sortedSummary = useMemo(
    () => [...summary].sort((a, b) => (a.expiry < b.expiry ? -1 : 1)),
    [summary],
  );
  const defaultExpiry = useMemo(() => {
    const live = sortedSummary
      .filter((r) => r.dte == null || (r.dte as number) >= 0)
      .sort(
        (a, b) => ((a.dte ?? 99999) as number) - ((b.dte ?? 99999) as number),
      );
    return (live[0] ?? sortedSummary[0])?.expiry ?? null;
  }, [sortedSummary]);
  const [selected, setSelected] = useState<string | null>(defaultExpiry);

  if (sortedSummary.length === 0) {
    return (
      <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
        Vanna data not yet available for this run.
      </div>
    );
  }

  const summaryRow =
    sortedSummary.find((r) => r.expiry === selected) ?? sortedSummary[0];
  const rowsForExpiry = strikeExposures.filter(
    (r) => r.expiry === summaryRow.expiry,
  );

  const netCurve = rowsForExpiry
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      netValue: (toNum(r.call_vanna) ?? 0) + (toNum(r.put_vanna) ?? 0),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const callPutCurve = rowsForExpiry
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      callValue: toNum(r.call_vanna),
      putValue: toNum(r.put_vanna),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const dte = summaryRow.dte ?? null;
  const spot = toSpot(summaryRow.spot);
  const flip = toNum(summaryRow.vanna_flip);
  const netVanna = toNum(summaryRow.net_vanna);
  const tone =
    netVanna == null || Math.abs(netVanna) < 1000
      ? "muted"
      : netVanna > 0
        ? "positive"
        : "negative";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div
          style={{
            fontSize: 10,
            letterSpacing: 1.5,
            color: "var(--accent-vol)",
            textTransform: "uppercase",
          }}
        >
          Volatility · Vanna
        </div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: "var(--text-primary)",
          }}
        >
          {summaryRow.vanna_headline ?? "Vanna positioning"}
        </div>
        {summaryRow.vanna_subtitle && (
          <div
            style={{
              fontSize: 12,
              color: "var(--text-secondary)",
              fontStyle: "italic",
            }}
          >
            {summaryRow.vanna_subtitle}
          </div>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        <ExposureTile
          label="Net Vanna"
          value={fmtMoneyAbbrev(netVanna)}
          sub={
            netVanna == null
              ? undefined
              : netVanna > 0
                ? "Long"
                : netVanna < 0
                  ? "Short"
                  : "Flat"
          }
          tone={tone}
        />
        <ExposureTile
          label="Top vol-sensitive strike"
          value={
            summaryRow.top_vanna_strike != null
              ? `$${Number(summaryRow.top_vanna_strike).toFixed(2)}`
              : "—"
          }
          sub={fmtMoneyAbbrev(toNum(summaryRow.top_vanna_value))}
        />
        <ExposureTile
          label="Δ from +1pt IV"
          value={fmtMoneyAbbrev(toNum(summaryRow.delta_shock_1pt_iv))}
          sub="Dealers sell when IV up"
        />
        <ExposureTile
          label="Vol-shock regime"
          value={summaryRow.vanna_regime ?? "neutral"}
          sub={
            summaryRow.vanna_regime === "procyclical"
              ? "amplifies down moves"
              : summaryRow.vanna_regime === "countercyclical"
                ? "dampens down moves"
                : "limited impact"
          }
          tone={
            summaryRow.vanna_regime === "procyclical"
              ? "negative"
              : summaryRow.vanna_regime === "countercyclical"
                ? "positive"
                : "muted"
          }
        />
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <ExpiryDropdown
          options={sortedSummary.map((r) => ({
            value: r.expiry,
            label: `${r.expiry}${r.dte != null ? ` (${r.dte}d)` : ""}`,
          }))}
          value={summaryRow.expiry}
          onChange={setSelected}
        />
        {rowsForExpiry.length === 0 && (
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
              fontStyle: "italic",
            }}
          >
            Aggregate only — per-strike chart available on nearest expiry.
          </span>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <NetExposureChart
          curve={netCurve}
          spot={spot}
          flipStrike={flip}
          yLabel="Vanna"
          title={`Net Vanna Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
        <CallPutExposureChart
          curve={callPutCurve}
          spot={spot}
          yLabel="Vanna"
          title={`Vanna Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
      </div>
    </div>
  );
}
