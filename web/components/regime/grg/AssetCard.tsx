"use client";

import InfoTooltip from "../InfoTooltip";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "../primitives/format";
import { type GrgAsset } from "@/lib/regime/useGrgLive";
import { assetStateHelp, fmtGex, gexColor } from "./format";

export function AssetCard({ asset }: { asset: GrgAsset }) {
  const pill =
    asset.state === "CUSHION"
      ? "CUSHION"
      : asset.state === "WHIP"
        ? "WHIP"
        : "NEUTRAL";
  const pillColor =
    asset.state === "CUSHION"
      ? "var(--positive)"
      : asset.state === "WHIP"
        ? "var(--negative)"
        : "var(--text-muted)";
  return (
    <div className="section" data-testid={`grg-asset-${asset.ticker}`}>
      <div className="section-header">
        <div className="section-title">{asset.ticker}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              border: `1px solid ${pillColor}`,
              color: pillColor,
              borderRadius: 999,
              padding: "2px 10px",
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              letterSpacing: "1px",
            }}
          >
            {pill}
          </span>
          <InfoTooltip
            text={assetStateHelp(asset.state)}
            ariaLabel={`${pill} meaning`}
            triggerTestId={`grg-asset-state-info-${asset.ticker}`}
            contentTestId={`grg-asset-state-help-${asset.ticker}`}
          />
        </div>
      </div>
      <div className="section-body" style={{ padding: "12px" }}>
        <div
          style={{
            fontSize: 30,
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            color: gexColor(asset.net_gamma),
          }}
        >
          {fmtGex(asset.net_gamma)}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto",
            gap: "6px 12px",
            marginTop: 12,
            fontFamily: "var(--font-mono)",
            fontSize: 12,
          }}
        >
          <span style={{ color: "var(--text-muted)" }}>GAMMA Z</span>
          <span style={{ textAlign: "right" }}>
            {formatSignedNumber(asset.gamma_z)}
            {asset.gamma_z != null ? "σ" : ""}
          </span>
          <span style={{ color: "var(--text-muted)" }}>SPOT</span>
          <span style={{ textAlign: "right" }}>{formatNumber(asset.spot)}</span>
          <span style={{ color: "var(--text-muted)" }}>FLIP</span>
          <span style={{ textAlign: "right" }}>{formatNumber(asset.flip)}</span>
          <span style={{ color: "var(--text-muted)" }}>SPOT VS FLIP</span>
          <span style={{ textAlign: "right" }}>
            {formatPercent(asset.spot_vs_flip_pct)}
          </span>
        </div>
      </div>
    </div>
  );
}
