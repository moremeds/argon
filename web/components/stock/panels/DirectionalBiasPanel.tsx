import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type HistoryRow = components["schemas"]["StockHistoryRow"];

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  marginBottom: 12,
};

const biasColors: Record<string, string> = {
  BULL: "var(--positive)",
  BEAR: "var(--negative)",
  CAUTIOUS_BULL: "var(--warning)",
  CAUTIOUS_BEAR: "var(--warning)",
  NEUTRAL: "var(--text-secondary)",
};

const biasArrows: Record<string, string> = {
  BULL: "↗",
  BEAR: "↘",
  CAUTIOUS_BULL: "↗",
  CAUTIOUS_BEAR: "↘",
  NEUTRAL: "→",
};

function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function classifyClient(
  spot: number | null,
  flip: number | null,
  netGex: number | null,
): string {
  if (spot == null || flip == null || netGex == null) return "NEUTRAL";
  const above = spot > flip;
  const stab = netGex > 0;
  if (above && stab) return "BULL";
  if (!above && !stab) return "BEAR";
  return above ? "CAUTIOUS_BULL" : "CAUTIOUS_BEAR";
}

function buildRationale(report: Report): string[] {
  const m = report.market_structure;
  const lv = report.market_structure_levels;
  const spot = toNum(m.spot);
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;
  const netGex = toNum(m.net_gex);
  const maxMagnet = lv?.max_magnet ? toNum(lv.max_magnet.strike) : null;

  const out: string[] = [];
  if (spot != null && flip != null) {
    out.push(
      spot > flip
        ? `Spot above flip (${fmtNum(flip, 2)})`
        : `Spot below flip (${fmtNum(flip, 2)})`,
    );
  }
  if (netGex != null) {
    out.push(
      netGex > 0
        ? "Net GEX positive (stabilizing)"
        : "Net GEX negative (destabilizing)",
    );
  }
  if (maxMagnet != null && spot != null) {
    out.push(
      maxMagnet > spot
        ? `Max magnet at ${fmtNum(maxMagnet, 2)} pulls higher`
        : `Max magnet at ${fmtNum(maxMagnet, 2)} pulls lower`,
    );
  }
  return out;
}

function flipMigration(rows: HistoryRow[]): string {
  // Last 5 daily flips, oldest → newest with arrows.
  const recent = rows.slice(0, 5).reverse();
  const flips = recent
    .map((r) => (r.gex_flip != null ? fmtNum(Number(r.gex_flip), 2) : "—"))
    .join(" → ");
  return flips || "—";
}

export function DirectionalBiasPanel({
  report,
  history,
}: {
  report: Report;
  history: HistoryRow[];
}) {
  const m = report.market_structure;
  const lv = report.market_structure_levels;
  const spot = toNum(m.spot);
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;
  const netGex = toNum(m.net_gex);
  const bias = classifyClient(spot, flip, netGex);
  const color = biasColors[bias] ?? biasColors.NEUTRAL;
  const arrow = biasArrows[bias] ?? "→";
  const rationale = buildRationale(report);

  // "Days above flip": consecutive history rows (newest-first) where spot > flip.
  let consecutive = 0;
  for (const r of history) {
    const rs = toNum(r.spot);
    const rf = toNum(r.gex_flip);
    if (rs == null || rf == null) break;
    if (rs > rf) consecutive++;
    else break;
  }

  return (
    <div style={panelStyle}>
      <div style={labelStyle}>Directional Bias</div>
      <div
        style={{
          fontSize: 36,
          fontWeight: 700,
          color,
          letterSpacing: 1,
          marginBottom: 12,
        }}
      >
        {bias.replace("_", " ")} <span style={{ fontSize: 24 }}>{arrow}</span>
      </div>

      <ul
        style={{
          fontSize: 12,
          color: "var(--text-secondary)",
          paddingLeft: 16,
          margin: 0,
          marginBottom: 12,
          lineHeight: 1.7,
        }}
      >
        {rationale.map((r) => (
          <li key={r}>{r}</li>
        ))}
        {consecutive > 0 && (
          <li>
            {consecutive} consecutive {consecutive === 1 ? "day" : "days"} above
            flip
          </li>
        )}
      </ul>

      <div
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          borderTop: "1px solid var(--border-dim)",
          paddingTop: 8,
        }}
      >
        Flip migration: {flipMigration(history)}
      </div>
    </div>
  );
}
