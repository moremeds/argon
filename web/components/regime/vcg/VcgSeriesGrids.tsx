"use client";

import { MultiPanelGrid, type PanelSpec } from "../MultiPanelGrid";
import {
  useVcgIntraday,
  type VcgIntradayPoint,
} from "@/lib/regime/useVcgSeries";
import { useMarketHours } from "@/lib/regime/useMarketHours";

type AnyRow = VcgIntradayPoint;

const PANELS: PanelSpec<AnyRow>[] = [
  {
    key: "vcg",
    label: "VCG Z",
    color: "var(--accent-warm, #F5A623)",
    fmt: (v) => v.toFixed(2),
    get: (r) => r.vcg,
  },
  {
    key: "vcg_adj",
    label: "VCG ADJ",
    fmt: (v) => v.toFixed(2),
    get: (r) => r.vcg_adj,
  },
  {
    key: "credit_price",
    label: "HYG",
    color: "var(--text-primary)",
    get: (r) => r.credit_price,
  },
  {
    key: "credit_5d_return_pct",
    label: "CREDIT 5D %",
    fmt: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`,
    get: (r) => r.credit_5d_return_pct,
  },
  {
    key: "residual",
    label: "RESIDUAL",
    fmt: (v) => v.toFixed(5),
    get: (r) => r.residual,
  },
  { key: "vix", label: "VIX", get: (r) => r.vix },
  {
    key: "vvix",
    label: "VVIX",
    color: "var(--accent-vol, #8B5CF6)",
    get: (r) => r.vvix,
  },
  {
    key: "beta1",
    label: "β1 (VVIX)",
    fmt: (v) => v.toFixed(5),
    get: (r) => r.beta1,
  },
];

export default function VcgSeriesGrids() {
  const marketState = useMarketHours();
  const { data: intraday } = useVcgIntraday(marketState);

  const flatRows: VcgIntradayPoint[] = [];
  const dividers: number[] = [];
  for (const s of intraday?.sessions ?? []) {
    if (flatRows.length > 0) dividers.push(flatRows.length);
    flatRows.push(...(s.points ?? []));
  }

  // Daily 90d series now live as sparklines inside the VCG cards above —
  // the standalone daily grid was removed in favour of that layout.
  return (
    <MultiPanelGrid
      title="VCG — Intraday, last 5 sessions"
      panels={PANELS}
      rows={flatRows}
      dividers={dividers}
      testId="vcg-intraday-grid"
    />
  );
}
