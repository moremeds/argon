"use client";

import { MultiPanelGrid, type PanelSpec } from "../MultiPanelGrid";
import {
  useCriIntraday,
  type CriIntradayPoint,
} from "@/lib/regime/useCriSeries";
import { useMarketHours } from "@/lib/regime/useMarketHours";

const PANELS: PanelSpec<CriIntradayPoint>[] = [
  {
    key: "cri_score",
    label: "CRI",
    color: "var(--accent-warm, #F5A623)",
    get: (r) => r.cri_score,
  },
  { key: "vix", label: "VIX", get: (r) => r.vix },
  {
    key: "vvix",
    label: "VVIX",
    color: "var(--accent-vol, #8B5CF6)",
    get: (r) => r.vvix,
  },
  { key: "vix3m", label: "VIX3M", get: (r) => r.vix3m },
  { key: "spx", label: "SPX", color: "var(--text-primary)", get: (r) => r.spx },
  { key: "cor1m", label: "COR1M", get: (r) => r.cor1m },
  {
    key: "vix_vix3m_ratio",
    label: "VIX/VIX3M",
    fmt: (v) => v.toFixed(3),
    get: (r) => r.vix_vix3m_ratio,
  },
  { key: "realized_vol", label: "RVOL 20D", get: (r) => r.realized_vol },
  { key: "vrp", label: "VRP", get: (r) => r.vrp },
];

export default function CriSeriesGrids() {
  const marketState = useMarketHours();
  const { data: intraday } = useCriIntraday(marketState);

  const flatRows: CriIntradayPoint[] = [];
  const dividers: number[] = [];
  for (const s of intraday?.sessions ?? []) {
    if (flatRows.length > 0) dividers.push(flatRows.length);
    flatRows.push(...(s.points ?? []));
  }

  // Daily 90d series now live as sparklines inside the CRI cards above —
  // the standalone daily grid was removed in favour of that layout.
  return (
    <MultiPanelGrid
      title="CRI — Intraday, last 5 sessions"
      panels={PANELS}
      rows={flatRows}
      dividers={dividers}
      testId="cri-intraday-grid"
    />
  );
}
