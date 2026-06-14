"use client";

import GrgDivergenceChart from "./GrgDivergenceChart";
import InfoTooltip from "./InfoTooltip";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "./primitives/format";
import {
  useGrgLive,
  type GrgAsset,
  type GrgGate,
  type GrgResponse,
} from "@/lib/regime/useGrgLive";

const METHODOLOGY =
  "GRG = z-score of (SPY gamma-z − TLT gamma-z) over a 63-session window. " +
  "Positive dealer gamma cushions moves; negative gamma whips them. A SPY/TLT " +
  "divergence flags a cross-asset risk rotation. DESCRIPTIVE indicator — the " +
  "gamma→vol mechanic is peer-reviewed, but the cross-asset gap signal is an " +
  "unvalidated hypothesis (no forward-return backtest). See " +
  "docs/research/grg-gamma-rotation-gap.";

export function fmtGex(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "---";
  // radon shows a signed magnitude ("-702.1K", "+7.7M").
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

function gexColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-muted)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

export function gateColor(status: string): string {
  switch (status) {
    case "PASS":
      return "var(--positive)";
    case "FAIL":
      return "var(--negative)";
    default:
      return "var(--warning)";
  }
}

function residualColor(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return "var(--text-primary)";
  if (z <= -1) return "var(--negative)";
  if (z >= 1) return "var(--positive)";
  return "var(--text-primary)";
}

function Tile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div
      style={{
        padding: "10px 12px",
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "1.5px",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 20,
          fontWeight: 700,
          fontFamily: "var(--font-mono)",
          marginTop: 4,
        }}
      >
        {value}
      </div>
      {sub ? (
        <div
          style={{
            fontSize: 10,
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            marginTop: 2,
          }}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
}

function AssetCard({ asset }: { asset: GrgAsset }) {
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

function GatesPanel({ gates }: { gates: GrgGate[] }) {
  return (
    <div className="section" data-testid="grg-gates">
      <div className="section-header">
        <div className="section-title">Signal Gates</div>
      </div>
      <div
        className="section-body"
        style={{
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {gates.map((gate) => (
          <div
            key={gate.id}
            data-testid={`grg-gate-${gate.id}`}
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr auto",
              gap: 12,
              alignItems: "center",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                letterSpacing: "1px",
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              {gate.label}
            </span>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              {gate.copy}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                fontWeight: 700,
                color: gateColor(gate.status),
              }}
            >
              {gate.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function GrgSubTabView({ data }: { data: GrgResponse | null }) {
  if (!data || data.status === "empty" || !data.assets) {
    return (
      <div className="regime-empty" data-testid="grg-empty">
        No GRG snapshot yet. The scanner runs every 15 min (market hours +
        post-close settlement).
      </div>
    );
  }

  const signal = data.signal;
  const top_bottom = data.top_bottom;
  // Generated types mark default-valued fields optional. A non-empty snapshot
  // always carries signal + top_bottom; narrow them here (mirrors VcgSubTab).
  if (!signal || !top_bottom) {
    return (
      <div className="regime-empty" data-testid="grg-empty">
        No GRG snapshot yet. The scanner runs every 15 min (market hours +
        post-close settlement).
      </div>
    );
  }
  const assets = data.assets; // non-null: guarded by the early return above
  const gates = data.gates ?? [];
  const history = data.history ?? [];
  const topSide = top_bottom.top ?? { active: false, copy: "" };
  const botSide = top_bottom.bottom ?? { active: false, copy: "" };
  const stateColor =
    signal.state === "RISK_OFF_DIVERGENCE" || signal.state === "DUAL_WHIP"
      ? "var(--negative)"
      : signal.state === "RISK_ON_DIVERGENCE" || signal.state === "DUAL_CUSHION"
        ? "var(--positive)"
        : "var(--text-muted)";

  return (
    <div className="gex-panel" data-testid="grg-panel">
      {/* Hero */}
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
                color: residualColor(signal.grg_z),
              }}
            >
              {formatSignedNumber(signal.grg_z)}
              {signal.grg_z != null ? "σ" : ""}
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 6 }}>
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

      {/* Asset cards + chart */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1fr) 2fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <AssetCard asset={assets.SPY} />
          <AssetCard asset={assets.TLT} />
        </div>
        <GrgDivergenceChart history={history} />
      </div>

      {/* Top / Bottom identification */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <div className="section" data-testid="grg-top">
          <div className="section-header">
            <div className="section-title">Top Identification</div>
          </div>
          <div
            className="section-body"
            style={{
              padding: 12,
              fontSize: 12,
              color: "var(--text-secondary)",
            }}
          >
            {topSide.copy}
            <div
              style={{
                marginTop: 8,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: topSide.active ? "var(--warning)" : "var(--text-muted)",
              }}
            >
              {topSide.active ? "TOP WATCH ACTIVE" : "NO CONFIRMED TOP WATCH"}
            </div>
          </div>
        </div>
        <div className="section" data-testid="grg-bottom">
          <div className="section-header">
            <div className="section-title">Bottom Identification</div>
          </div>
          <div
            className="section-body"
            style={{
              padding: 12,
              fontSize: 12,
              color: "var(--text-secondary)",
            }}
          >
            {botSide.copy}
            <div
              style={{
                marginTop: 8,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: botSide.active ? "var(--warning)" : "var(--text-muted)",
              }}
            >
              {botSide.active
                ? "BOTTOM WATCH ACTIVE"
                : "NO CONFIRMED BOTTOM WATCH"}
            </div>
          </div>
        </div>
      </div>

      {/* Gates */}
      <div style={{ marginTop: 16 }}>
        <GatesPanel gates={gates} />
      </div>
    </div>
  );
}

export default function GrgSubTab() {
  const { data } = useGrgLive();
  return <GrgSubTabView data={data} />;
}
