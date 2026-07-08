import type { TechnicalsResponse } from "@/lib/api";
import { fmtDecimal, fmtPct, fmtSigned } from "@/lib/formatters";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";
import { Tile, type MaKin, type TechDetail } from "./TechnicalsTiles";

const grid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
  gap: 8,
};

export function TechnicalsDetailPanels({ data }: { data: TechnicalsResponse }) {
  const d = (data.detail ?? {}) as TechDetail;
  const kin = d.kinematics ?? {};
  const sig = d.sigmoid ?? {};
  const dist = d.distribution ?? {};
  const rsi = d.rsi ?? {};
  const macd = d.macd ?? {};
  const rs = d.rs ?? {};

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
        gap: 16,
      }}
    >
      <AnalyticalSeriesPanel title="MA Kinematics" subtitle="ATR-normalized">
        <div style={grid}>
          {(["sma20", "sma50", "sma200"] as const).map((k) => {
            const m: MaKin = kin[k] ?? null;
            return (
              <Tile
                key={k}
                label={k.toUpperCase()}
                value={fmtSigned((m?.slope_atr ?? null) as number | null, 3)}
                sub={
                  m?.tstat != null
                    ? `t=${fmtDecimal(m.tstat, 1)}`
                    : "slope·ATR/d"
                }
              />
            );
          })}
          <Tile
            label="Alignment"
            value={kin.alignment != null ? `${kin.alignment}/3` : "—"}
            valueColor={
              kin.alignment == null
                ? undefined
                : kin.alignment > 0
                  ? "var(--positive)"
                  : kin.alignment < 0
                    ? "var(--negative)"
                    : undefined
            }
            sub="3-pair MA order"
          />
        </div>
      </AnalyticalSeriesPanel>

      <AnalyticalSeriesPanel
        title="Sigmoid Trend Maturity"
        subtitle="beats-linear guard"
        headline={sig.valid ? (sig.phase ?? undefined) : undefined}
      >
        {sig.valid ? (
          <div style={grid}>
            <Tile label="k (steepness)" value={fmtDecimal(sig.k, 3)} />
            <Tile label="s = k·Δt" value={fmtSigned(sig.s, 2)} />
            <Tile
              label="R² sig / lin"
              value={`${fmtDecimal(sig.r2_sigmoid, 2)} / ${fmtDecimal(sig.r2_linear, 2)}`}
            />
          </div>
        ) : (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            No S-curve structure (R²sig {fmtDecimal(sig.r2_sigmoid, 2)} ≤ R²lin{" "}
            {fmtDecimal(sig.r2_linear, 2)} + 0.05).
          </div>
        )}
      </AnalyticalSeriesPanel>

      <AnalyticalSeriesPanel
        title="Return Distribution"
        subtitle="σ & higher moments"
      >
        <div style={grid}>
          <Tile label="RV20 (ann.)" value={fmtPct(dist.rv20)} />
          <Tile label="RV20 z" value={fmtSigned(dist.rv20_z, 2)} />
          <Tile label="Vol-of-vol" value={fmtDecimal(dist.vol_of_vol, 3)} />
          <Tile label="Skew 60d" value={fmtSigned(dist.skew60, 2)} />
          <Tile label="Kurt 60d" value={fmtDecimal(dist.kurt60, 2)} />
          <Tile label="Jerk 20d" value={fmtDecimal(dist.jerk20, 4)} />
        </div>
      </AnalyticalSeriesPanel>

      <AnalyticalSeriesPanel
        title="RSI Enhanced"
        subtitle="z-scored + divergence"
      >
        <div style={grid}>
          <Tile label="RSI14" value={fmtDecimal(rsi.rsi14, 1)} />
          <Tile label="RSI z" value={fmtSigned(rsi.rsi_z, 2)} />
          <Tile label="Slope 5d" value={fmtSigned(rsi.rsi_slope5, 2)} />
        </div>
        {rsi.divergence?.type && (
          <div style={{ marginTop: 8 }}>
            <span
              style={{
                fontSize: 11,
                letterSpacing: 1,
                textTransform: "uppercase",
                padding: "2px 8px",
                borderRadius: 3,
                color:
                  rsi.divergence.type === "BEARISH"
                    ? "var(--negative)"
                    : "var(--positive)",
                border: "1px solid var(--border-dim)",
              }}
            >
              {rsi.divergence.type} DIVERGENCE
            </span>
          </div>
        )}
      </AnalyticalSeriesPanel>

      <AnalyticalSeriesPanel title="MACD Enhanced" subtitle="8/17/9 · ATR-norm">
        <div style={grid}>
          <Tile label="Hist / ATR" value={fmtSigned(macd.hist_atr, 3)} />
          <Tile label="Slope 3d" value={fmtSigned(macd.hist_atr_slope3, 3)} />
          <Tile
            label="Watchlist Pctile"
            value={
              data.macd_watchlist_pctile != null
                ? fmtDecimal(data.macd_watchlist_pctile * 100, 0)
                : "—"
            }
          />
        </div>
      </AnalyticalSeriesPanel>

      <AnalyticalSeriesPanel
        title="Relative Strength vs SPY"
        subtitle="ratio + MAs"
        headline={rs.trend ?? undefined}
      >
        <div style={grid}>
          <Tile label="Ratio" value={fmtDecimal(rs.ratio, 4)} />
          <Tile label="MA60" value={fmtDecimal(rs.ma60, 4)} />
          <Tile label="MA200" value={fmtDecimal(rs.ma200, 4)} />
        </div>
      </AnalyticalSeriesPanel>
    </div>
  );
}
