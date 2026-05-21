"use client";

import type { RegimeDealerResponse } from "@/lib/api";

const PANEL: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  display: "flex",
  flexDirection: "column",
  gap: 12,
  width: "100%",
  maxWidth: 360,
};

const SECTION_LABEL: React.CSSProperties = {
  fontSize: 9,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

function regimeColor(label: string | null | undefined): string {
  if (label === "dampening") return "var(--positive)";
  if (label === "amplifying") return "var(--negative)";
  return "var(--warning)";
}

function fmtScore(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(2)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function SubBar({
  label,
  score,
}: {
  label: string;
  score: number | null | undefined;
}) {
  const v = score ?? 0;
  const color = v >= 0 ? "var(--positive)" : "var(--negative)";
  const widthPct = Math.min(Math.abs(v) * 100, 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ width: 14, fontWeight: 700 }}>{label}</span>
      <div style={{ position: "relative", flex: 1, height: 6 }}>
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: 0,
            bottom: 0,
            width: 1,
            background: "var(--border-dim)",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 1,
            bottom: 1,
            left: v >= 0 ? "50%" : `${50 - widthPct / 2}%`,
            width: `${widthPct / 2}%`,
            background: color,
          }}
        />
      </div>
      <span style={{ width: 50, textAlign: "right", color, fontSize: 11 }}>
        {fmtScore(v)}
      </span>
    </div>
  );
}

export function VolatilityRegimePanel({
  data,
}: {
  data: RegimeDealerResponse | null;
}) {
  if (!data || data.status !== "ok") {
    return (
      <div style={PANEL}>
        <div style={SECTION_LABEL}>Volatility Regime</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          No dealer regime data yet.
        </div>
      </div>
    );
  }

  const signal = data.signal ?? {
    label: "neutral" as const,
    score: 0,
    gamma_score: 0,
    vanna_score: 0,
    charm_score: 0,
    headline: "",
    subtitle: "",
  };
  const closest = data.closest_levels ?? [];
  const odte_gex = data.odte_gex ?? null;
  const odte_share_pct = data.odte_share_pct ?? null;
  const gamma_decay = data.gamma_decay ?? [];

  // Show only "nearest" rank to keep the right column compact; dominant is
  // also available on the wire if a future view wants to expose it.
  const closestNearest = closest.filter((l) => l.rank_kind === "nearest");

  const labelColor = regimeColor(signal.label);
  const sliderScore = signal.score ?? 0;
  const sliderPct = ((sliderScore + 1) / 2) * 100;

  const decayMaxAbs = Math.max(
    ...gamma_decay.map((b) => Math.abs(b.net_gex ?? 0)),
    1,
  );

  return (
    <div style={PANEL} data-testid="volatility-regime-panel">
      {/* Regime header */}
      <div>
        <div style={SECTION_LABEL}>Volatility Regime</div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: labelColor,
            textTransform: "capitalize",
          }}
          data-testid="regime-label"
        >
          {signal.label}
        </div>
        {signal.subtitle && (
          <div
            style={{
              fontSize: 11,
              color: "var(--text-secondary)",
              marginTop: 4,
            }}
          >
            {signal.subtitle}
          </div>
        )}
      </div>

      {/* Amplifying ↔ Dampening slider */}
      <div>
        <div
          style={{
            position: "relative",
            height: 8,
            background:
              "linear-gradient(90deg, var(--negative) 0%, var(--warning) 50%, var(--positive) 100%)",
            borderRadius: 4,
          }}
        >
          <div
            style={{
              position: "absolute",
              left: `${sliderPct}%`,
              top: -2,
              bottom: -2,
              width: 2,
              background: "var(--text-primary)",
            }}
          />
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 10,
            color: "var(--text-muted)",
            marginTop: 4,
          }}
        >
          <span>Amplifying</span>
          <span>Dampening</span>
        </div>
      </div>

      {/* Γ / V / C sub-bars */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <SubBar label="Γ" score={signal.gamma_score} />
        <SubBar label="V" score={signal.vanna_score} />
        <SubBar label="C" score={signal.charm_score} />
      </div>

      {/* Closest levels */}
      <div style={{ borderTop: "1px solid var(--border-dim)", paddingTop: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <div style={SECTION_LABEL}>Closest Levels</div>
          <div style={{ ...SECTION_LABEL, fontStyle: "italic" }}>
            by proximity
          </div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            marginTop: 6,
          }}
        >
          {closestNearest.map((l) => {
            const directionGlyph =
              l.direction === "up" ? "↑" : l.direction === "down" ? "↓" : "·";
            const color =
              l.role === "support"
                ? "var(--positive)"
                : l.role === "resistance"
                  ? "var(--warning)"
                  : l.role === "accelerator"
                    ? "var(--negative)"
                    : "var(--text-primary)";
            return (
              <div
                key={`${l.label}-${l.strike}`}
                data-testid="closest-level-row"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span style={{ color, fontWeight: 700 }}>
                    {l.label} {directionGlyph} @ ${l.strike.toFixed(2)}
                  </span>
                  <span style={{ color, fontSize: 10, letterSpacing: 1 }}>
                    {l.role?.toUpperCase()}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                  {fmtPct(l.distance_pct, 1)} from spot · {fmtMoney(l.gamma)}{" "}
                  gamma
                </div>
              </div>
            );
          })}
          {closestNearest.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
              No levels in range yet.
            </div>
          )}
        </div>
      </div>

      {/* 0DTE GEX */}
      <div style={{ borderTop: "1px solid var(--border-dim)", paddingTop: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <div style={SECTION_LABEL}>0DTE GEX</div>
          <div style={SECTION_LABEL}>expires today</div>
        </div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: (odte_gex ?? 0) >= 0 ? "var(--positive)" : "var(--negative)",
            marginTop: 4,
          }}
          data-testid="odte-gex"
        >
          {fmtMoney(odte_gex)}{" "}
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>
            {odte_share_pct != null
              ? `${Math.round(odte_share_pct * 100)}% of chain`
              : ""}
          </span>
        </div>
      </div>

      {/* Gamma decay */}
      <div style={{ borderTop: "1px solid var(--border-dim)", paddingTop: 10 }}>
        <div style={SECTION_LABEL}>Gamma Decay Over Time</div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            marginTop: 6,
          }}
        >
          {gamma_decay.map((b) => {
            const widthPct = (Math.abs(b.net_gex ?? 0) / decayMaxAbs) * 100;
            const color =
              (b.net_gex ?? 0) >= 0 ? "var(--positive)" : "var(--negative)";
            return (
              <div
                key={b.expiry}
                data-testid="decay-row"
                style={{
                  display: "grid",
                  gridTemplateColumns: "40px 90px 1fr 90px",
                  alignItems: "center",
                  fontSize: 11,
                  gap: 8,
                }}
              >
                <span style={{ color, fontWeight: 700 }}>{b.dte}d</span>
                <span style={{ color: "var(--text-muted)" }}>{b.expiry}</span>
                <div
                  style={{
                    position: "relative",
                    height: 4,
                    background: "var(--bg-panel)",
                    border: "1px solid var(--border-dim)",
                    borderRadius: 2,
                  }}
                >
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: 0,
                      bottom: 0,
                      width: `${widthPct}%`,
                      background: color,
                    }}
                  />
                </div>
                <span style={{ textAlign: "right", color }}>
                  {fmtMoney(b.net_gex)}
                </span>
              </div>
            );
          })}
          {gamma_decay.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
              No expiries with gamma data.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
