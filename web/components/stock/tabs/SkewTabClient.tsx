"use client";

import { useState } from "react";

import type { SkewAnalysisResponse } from "@/lib/api";
import { toNum } from "@/lib/formatters";

import { SmileChart } from "../panels/SmileChart";
import { SkewClassSpectrum } from "../panels/SkewClassSpectrum";
import { SkewHistoryChart } from "../panels/SkewHistoryChart";
import { SkewPostureTiles } from "../panels/SkewPostureTiles";
import { SkewReadPanel } from "../panels/SkewReadPanel";
import { SkewRhoPanel } from "../panels/SkewRhoPanel";
import { SkewTermPanel } from "../panels/SkewTermPanel";

function actualSign(rr: string | number | null | undefined): string {
  const v = toNum(rr);
  if (v == null) return "unknown";
  if (v > 1e-6) return "put_skew";
  if (v < -1e-6) return "call_skew";
  return "flat";
}

export function SkewTabClient({
  ticker,
  initial,
}: {
  ticker: string;
  initial: SkewAnalysisResponse;
}) {
  const [data] = useState(initial);
  if (data.backfill_status === "empty") {
    return (
      <div style={{ color: "var(--text-muted)", padding: 16 }}>
        No skew history for {ticker} yet.
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SkewPostureTiles
        p={{
          rr_25d: data.rr_25d,
          rr_z_180d: data.rr_z_180d,
          rr_pct_252d: data.rr_pct_252d,
          deviation_class: data.deviation_class,
          drive_class: data.drive_class,
          borrow_flag: data.borrow_flag,
          regime: data.regime,
        }}
      />
      <SkewReadPanel read={data.read} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <SkewHistoryChart data={data.history} />
        <SkewRhoPanel
          rho63={data.rho_spotvol_63d}
          rho21={data.rho_spotvol_21d}
          series={data.rho_series}
        />
        <SkewTermPanel
          termClass={data.skew_term_class}
          frontRr={data.front_rr}
          backRr={data.back_rr}
        />
        <SkewClassSpectrum
          assetClass={data.asset_class}
          expectedSign={data.class_expected_sign}
          actualSign={actualSign(data.rr_25d)}
        />
      </div>
      <SmileChart
        data={data.smile.map((c) => ({ expiry: c.expiry, points: c.points }))}
        spot={data.spot}
      />
    </div>
  );
}
