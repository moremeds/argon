import type { TechnicalsResponse } from "@/lib/api";
import { fmtDecimal, fmtPct, fmtSigned } from "@/lib/formatters";
import { Tile } from "./TechnicalsTiles";

export function TechnicalsKpiStrip({ data }: { data: TechnicalsResponse }) {
  const h = data.header;
  const z = h?.z ?? null;
  const zColor =
    z == null
      ? undefined
      : z <= -1
        ? "var(--positive)" // stretched low -> mean-revert cheap
        : z >= 1
          ? "var(--negative)"
          : undefined;
  const pctile = data.macd_watchlist_pctile;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
        gap: 12,
      }}
    >
      <Tile
        label="Price"
        value={fmtDecimal(h?.price, 2)}
        sub={data.as_of ?? " "}
      />
      <Tile
        label="200 DMA / Dist"
        value={fmtDecimal(h?.sma200, 2)}
        sub={h?.dist_pct != null ? `${fmtPct(h.dist_pct)} vs 200DMA` : " "}
      />
      <Tile
        label="Z-Score"
        value={fmtSigned(z, 2)}
        valueColor={zColor}
        sub={h?.z_band ?? " "}
      />
      <Tile
        label="200 DMA Slope (Ann.)"
        value={fmtPct(h?.slope_ann)}
        sub={h?.slope_regime ?? " "}
      />
      <Tile
        label="Composite"
        value={fmtSigned(h?.composite, 2)}
        sub={data.bars_n != null ? `n=${data.bars_n} bars` : " "}
      />
      <Tile
        label="MACD Pctile"
        value={pctile != null ? fmtDecimal(pctile * 100, 0) : "—"}
        sub="vs watchlist"
      />
    </div>
  );
}
