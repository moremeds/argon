import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

// Drop strikes whose aggregated net_gex is too small to render as a meaningful
// bar — keeps the chart from looking like a wall of "+$0" rows on quiet days.
const MIN_ABS_GEX = 100;
// Window around spot to render. Wider = more context, narrower = denser bars.
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

  // 1) Aggregate per strike across expiries.
  const perStrike = new Map<number, number>();
  for (const b of curve) {
    const s = toNum(b.strike);
    const g = toNum(b.net_gex);
    if (s == null || g == null) continue;
    perStrike.set(s, (perStrike.get(s) ?? 0) + g);
  }

  // 2) Pre-compute the strike closest to spot — independent of the gex
  // threshold, so spot is always represented even when its strike has thin
  // gamma. We restrict the search to the render window to avoid picking up
  // far-OTM noise on stocks with sparse chains.
  const center = spot ?? 0;
  const winLo = center * (1 - WINDOW_PCT);
  const winHi = center * (1 + WINDOW_PCT);
  let closestToSpot: number | null = null;
  if (spot != null) {
    let bestDist = Infinity;
    for (const s of perStrike.keys()) {
      if (s < winLo || s > winHi) continue;
      const d = Math.abs(s - spot);
      if (d < bestDist) {
        bestDist = d;
        closestToSpot = s;
      }
    }
  }

  // 3) Filter: keep strikes within ±WINDOW_PCT of spot AND with |gex| >= threshold.
  // Always keep walls AND the spot-anchor strike even if below threshold.
  const strikes = Array.from(perStrike.entries())
    .filter(([s, g]) => {
      if (s < winLo || s > winHi) return false;
      const isWall = s === callWall || s === putWall;
      const isSpotAnchor = s === closestToSpot;
      return isWall || isSpotAnchor || Math.abs(g) >= MIN_ABS_GEX;
    })
    .sort((a, b) => b[0] - a[0]); // descending — highest strike at top

  const maxAbs = Math.max(...strikes.map(([, g]) => Math.abs(g)), 1);
  const ROW_H = 22;
  const LABEL_W = 110;
  const BAR_W = 280;
  const VALUE_W = 90;
  const TAG_W = 110;

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
          maxWidth: LABEL_W + BAR_W + VALUE_W + TAG_W,
          margin: "0 auto",
        }}
      >
        {strikes.map(([strike, gex]) => {
          const pct = spot != null ? (strike - spot) / spot : 0;
          const widthPct = (Math.abs(gex) / maxAbs) * 50;
          const isPos = gex >= 0;
          const isCallWall = callWall != null && strike === callWall;
          const isPutWall = putWall != null && strike === putWall;
          const isSpotRow = closestToSpot != null && strike === closestToSpot;

          // Strike-label color: wall identity wins (green/red) for the level
          // semantics; spot-only rows get yellow. Spot rows always carry a
          // dashed yellow border, so a green/red wall that also is spot is
          // unambiguous (green text + yellow border + both tags stacked).
          const strikeColor = isCallWall
            ? "var(--positive)"
            : isPutWall
              ? "var(--negative)"
              : isSpotRow
                ? "var(--warning)"
                : "var(--text-primary)";
          const strikeBold = isCallWall || isPutWall || isSpotRow;

          const tags: { label: string; color: string }[] = [];
          if (isCallWall)
            tags.push({ label: "◀ CALL WALL", color: "var(--positive)" });
          if (isPutWall)
            tags.push({ label: "◀ PUT WALL", color: "var(--negative)" });
          if (isSpotRow)
            tags.push({ label: "◀ SPOT", color: "var(--warning)" });

          return (
            <div
              key={strike}
              style={{
                display: "grid",
                gridTemplateColumns: `${LABEL_W}px ${BAR_W}px ${VALUE_W}px ${TAG_W}px`,
                alignItems: "center",
                height: ROW_H,
                fontSize: 11,
                borderTop: isSpotRow ? "1px dashed var(--warning)" : undefined,
                borderBottom: isSpotRow
                  ? "1px dashed var(--warning)"
                  : undefined,
              }}
            >
              {/* Strike label */}
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

              {/* Bar canvas with centerline */}
              <div
                style={{
                  position: "relative",
                  height: ROW_H,
                }}
              >
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

              {/* $ value */}
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

              {/* Tag column — stacks multiple labels when a strike is both a
                  wall and the spot anchor. Each tag carries its own color so
                  the reader can match it to the strike-label color at a glance. */}
              <div
                style={{
                  paddingLeft: 8,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                  gap: 1,
                  whiteSpace: "nowrap",
                }}
              >
                {tags.map((t) => (
                  <div
                    key={t.label}
                    style={{
                      fontSize: 9,
                      letterSpacing: 1,
                      color: t.color,
                      lineHeight: 1.2,
                    }}
                  >
                    {t.label}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
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
