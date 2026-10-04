"use client";

import InfoTooltip from "../InfoTooltip";
import { formatSignedNumber } from "../primitives/format";
import { type GrgResponse } from "@/lib/regime/useGrgLive";
import type { components } from "@/lib/types";
import { METHODOLOGY, fmtGex } from "./format";
import { Tile } from "./Tile";

/* Hero: GRG headline residual + state, with the per-leg tiles. */
export function GrgHero({
  data,
  signal,
  assets,
  stateColor,
}: {
  data: GrgResponse;
  signal: components["schemas"]["GrgSignal"];
  assets: components["schemas"]["GrgAssets"];
  stateColor: string;
}) {
  return (
    <div className="section" data-testid="grg-hero">
      <div className="section-header">
        <div
          className="section-title"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          Gamma Rotation Gap
          <InfoTooltip
            text={METHODOLOGY}
            ariaLabel="GRG methodology"
            triggerTestId="grg-info"
          />
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span
            data-testid="grg-state-badge"
            style={{
              border: `1px solid ${stateColor}`,
              color: stateColor,
              borderRadius: 999,
              padding: "2px 10px",
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              letterSpacing: "1px",
            }}
          >
            {(signal.state_label ?? "Neutral").toUpperCase()}
          </span>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-muted)",
            }}
          >
            {data.data_date ?? ""}
          </span>
        </div>
      </div>
      <div
        className="section-body"
        style={{
          padding: 16,
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1fr) 2fr",
          gap: 16,
          alignItems: "center",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              letterSpacing: "1.5px",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            GRG Residual
          </div>
          <div
            data-testid="grg-residual"
            style={{
              fontSize: 56,
              fontWeight: 700,
              fontFamily: "var(--font-mono)",
              lineHeight: 1.05,
              color: stateColor,
            }}
          >
            {formatSignedNumber(signal.grg_z)}
            {signal.grg_z != null ? "σ" : ""}
          </div>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              marginTop: 6,
              color: stateColor,
            }}
          >
            {signal.state_label}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--text-secondary)",
              marginTop: 6,
              maxWidth: 380,
            }}
          >
            {signal.summary}
          </div>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 10,
          }}
        >
          <Tile
            label="SPY GEX"
            value={fmtGex(assets.SPY.net_gamma)}
            sub={`${formatSignedNumber(assets.SPY.gamma_z)}σ`}
          />
          <Tile
            label="TLT GEX"
            value={fmtGex(assets.TLT.net_gamma)}
            sub={`${formatSignedNumber(assets.TLT.gamma_z)}σ`}
          />
          <Tile
            label="Top Gate"
            value={`${signal.top_score ?? 0}/5`}
            sub={signal.top_watch ? "active" : "inactive"}
          />
          <Tile
            label="Bottom Gate"
            value={`${signal.bottom_score ?? 0}/5`}
            sub={signal.bottom_watch ? "active" : "inactive"}
          />
        </div>
      </div>
    </div>
  );
}
