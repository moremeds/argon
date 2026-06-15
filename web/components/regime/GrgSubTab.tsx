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
  type GrgEvent,
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

// Explainer for the per-asset badge — scoped to the asset's actual state so
// a WHIP card shows only the whip meaning, a CUSHION card only the cushion.
export function assetStateHelp(state: string | null | undefined): string {
  switch (state) {
    case "CUSHION":
      return "CUSHION: dealer gamma is positive — hedging mechanically dampens this asset's moves (stabilizing).";
    case "WHIP":
      return "WHIP: dealer gamma is negative — hedging mechanically amplifies this asset's moves (destabilizing).";
    default:
      return "NEUTRAL: dealer gamma is near zero — little mechanical push on this asset's moves.";
  }
}

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

// Regime sentiment color, shared by the hero residual/label and the event rows.
export function pairStateColor(state: string | null | undefined): string {
  if (state === "RISK_OFF_DIVERGENCE" || state === "DUAL_WHIP")
    return "var(--negative)";
  if (state === "RISK_ON_DIVERGENCE" || state === "DUAL_CUSHION")
    return "var(--positive)";
  return "var(--text-muted)";
}

export function shortState(state: string | null | undefined): string {
  switch (state) {
    case "RISK_ON_DIVERGENCE":
      return "RISK-ON";
    case "RISK_OFF_DIVERGENCE":
      return "RISK-OFF";
    case "DUAL_WHIP":
      return "DUAL WHIP";
    case "DUAL_CUSHION":
      return "DUAL CUSHION";
    default:
      return "NEUTRAL";
  }
}

// GRG σ colored by sign (no dead band) — a -0.79σ reads red, +2.1σ reads green.
export function sigmaColor(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return "var(--text-muted)";
  if (z < 0) return "var(--negative)";
  if (z > 0) return "var(--positive)";
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

function EventRow({ ev }: { ev: GrgEvent }) {
  return (
    <div
      data-testid="grg-event-row"
      style={{
        padding: "8px 0",
        borderBottom: "1px solid var(--border-dim)",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 64px 1fr auto",
          gap: 8,
          alignItems: "baseline",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        <span style={{ color: "var(--text-secondary)" }}>{ev.date}</span>
        <span
          style={{
            color: sigmaColor(ev.grg_z),
            textAlign: "right",
            fontWeight: 700,
          }}
        >
          {formatSignedNumber(ev.grg_z)}
          {ev.grg_z != null ? "σ" : ""}
        </span>
        <span
          style={{
            color: pairStateColor(ev.pair_state),
            letterSpacing: "0.5px",
          }}
        >
          {shortState(ev.pair_state)}
        </span>
        <span style={{ color: "var(--text-muted)" }}>
          {ev.tier != null ? `T${ev.tier}` : "—"}
        </span>
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--text-muted)",
          marginTop: 2,
        }}
      >
        SPY {fmtGex(ev.spy_net_gamma)} · TLT {fmtGex(ev.tlt_net_gamma)}
      </div>
    </div>
  );
}

function EventsColumn({
  title,
  testid,
  events,
  emptyCopy,
}: {
  title: string;
  testid: string;
  events: GrgEvent[];
  emptyCopy: string;
}) {
  return (
    <div className="section" data-testid={testid}>
      <div className="section-header">
        <div className="section-title">{title}</div>
      </div>
      <div className="section-body" style={{ padding: 12 }}>
        {events.length === 0 ? (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-muted)",
            }}
          >
            {emptyCopy}
          </div>
        ) : (
          events.slice(0, 5).map((ev) => <EventRow key={ev.date} ev={ev} />)
        )}
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
  const tops = data.events?.tops ?? [];
  const bottoms = data.events?.bottoms ?? [];
  const topSide = top_bottom.top ?? { active: false, copy: "" };
  const botSide = top_bottom.bottom ?? { active: false, copy: "" };
  const stateColor = pairStateColor(signal.state);

  return (
    <div
      className="section gex-panel"
      data-testid="grg-panel"
      style={{ padding: 16 }}
    >
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

      {/* Recent gate-confirmed tops / bottoms (YTD history of the signal) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <EventsColumn
          title="Recent Tops"
          testid="grg-recent-tops"
          events={tops}
          emptyCopy="No gate-confirmed tops year-to-date."
        />
        <EventsColumn
          title="Recent Bottoms"
          testid="grg-recent-bottoms"
          events={bottoms}
          emptyCopy="No gate-confirmed bottoms year-to-date."
        />
      </div>
      <div
        style={{
          marginTop: 6,
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
        }}
      >
        Gate-confirmed TOP_WATCH / BOTTOM_WATCH days, YTD. Spot-vs-flip excluded
        — UW history carries no per-day gamma flip.
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
