import type { CockpitStateResponse } from "@/lib/api";
import type React from "react";
import { fmtDateTimeWithZone, fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";

type MatrixState = NonNullable<CockpitStateResponse>["state"];
type Direction = MatrixState["vanna_state"];

const DIMENSIONS = [
  ["Vanna", "vanna_state", "vanna_charm"],
  ["Charm", "charm_state", "vanna_charm"],
  ["Skew", "skew_state", "skew"],
  ["Term", "term_state", "term"],
  ["Flow + IM", "dim5_state", "im_vrp"],
  ["VRP", "vrp_state", "vrp_rv"],
] as const;

const INPUTS = [
  ["Skew z", "skew_25d_zscore_180d", "signed"],
  ["IV 30d", "iv_atm_30d", "decimal"],
  ["RV 30d", "rv_30d", "decimal"],
  ["VRP", "vrp", "signed"],
  ["VRP z", "vrp_zscore_60d", "signed"],
  ["IM %", "implied_move_pct", "decimal"],
  ["Front IV", "front_iv", "decimal"],
  ["Back IV", "back_iv", "decimal"],
  ["Front/back spread", "front_back_spread", "signed"],
  ["Pin sigma", "pin_distance_sigma", "decimal"],
  ["Flow imbalance 3d", "directional_imbalance_3d", "signed"],
  ["Skew 5d chg", "skew_25d_5d_change", "signed"],
  ["Skew term", "skew_term_structure", "signed"],
  ["Single bump", "single_point_bump_pct", "signed"],
  ["Curve slope", "full_curve_slope_pct", "signed"],
  ["Johnson slope", "term_johnson_slope_pc1", "signed"],
  ["ATM straddle", "atm_straddle_mid", "decimal"],
  ["Expected abs move", "implied_move_expected_abs", "decimal"],
  ["Event percentile", "implied_move_event_percentile", "decimal"],
  ["VRP z 252d", "vrp_zscore_252d", "signed"],
] as const;

export function StateTab({
  ticker,
  data,
}: {
  ticker: string;
  data: CockpitStateResponse | null;
}) {
  if (!data) {
    return (
      <section style={panelStyle}>
        <div style={emptyTitleStyle}>{ticker} STATE UNAVAILABLE</div>
        <p style={emptyCopyStyle}>
          No matrix snapshot has been written for this ticker yet.
        </p>
      </section>
    );
  }

  const { state, freshness } = data;
  const dim5 = dim5Vote(state.im_state, state.flow_state);
  const tier = tierMeta(state.consistency_tier);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section style={panelStyle}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            marginBottom: 16,
          }}
        >
          <div>
            <div style={labelStyle}>State date</div>
            <div style={valueStyle}>{state.market_date}</div>
          </div>
          <div
            style={{
              ...tierStyle,
              color: tier.color,
              borderColor: tier.color,
              background: tier.background,
            }}
          >
            {tier.label}
          </div>
        </div>
        <p
          style={{
            margin: "0 0 16px",
            color: "var(--text-secondary)",
            fontSize: 13,
            lineHeight: 1.5,
          }}
        >
          {tier.copy}
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: 10,
          }}
        >
          {DIMENSIONS.map(([label, key, freshnessKey]) => {
            const stateValue =
              key === "dim5_state" ? dim5 : (state[key] as Direction);
            const freshAt = freshness[freshnessKey] ?? null;
            return (
              <DimensionCell
                key={label}
                label={label}
                state={stateValue}
                freshAt={freshAt}
              />
            );
          })}
        </div>
      </section>

      <section style={panelStyle}>
        <div style={{ ...labelStyle, marginBottom: 12 }}>State gates</div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: 10,
          }}
        >
          <InputTile
            label="CLUSTER COVERAGE"
            value={state.cluster_coverage_ok ? "OK" : "BLOCKED"}
          />
          <InputTile
            label="THRESHOLD VERSION"
            value={String(state.threshold_version)}
          />
          <InputTile
            label="TERM CLASSIFICATION"
            value={formatLabel(state.term_classification)}
          />
          <InputTile
            label="VANNA READING"
            value={formatLabel(state.vanna_conditional_reading)}
          />
          <InputTile
            label="VANNA OI BIAS"
            value={formatLabel(state.vanna_oi_change_bias)}
          />
          <InputTile label="CHARM REGIME" value={formatLabel(state.charm_regime)} />
          <InputTile
            label="CHARM STRESS"
            value={state.charm_stress_override ? "YES" : "NO"}
          />
          <InputTile label="SKEW REGIME" value={formatLabel(state.skew_regime)} />
        </div>
      </section>

      <section style={panelStyle}>
        <div style={{ ...labelStyle, marginBottom: 12 }}>Inputs</div>
        <details>
          <summary
            style={{
              cursor: "pointer",
              color: "var(--text-primary)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
            }}
          >
            SHOW INPUTS
          </summary>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
              gap: 10,
              marginTop: 14,
            }}
          >
            {INPUTS.map(([label, key, format]) => {
              const value = toNum(state[key]);
              return (
                <div key={key} style={inputTileStyle}>
                  <div style={labelStyle}>{label}</div>
                  <div style={inputValueStyle}>
                    {format === "signed"
                      ? fmtSigned(value, 2)
                      : fmtDecimal(value, 2)}
                  </div>
                </div>
              );
            })}
          </div>
        </details>
      </section>
    </div>
  );
}

function InputTile({ label, value }: { label: string; value: string }) {
  return (
    <div style={inputTileStyle}>
      <div style={labelStyle}>{label}</div>
      <div style={inputValueStyle}>{value}</div>
    </div>
  );
}

function formatLabel(value: string | null | undefined): string {
  return value ? value.replaceAll("_", " ").toUpperCase() : "-";
}

function DimensionCell({
  label,
  state,
  freshAt,
}: {
  label: string;
  state: Direction;
  freshAt: string | null;
}) {
  const meta = directionMeta(state);
  return (
    <div
      style={{
        minHeight: 126,
        padding: 12,
        border: `1px solid ${meta.border}`,
        background: meta.background,
        backgroundImage:
          state === "stale"
            ? "repeating-linear-gradient(135deg, transparent 0 7px, rgba(148,163,184,0.10) 7px 9px)"
            : "none",
      }}
    >
      <div style={labelStyle}>{label}</div>
      <div style={{ ...dimValueStyle, color: meta.color }}>{meta.label}</div>
      <div
        style={{
          marginTop: 14,
          color: freshnessColor(freshAt),
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          lineHeight: 1.35,
        }}
      >
        {freshAt ? fmtDateTimeWithZone(freshAt) : "NO SOURCE"}
      </div>
    </div>
  );
}

function dim5Vote(im: Direction, flow: Direction): Direction {
  if (im === "stale" || flow === "stale") return "stale";
  if (im === flow) return im;
  return "neutral";
}

function directionMeta(state: Direction) {
  if (state === "vol_down") {
    return {
      label: "VOL DOWN",
      color: "var(--positive)",
      border: "rgba(5,173,152,0.58)",
      background: "rgba(5,173,152,0.10)",
    };
  }
  if (state === "vol_up") {
    return {
      label: "VOL UP",
      color: "var(--negative)",
      border: "rgba(232,93,108,0.62)",
      background: "rgba(232,93,108,0.10)",
    };
  }
  if (state === "neutral") {
    return {
      label: "NEUTRAL",
      color: "var(--text-secondary)",
      border: "var(--border-dim)",
      background: "var(--bg-panel)",
    };
  }
  return {
    label: "STALE",
    color: "var(--text-muted)",
    border: "var(--border-dim)",
    background: "var(--bg-panel)",
  };
}

function tierMeta(tier: MatrixState["consistency_tier"]) {
  if (tier === "strict") {
    return {
      label: "STRICT",
      color: "var(--positive)",
      background: "rgba(5,173,152,0.12)",
      copy: "All fresh voting dimensions agree.",
    };
  }
  if (tier === "strong") {
    return {
      label: "STRONG",
      color: "var(--signal-strong)",
      background: "rgba(15,207,181,0.10)",
      copy: "One fresh voting dimension is neutral; the directional read still holds.",
    };
  }
  if (tier === "weak") {
    return {
      label: "WEAK",
      color: "var(--warning)",
      background: "rgba(245,166,35,0.10)",
      copy: "The matrix has partial alignment with two neutral voting dimensions.",
    };
  }
  if (tier === "no_trade") {
    return {
      label: "NO-TRADE",
      color: "var(--negative)",
      background: "rgba(232,93,108,0.10)",
      copy: "The current voting dimensions conflict or lack dealer-flow confirmation.",
    };
  }
  return {
    label: "INSUFFICIENT-DATA",
    color: "var(--text-secondary)",
    background: "rgba(148,163,184,0.10)",
    copy: "At least two expected v1 dimensions are missing for this state date.",
  };
}

function freshnessColor(iso: string | null): string {
  if (!iso) return "var(--text-muted)";
  const ageMs = Date.now() - new Date(iso).getTime();
  return ageMs > 24 * 60 * 60 * 1000 ? "var(--warning)" : "var(--positive)";
}

const panelStyle: React.CSSProperties = {
  border: "1px solid var(--border-dim)",
  background: "var(--bg-panel)",
  padding: 16,
};

const labelStyle: React.CSSProperties = {
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
};

const valueStyle: React.CSSProperties = {
  marginTop: 4,
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontSize: 22,
  fontWeight: 700,
};

const tierStyle: React.CSSProperties = {
  padding: "8px 10px",
  border: "1px solid",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  fontWeight: 700,
  letterSpacing: 1,
};

const dimValueStyle: React.CSSProperties = {
  marginTop: 12,
  fontFamily: "var(--font-mono)",
  fontSize: 18,
  fontWeight: 800,
  letterSpacing: 0,
};

const inputTileStyle: React.CSSProperties = {
  minHeight: 72,
  border: "1px solid var(--border-dim)",
  background: "var(--bg-panel-raised)",
  padding: 10,
};

const inputValueStyle: React.CSSProperties = {
  marginTop: 8,
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontSize: 18,
  fontWeight: 700,
};

const emptyTitleStyle: React.CSSProperties = {
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontSize: 18,
  fontWeight: 800,
};

const emptyCopyStyle: React.CSSProperties = {
  margin: "10px 0 0",
  color: "var(--text-secondary)",
  fontSize: 13,
};
