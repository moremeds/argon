import type { components } from "@/lib/types";
import {
  fmtSignedCompactMoney,
  fmtSignedPct,
  toNum,
} from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const headlineStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
  color: "var(--text-primary)",
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--text-secondary)",
  fontStyle: "italic",
};

const tilesRowStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(5, 1fr)",
  gap: 12,
  borderTop: "1px solid var(--border-dim)",
  paddingTop: 10,
};

const tileLabel: React.CSSProperties = {
  ...labelStyle,
  fontSize: 9,
};

const tileValue: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  marginTop: 2,
};

function deltaColor(v: number | null | undefined): string {
  if (v == null) return "var(--text-muted)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

function regimeColor(label: string | null | undefined): string {
  if (label === "dampening") return "var(--positive)";
  if (label === "amplifying") return "var(--negative)";
  return "var(--warning)";
}

export function MagnetGammaBar({ report }: { report: Report }) {
  const regime = report.dealer_regime;
  if (!regime) return null;

  const spot = toNum(report.market_structure?.spot);
  const netGex = toNum(report.market_structure?.net_gex);
  const prevClose = toNum(regime.prev_close_net_gex);
  const odte = toNum(regime.odte_net_gex);

  const lv = report.market_structure_levels;
  const callWall = lv?.call_wall ? toNum(lv.call_wall.strike) : null;
  const callWallGex = lv?.call_wall ? toNum(lv.call_wall.net_gex) : null;
  const putWall = lv?.put_wall ? toNum(lv.put_wall.strike) : null;
  const putWallGex = lv?.put_wall ? toNum(lv.put_wall.net_gex) : null;
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;

  // Top wall = larger |gex|; ties go to the call wall.
  const useCallTop =
    (callWallGex != null ? Math.abs(callWallGex) : 0) >=
    (putWallGex != null ? Math.abs(putWallGex) : 0);
  const topWallStrike = useCallTop ? callWall : putWall;
  const topWallGex = useCallTop ? callWallGex : putWallGex;

  const deltaVsPrev =
    netGex != null && prevClose != null ? netGex - prevClose : null;
  const deltaPct =
    netGex != null && prevClose != null && prevClose !== 0
      ? deltaVsPrev! / Math.abs(prevClose)
      : null;
  const flipDistPct =
    flip != null && spot != null && spot > 0 ? (flip - spot) / spot : null;

  return (
    <div style={panelStyle} data-testid="magnet-gamma-bar">
      <div style={labelStyle}>
        <span style={{ color: "var(--accent-warm)" }}>MAGNET</span>{" "}
        <span style={{ color: "var(--text-muted)" }}>· GAMMA</span>
      </div>
      <div
        style={{ ...headlineStyle, color: regimeColor(regime.label) }}
        data-testid="magnet-gamma-headline"
      >
        {regime.headline}
      </div>
      {regime.subtitle && (
        <div style={subtitleStyle} data-testid="magnet-gamma-subtitle">
          {regime.subtitle}
        </div>
      )}

      <div style={tilesRowStyle}>
        <div>
          <div style={tileLabel}>Net dealer Γ</div>
          <div style={{ ...tileValue, color: deltaColor(netGex) }}>
            {fmtSignedCompactMoney(netGex, {
              digits: 2,
              fixed: true,
            })}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              {netGex == null ? "" : netGex >= 0 ? "Long" : "Short"}
            </span>
          </div>
        </div>

        <div>
          <div style={tileLabel}>Γ vs prev close</div>
          <div style={{ ...tileValue, color: deltaColor(deltaVsPrev) }}>
            {fmtSignedCompactMoney(deltaVsPrev, {
              digits: 2,
              fixed: true,
            })}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              {fmtSignedPct(deltaPct, 0)}
            </span>
          </div>
        </div>

        <div>
          <div style={tileLabel}>Top wall</div>
          <div style={tileValue}>
            ${topWallStrike?.toFixed(2) ?? "—"}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              {fmtSignedCompactMoney(topWallGex, {
                digits: 2,
                fixed: true,
              })}
            </span>
          </div>
        </div>

        <div>
          <div style={tileLabel}>Flip distance</div>
          <div
            style={{ ...tileValue, color: deltaColor(flipDistPct) }}
            data-testid="magnet-gamma-flip-dist"
          >
            {fmtSignedPct(flipDistPct, 1)}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              at ${flip?.toFixed(2) ?? "—"}
            </span>
          </div>
        </div>

        <div>
          <div style={tileLabel}>0–1d rolls off</div>
          <div style={{ ...tileValue, color: deltaColor(odte) }}>
            {fmtSignedCompactMoney(odte, {
              digits: 2,
              fixed: true,
            })}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              by tomorrow
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
