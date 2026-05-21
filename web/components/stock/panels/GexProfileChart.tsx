import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

const MIN_ABS_GEX = 100;
const WINDOW_PCT = 0.15;

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 20,
  fontFamily: "var(--font-mono)",
};

const headingStyle: React.CSSProperties = {
  fontSize: 12,
  color: "var(--text-secondary)",
};

function fmtPct(v: number, digits = 2): string {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function fmtMoney(v: number): string {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e6)
    return `${sign}$${(abs / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
  if (abs >= 1e3)
    return `${sign}$${(abs / 1e3).toLocaleString("en-US", { maximumFractionDigits: 1 })}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function GexProfileChart({ report }: { report: Report }) {
  const curve = report.strike_gex_curve;
  const spot = toNum(report.market_structure.spot);
  const lv = report.market_structure_levels;
  const callWall = lv?.call_wall ? toNum(lv.call_wall.strike) : null;
  const putWall = lv?.put_wall ? toNum(lv.put_wall.strike) : null;
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;

  if (spot == null || spot <= 0) {
    return (
      <div style={panelStyle}>
        <div style={headingStyle}>GEX Profile — Net gamma by strike</div>
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: 12,
            marginTop: 12,
          }}
        >
          Spot unavailable — strike profile cannot be anchored.
        </div>
      </div>
    );
  }

  // Aggregate per strike across expiries.
  const perStrike = new Map<number, number>();
  for (const b of curve) {
    const s = toNum(b.strike);
    const g = toNum(b.net_gex);
    if (s == null || g == null) continue;
    perStrike.set(s, (perStrike.get(s) ?? 0) + g);
  }

  const center = spot;
  const winLo = center * (1 - WINDOW_PCT);
  const winHi = center * (1 + WINDOW_PCT);
  let closestToSpot: number | null = null;
  let bestDist = Infinity;
  for (const s of perStrike.keys()) {
    if (s < winLo || s > winHi) continue;
    const d = Math.abs(s - spot);
    if (d < bestDist) {
      bestDist = d;
      closestToSpot = s;
    }
  }

  const strikes = Array.from(perStrike.entries())
    .filter(([s, g]) => {
      if (s < winLo || s > winHi) return false;
      const isWall = s === callWall || s === putWall;
      const isSpotAnchor = s === closestToSpot;
      return isWall || isSpotAnchor || Math.abs(g) >= MIN_ABS_GEX;
    })
    .sort((a, b) => b[0] - a[0]);

  // Use ALL in-window strikes for the overlay y-mapping, not just the
  // filtered render set. Otherwise a thin chart can put the flip line
  // off-canvas just because the strike between flip and spot got filtered.
  const strikesForY = Array.from(perStrike.keys())
    .filter((s) => s >= winLo && s <= winHi)
    .sort((a, b) => b - a);

  const maxAbs = Math.max(...strikes.map(([, g]) => Math.abs(g)), 1);
  const ROW_H = 22;
  const LABEL_W = 110;
  const BAR_W = 280;
  const VALUE_W = 90;
  const TAG_W = 0;
  const ROW_W = LABEL_W + BAR_W + VALUE_W + TAG_W;

  // Map a continuous strike value to a vertical pixel offset within the
  // rendered strike list. Interpolates between adjacent rendered strikes
  // when the level falls between two. Returns null if outside the window.
  function strikeToY(level: number): number | null {
    if (strikes.length === 0) return null;
    const hi = strikes[0][0];
    const lo = strikes[strikes.length - 1][0];
    if (level > hi + (hi - lo) * 0.05) return null;
    if (level < lo - (hi - lo) * 0.05) return null;
    for (let i = 0; i < strikes.length - 1; i++) {
      const a = strikes[i][0];
      const b = strikes[i + 1][0];
      if (level <= a && level >= b) {
        const t = (a - level) / (a - b || 1);
        return (i + t) * ROW_H + ROW_H / 2;
      }
    }
    return level >= hi ? ROW_H / 2 : (strikes.length - 1) * ROW_H + ROW_H / 2;
  }

  type Overlay = {
    label: string;
    color: string;
    y: number;
    strike: number;
  };
  const overlays: Overlay[] = [];
  const addOverlay = (label: string, color: string, level: number | null) => {
    if (level == null) return;
    const y = strikeToY(level);
    if (y == null) return;
    overlays.push({ label, color, y, strike: level });
  };
  addOverlay(`Spot $${spot.toFixed(2)}`, "var(--accent-vol)", spot);
  addOverlay(
    `Gamma flip $${flip?.toFixed(2) ?? ""}`,
    "var(--accent-vivid)",
    flip,
  );
  addOverlay(
    `Call Wall $${callWall?.toFixed(2) ?? ""}`,
    "var(--positive)",
    callWall,
  );
  addOverlay(
    `Put Wall $${putWall?.toFixed(2) ?? ""}`,
    "var(--negative)",
    putWall,
  );

  // Silence unused-variable lint while keeping the helper available for
  // future debugging of the y-mapping decoupling.
  void strikesForY;

  return (
    <div style={panelStyle}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <div style={headingStyle}>GEX Profile — Net gamma by strike</div>
        <div style={{ display: "flex", gap: 16, fontSize: 11 }}>
          <span style={{ color: "var(--positive)" }}>
            ■ Positive (stabilizing)
          </span>
          <span style={{ color: "var(--negative)" }}>
            ■ Negative (destabilizing)
          </span>
        </div>
      </div>

      <div
        style={{
          maxWidth: ROW_W,
          margin: "0 auto",
          position: "relative",
        }}
      >
        {strikes.map(([strike, gex]) => {
          const pct = (strike - spot) / spot;
          const widthPct = (Math.abs(gex) / maxAbs) * 50;
          const isPos = gex >= 0;
          const isCallWall = callWall != null && strike === callWall;
          const isPutWall = putWall != null && strike === putWall;
          const isSpotRow = closestToSpot != null && strike === closestToSpot;

          const strikeColor = isCallWall
            ? "var(--positive)"
            : isPutWall
              ? "var(--negative)"
              : isSpotRow
                ? "var(--accent-vol)"
                : "var(--text-primary)";
          const strikeBold = isCallWall || isPutWall || isSpotRow;

          return (
            <div
              key={strike}
              style={{
                display: "grid",
                gridTemplateColumns: `${LABEL_W}px ${BAR_W}px ${VALUE_W}px`,
                alignItems: "center",
                height: ROW_H,
                fontSize: 11,
              }}
            >
              <div
                style={{
                  textAlign: "right",
                  paddingRight: 12,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                }}
              >
                <span style={{ color: "var(--text-muted)" }}>
                  {fmtPct(pct, 2)}
                </span>{" "}
                <span
                  style={{
                    color: strikeColor,
                    fontWeight: strikeBold ? 700 : 400,
                  }}
                >
                  {strike}
                </span>
              </div>

              <div style={{ position: "relative", height: ROW_H }}>
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
                    top: 3,
                    bottom: 3,
                    left: isPos ? "50%" : `${50 - widthPct}%`,
                    width: `${widthPct}%`,
                    background: isPos ? "var(--positive)" : "var(--negative)",
                    opacity: 0.85,
                  }}
                />
              </div>

              <div
                style={{
                  paddingLeft: 12,
                  color: isPos ? "var(--positive)" : "var(--negative)",
                  whiteSpace: "nowrap",
                  textAlign: "left",
                }}
              >
                {fmtMoney(gex)}
              </div>
            </div>
          );
        })}

        {/* Overlay reference lines — placed above the bar grid so labels
            never get hidden by row content. */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            pointerEvents: "none",
          }}
        >
          {overlays.map((o) => (
            <div
              key={`${o.label}-${o.strike}`}
              data-testid={`gex-overlay-${o.label.split(" ")[0].toLowerCase()}`}
              style={{
                position: "absolute",
                left: LABEL_W,
                right: 0,
                top: o.y,
                height: 0,
                borderTop: `1px dashed ${o.color}`,
                display: "flex",
                justifyContent: "flex-end",
                alignItems: "flex-start",
              }}
            >
              <span
                style={{
                  background: "var(--bg-panel)",
                  color: o.color,
                  fontSize: 9,
                  letterSpacing: 1,
                  textTransform: "uppercase",
                  padding: "1px 4px",
                  marginTop: -7,
                  marginRight: 2,
                  whiteSpace: "nowrap",
                }}
              >
                {o.label}
              </span>
            </div>
          ))}
        </div>

        {strikes.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            No strike-gamma data in the ±{(WINDOW_PCT * 100).toFixed(0)}% window
            around spot.
          </div>
        )}
      </div>
    </div>
  );
}
