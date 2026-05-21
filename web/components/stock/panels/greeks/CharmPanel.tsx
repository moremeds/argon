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

const toSpot = (v: string | number | null | undefined): number | null => {
  const n = toNum(v);
  return n != null && n > 0 ? n : null;
};

export function CharmPanel({ ticker, strikeExposures, summary }: Props) {
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
        Charm data not yet available for this run.
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
      netValue: (toNum(r.call_charm) ?? 0) + (toNum(r.put_charm) ?? 0),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const callPutCurve = rowsForExpiry
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      callValue: toNum(r.call_charm),
      putValue: toNum(r.put_charm),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const dte = summaryRow.dte ?? null;
  const spot = toSpot(summaryRow.spot);
  const flip = toNum(summaryRow.charm_flip);
  const netCharm = toNum(summaryRow.net_charm);
  const pin = toNum(summaryRow.charm_pin_strike);
  const imb = toNum(summaryRow.charm_imbalance_pct);
  const aboveSum = toNum(summaryRow.charm_above_sum);
  const belowSum = toNum(summaryRow.charm_below_sum);

  const liveTone =
    netCharm == null || Math.abs(netCharm) < 1000
      ? "muted"
      : netCharm < 0
        ? "negative"
        : "positive";

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
          Timer · Charm
        </div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: "var(--text-primary)",
          }}
        >
          {summaryRow.charm_headline ?? "Charm pressure"}
        </div>
        {summaryRow.charm_subtitle && (
          <div
            style={{
              fontSize: 12,
              color: "var(--text-secondary)",
              fontStyle: "italic",
            }}
          >
            {summaryRow.charm_subtitle}
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
          label="Live charm"
          value={fmtMoneyAbbrev(netCharm)}
          sub={
            netCharm == null
              ? undefined
              : netCharm < 0
                ? "Sell pressure"
                : netCharm > 0
                  ? "Buy pressure"
                  : "Flat"
          }
          tone={liveTone}
        />
        <ExposureTile
          label="Positioning"
          value={fmtMoneyAbbrev(
            aboveSum != null && belowSum != null ? aboveSum - belowSum : null,
          )}
          sub={imb != null ? `${(imb * 100).toFixed(0)}% imbalance` : "—"}
        />
        <ExposureTile
          label="Signal quality"
          value={summaryRow.charm_signal_quality ?? "weak"}
          sub={
            summaryRow.charm_signal_quality === "aligned"
              ? "live and positioning align"
              : summaryRow.charm_signal_quality === "mixed"
                ? "live and positioning disagree"
                : "thin signal"
          }
          tone={
            summaryRow.charm_signal_quality === "aligned" ? liveTone : "muted"
          }
        />
        <ExposureTile
          label="Where it matters"
          value={pin != null ? `$${pin.toFixed(2)}` : "—"}
          sub={
            pin != null && spot != null
              ? `${(((pin - spot) / spot) * 100).toFixed(1)}% from spot`
              : undefined
          }
        />
      </div>

      <ExpiryDropdown
        options={sortedSummary.map((r) => ({
          value: r.expiry,
          label: `${r.expiry}${r.dte != null ? ` (${r.dte}d)` : ""}`,
        }))}
        value={summaryRow.expiry}
        onChange={setSelected}
      />

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
          yLabel="Charm"
          title={`Net Charm Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
        <CallPutExposureChart
          curve={callPutCurve}
          spot={spot}
          yLabel="Charm"
          title={`Charm Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
      </div>
    </div>
  );
}
