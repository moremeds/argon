import type { TechnicalsResponse } from "@/lib/api";
import { fmtDecimal, fmtPct, fmtSigned } from "@/lib/formatters";
import { OscillatorChart } from "./OscillatorChart";

type Row = TechnicalsResponse["series"][number];

const col = (series: readonly Row[], key: keyof Row): Array<number | null> =>
  series.map((r) => {
    const v = r[key];
    return typeof v === "number" ? v : null;
  });

const datesOf = (series: readonly Row[]) => series.map((r) => r.as_of);

export function TechnicalsZChart({ data }: { data: TechnicalsResponse }) {
  const s = data.series ?? [];
  return (
    <OscillatorChart
      title="Z-Score vs 200 DMA"
      subtitle="σ from the mean"
      headline={data.header?.z_band ?? undefined}
      unit="σ"
      dates={datesOf(s)}
      lines={[{ values: col(s, "z"), color: "var(--accent-vivid)" }]}
      refLines={[
        { y: 0, solid: true },
        { y: 2, label: "+2σ" },
        { y: 1, label: "+1σ" },
        { y: -1, label: "-1σ" },
        { y: -2, label: "-2σ" },
      ]}
      zones={[
        { from: 1.5, to: 4, color: "var(--negative)" },
        { from: -4, to: -1.5, color: "var(--positive)" },
      ]}
      explanation="How far price sits from its 200-day average, measured in standard deviations of that gap. Above +2σ is historically stretched-rich (mean-reversion risk); below −2σ is stretched-cheap. The current band drives the forward-return table below."
    />
  );
}

export function TechnicalsRsiChart({ data }: { data: TechnicalsResponse }) {
  const s = data.series ?? [];
  const rsi = data.detail?.rsi as { rsi14?: number | null } | undefined;
  return (
    <OscillatorChart
      title="RSI(14)"
      subtitle="momentum oscillator"
      headline={rsi?.rsi14 != null ? fmtDecimal(rsi.rsi14, 1) : undefined}
      dates={datesOf(s)}
      yDomain={[0, 100]}
      lines={[{ values: col(s, "rsi14"), color: "var(--accent-warm)" }]}
      refLines={[{ y: 70, label: "70" }, { y: 50 }, { y: 30, label: "30" }]}
      zones={[
        { from: 70, to: 100, color: "var(--negative)" },
        { from: 0, to: 30, color: "var(--positive)" },
      ]}
      explanation="Wilder's RSI(14): the speed and size of recent up- vs down-moves on a 0–100 scale. Above 70 (shaded) = overbought, below 30 = oversold. Persistent readings above 50 confirm an uptrend."
    />
  );
}

export function TechnicalsMacdChart({ data }: { data: TechnicalsResponse }) {
  const s = data.series ?? [];
  const macd = data.detail?.macd as { hist_atr?: number | null } | undefined;
  return (
    <OscillatorChart
      title="MACD Histogram (8/17/9)"
      subtitle="ATR-normalized"
      headline={
        macd?.hist_atr != null ? fmtSigned(macd.hist_atr, 3) : undefined
      }
      dates={datesOf(s)}
      histogram={{ values: col(s, "macd_hist_atr") }}
      refLines={[{ y: 0, solid: true }]}
      explanation="MACD histogram (fast/slow/signal = 8/17/9), divided by ATR so the scale is comparable across tickers. Green bars above zero = momentum strengthening; red below = weakening. Bars shrinking toward zero warn of a momentum turn before the sign flips."
    />
  );
}

export function TechnicalsVolChart({ data }: { data: TechnicalsResponse }) {
  const s = data.series ?? [];
  const dist = data.detail?.distribution as
    | { rv20?: number | null }
    | undefined;
  const rvPct = col(s, "rv20").map((v) => (v == null ? null : v * 100));
  return (
    <OscillatorChart
      title="Realized Volatility (20d, ann.)"
      subtitle="return dispersion"
      headline={dist?.rv20 != null ? fmtPct(dist.rv20) : undefined}
      unit="%"
      dates={datesOf(s)}
      lines={[{ values: rvPct, color: "var(--accent-vol)" }]}
      explanation="Annualized standard deviation of the last 20 daily returns — how choppy the stock has actually been. Rising realized vol often precedes or accompanies trend breaks; falling vol marks quiet, trending regimes."
    />
  );
}

export function TechnicalsKinematicsChart({
  data,
}: {
  data: TechnicalsResponse;
}) {
  const s = data.series ?? [];
  return (
    <OscillatorChart
      title="MA Kinematics — slope of each average"
      subtitle="ATR-normalized velocity"
      dates={datesOf(s)}
      lines={[
        {
          values: col(s, "kin_slope20"),
          color: "var(--accent-warm)",
          label: "SMA20",
        },
        {
          values: col(s, "kin_slope50"),
          color: "var(--accent-vol)",
          label: "SMA50",
        },
        {
          values: col(s, "kin_slope200"),
          color: "var(--accent-vivid)",
          label: "SMA200",
        },
      ]}
      refLines={[{ y: 0, solid: true }]}
      explanation="Slope (per-day rise/fall) of each moving average, divided by ATR so it reads as 'ATRs per day'. Above zero = the average is rising. The fast SMA20 slope turns first at inflections; when all three are positive and stacked, the trend is broad and healthy."
    />
  );
}

export function TechnicalsRsChart({ data }: { data: TechnicalsResponse }) {
  const s = data.series ?? [];
  const rs = data.detail?.rs as
    | { ratio?: number | null; trend?: string | null }
    | undefined;
  return (
    <OscillatorChart
      title="Relative Strength vs SPY"
      subtitle="price ÷ SPY"
      headline={rs?.trend ?? undefined}
      dates={datesOf(s)}
      lines={[{ values: col(s, "rs_ratio"), color: "var(--accent-vivid)" }]}
      explanation="This ticker's price divided by SPY. A rising line means the stock is outperforming the market regardless of absolute direction; a falling line means it's lagging. Trend changes here often lead absolute-price trend changes."
    />
  );
}
