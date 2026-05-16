import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type Level = components["schemas"]["uw_scan__models__GexLevel"];

const tileStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: "12px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const valueStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontWeight: 700,
  fontSize: 22,
  color: "var(--text-primary)",
  lineHeight: 1,
};

const subStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  color: "var(--text-muted)",
};

function signedColor(v: number | null): string {
  if (v == null) return "var(--text-primary)";
  if (v > 0) return "var(--positive)";
  if (v < 0) return "var(--negative)";
  return "var(--text-primary)";
}

function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtMoneyCompact(v: number | null): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e9)
    return `${sign}$${(abs / 1e9).toLocaleString("en-US", { maximumFractionDigits: 1 })}B`;
  if (abs >= 1e6)
    return `${sign}$${(abs / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
  if (abs >= 1e3)
    return `${sign}$${(abs / 1e3).toLocaleString("en-US", { maximumFractionDigits: 1 })}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function fmtPct(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function Tile({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div style={tileStyle}>
      <div style={labelStyle}>{label}</div>
      <div style={{ ...valueStyle, color: valueColor ?? valueStyle.color }}>
        {value}
      </div>
      <div style={subStyle}>{sub ?? " "}</div>
    </div>
  );
}

function levelSub(level: Level | null | undefined): string {
  if (!level) return "—";
  const pct = toNum(level.pct_from_spot);
  const sens = toNum(level.gamma_per_dollar);
  const pctStr = pct != null ? fmtPct(pct, 2) : "—";
  const sensStr = sens != null ? `${fmtMoneyCompact(sens)} per $1` : "—";
  return `${pctStr} — ${sensStr}`;
}

export function GexLevelTiles({ report }: { report: Report }) {
  const m = report.market_structure;
  const a = report.aggregates;
  const v = report.volatility;
  const lv = report.market_structure_levels;

  const spot = toNum(m.spot);
  const netGex = toNum(m.net_gex);
  // NET DEX in $: (call_dex_oi + put_dex_oi) * spot. The signs of the two
  // OI components already encode dealer-side direction.
  const callDex = toNum(m.total_call_dex_oi);
  const putDex = toNum(m.total_put_dex_oi);
  const netDexDollars =
    callDex != null && putDex != null && spot != null
      ? (callDex + putDex) * spot
      : null;
  const iv = toNum(v.iv);
  const ivRank = toNum(v.iv_rank);
  const pcrVol = toNum(a?.pcr_vol);
  const flip = lv?.gex_flip;
  const flipPct = toNum(flip?.pct_from_spot);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Top row: 6 wide tiles */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <Tile label="Spot" value={fmtNum(spot, 2)} sub=" " />
        <Tile
          label="GEX Flip"
          value={flip ? fmtNum(toNum(flip.strike), 2) : "—"}
          sub={flipPct != null ? `${fmtPct(flipPct, 2)} from spot` : "—"}
          valueColor="var(--warning)"
        />
        <Tile
          label="Net GEX"
          value={netGex != null ? fmtMoneyCompact(netGex) : "—"}
          valueColor={signedColor(netGex)}
        />
        <Tile
          label="Net DEX"
          value={netDexDollars != null ? fmtMoneyCompact(netDexDollars) : "—"}
          valueColor={signedColor(netDexDollars)}
        />
        <Tile
          label="IV 30D"
          value={iv != null ? `${(iv * 100).toFixed(1)}%` : "—"}
          sub={ivRank != null ? `rank ${Math.round(ivRank)}%` : ""}
        />
        <Tile
          label="Vol P/C"
          value={fmtNum(pcrVol, 2)}
          valueColor="var(--warning)"
        />
      </div>

      {/* Bottom row: 5 level tiles */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <Tile
          label="GEX Flip (support)"
          value={lv?.gex_flip ? fmtNum(toNum(lv.gex_flip.strike), 2) : "—"}
          sub={levelSub(lv?.gex_flip)}
          valueColor="var(--warning)"
        />
        <Tile
          label="Max Magnet"
          value={lv?.max_magnet ? fmtNum(toNum(lv.max_magnet.strike), 2) : "—"}
          sub={levelSub(lv?.max_magnet)}
          valueColor="var(--positive)"
        />
        <Tile
          label="2nd Magnet"
          value={
            lv?.second_magnet ? fmtNum(toNum(lv.second_magnet.strike), 2) : "—"
          }
          sub={levelSub(lv?.second_magnet)}
        />
        <Tile
          label="Max Accel (below flip)"
          value={lv?.max_accel ? fmtNum(toNum(lv.max_accel.strike), 2) : "—"}
          sub={levelSub(lv?.max_accel)}
          valueColor="var(--negative)"
        />
        <Tile
          label="Put Wall"
          value={lv?.put_wall ? fmtNum(toNum(lv.put_wall.strike), 2) : "—"}
          sub={levelSub(lv?.put_wall)}
          valueColor="var(--negative)"
        />
      </div>
    </div>
  );
}
