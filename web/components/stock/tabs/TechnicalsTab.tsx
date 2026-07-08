"use client";

import { useEffect, useState } from "react";
import { api, type TechnicalsResponse } from "@/lib/api";
import { TechnicalsKpiStrip } from "../panels/TechnicalsKpiStrip";
import { TechnicalsAnchorChart } from "../panels/TechnicalsAnchorChart";
import { TechnicalsZChart } from "../panels/TechnicalsZChart";
import { ForwardReturnTable } from "../panels/ForwardReturnTable";
import { TechnicalsDetailPanels } from "../panels/TechnicalsDetailPanels";

type State = {
  ticker: string;
  data: TechnicalsResponse | null;
  error: string | null;
};

export function TechnicalsTab({ ticker }: { ticker: string }) {
  // State is keyed to the ticker so a stale response never renders after a
  // ticker switch, and we avoid a synchronous setState in the effect body
  // (react-hooks/set-state-in-effect).
  const [state, setState] = useState<State>({
    ticker,
    data: null,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    api
      .technicals(ticker)
      .then((r) => {
        if (!cancelled) setState({ ticker, data: r, error: null });
      })
      .catch((e) => {
        if (!cancelled) setState({ ticker, data: null, error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const ready = state.ticker === ticker;
  const error = ready ? state.error : null;
  const data = ready ? state.data : null;

  if (error) {
    return (
      <div style={{ color: "var(--negative)", padding: 16 }}>
        Technicals failed to load: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div style={{ color: "var(--text-muted)", padding: 16 }}>
        Loading technicals…
      </div>
    );
  }
  if (data.backfill_status === "empty") {
    return (
      <div style={{ color: "var(--text-muted)", padding: 16 }}>
        No technicals history for {ticker} yet — populated by the nightly
        refresh (or run scripts/backfill/technicals_refresh_backfill.py).
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <TechnicalsKpiStrip data={data} />
      <TechnicalsAnchorChart data={data} />
      <TechnicalsZChart data={data} />
      <ForwardReturnTable data={data} />
      <TechnicalsDetailPanels data={data} />
    </div>
  );
}
