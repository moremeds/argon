import type { TechnicalsResponse } from "@/lib/api";
import { fmtDecimal, fmtPct } from "@/lib/formatters";
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
  const dm = data.detail?.dual_macd as
    | {
        trend_state?: string;
        tactical_signal?: string;
        momentum_balance?: string;
        confidence?: number | null;
      }
    | undefined;
  const sig =
    dm?.tactical_signal && dm.tactical_signal !== "NONE"
      ? `${dm.tactical_signal} · conf ${fmtDecimal(dm.confidence ?? 0, 2)}`
      : (dm?.trend_state ?? undefined);
  return (
    <OscillatorChart
      title="Dual MACD — 13/21/9 vs 55/89/34"
      subtitle="ATR-normalized · fast vs slow"
      headline={sig}
      dates={datesOf(s)}
      histogram={{
        values: col(s, "fast_macd_hist_atr"),
        label: "FAST 13/21/9 · tactical (short)",
      }}
      histogramOverlay={{
        values: col(s, "slow_macd_hist_atr"),
        color: "var(--accent-vol)",
        label: "SLOW 55/89/34 · structural (long)",
      }}
      refLines={[{ y: 0, solid: true }]}
      explanation="Two MACD histograms on one ATR-normalized scale: the wide muted bars are the slow 55/89/34 (structural trend); the sharp bars are the fast 13/21/9 (tactical timing). When the slow trend is up but the fast bars dip below zero and start curling back up, that's a DIP_BUY (mirror = RALLY_SELL). The badge shows the current tactical signal, its confidence, and the trend/momentum-balance state."
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

// Plain-English take on the three MA slopes: how many are statistically
// reliable (|t| >= 2) and whether they point the same way. Complements the
// ALIGN badge (which reports stack order, not velocity).
export function kinematicsReading(
  t20: number | null | undefined,
  t50: number | null | undefined,
  t200: number | null | undefined,
): string | null {
  const known = [t20, t50, t200].filter(
    (t): t is number => typeof t === "number",
  );
  if (known.length < 3) return null;
  const sig = known.filter((t) => Math.abs(t) >= 2);
  if (sig.length === 0)
    return "Reading: no MA slope is statistically reliable — no trend.";
  const up = sig.filter((t) => t > 0).length;
  const down = sig.filter((t) => t < 0).length;
  if (up > 0 && down > 0)
    return `Reading: slopes disagree (${sig.length}/3 reliable) — no clean trend.`;
  const conf = sig.length === 3 ? "all three MAs" : `${sig.length}/3 MAs`;
  const dir = up > 0 ? "rising" : "falling";
  const strength = sig.length === 3 ? "confirmed" : "tentative";
  const verdict = up > 0 ? "uptrend" : "downtrend";
  return `Reading: ${conf} ${dir}, statistically reliable — ${strength} ${verdict}.`;
}

export function TechnicalsKinematicsChart({
  data,
}: {
  data: TechnicalsResponse;
}) {
  const s = data.series ?? [];
  const kin = (data.detail?.kinematics ?? {}) as {
    sma20?: { tstat?: number | null };
    sma50?: { tstat?: number | null };
    sma200?: { tstat?: number | null };
    alignment?: number | null;
  };
  const reading = kinematicsReading(
    kin.sma20?.tstat,
    kin.sma50?.tstat,
    kin.sma200?.tstat,
  );
  // Blend Trend-Reliability into the slope chart: draw each MA weighted by its
  // slope t-stat. |t| >= 2 (unlikely to be noise) is bold/solid; |t| < 2 fades.
  const weight = (t: number | null | undefined) => {
    const a = t == null ? 0 : Math.abs(t);
    return a >= 2
      ? { strokeWidth: 1.9, opacity: 1 }
      : { strokeWidth: 0.9, opacity: 0.35 };
  };
  const tLabel = (name: string, t: number | null | undefined) =>
    t == null
      ? name
      : `${name} · t ${Math.abs(t) >= 10 ? t.toFixed(0) : t.toFixed(1)}`;
  // Alignment badge: label the direction (BULL/BEAR/MIXED) and color it by sign
  // so a bearish stack reads red at a glance — |a| shows how many of the 3 MAs
  // are stacked that way.
  const a = kin.alignment;
  const badge =
    a == null ? undefined : (
      <span
        style={{
          color:
            a > 0
              ? "var(--positive)"
              : a < 0
                ? "var(--negative)"
                : "var(--text-muted)",
        }}
      >
        {a > 0 ? "BULL" : a < 0 ? "BEAR" : "MIXED"} ALIGN {Math.abs(a)}/3
      </span>
    );
  return (
    <OscillatorChart
      title="MA Kinematics — slope of each average"
      subtitle="ATR-normalized velocity · weighted by trend reliability"
      headline={badge}
      dates={datesOf(s)}
      lines={[
        {
          values: col(s, "kin_slope20"),
          color: "var(--accent-warm)",
          label: tLabel("SMA20", kin.sma20?.tstat),
          ...weight(kin.sma20?.tstat),
        },
        {
          values: col(s, "kin_slope50"),
          color: "var(--accent-vol)",
          label: tLabel("SMA50", kin.sma50?.tstat),
          ...weight(kin.sma50?.tstat),
        },
        {
          values: col(s, "kin_slope200"),
          color: "var(--accent-vivid)",
          label: tLabel("SMA200", kin.sma200?.tstat),
          ...weight(kin.sma200?.tstat),
        },
      ]}
      refLines={[{ y: 0, solid: true }]}
      shadeBelowZero
      explanation={`${reading ? reading + " " : ""}Slope (per-day rise/fall) of each moving average, divided by ATR so it reads as 'ATRs per day'. Each line is weighted by its slope t-stat: bold/solid = statistically reliable (|t| ≥ 2), faded = likely noise. The red band below the zero line is the downtrend zone — wherever a slope dips into it, that average is falling. The ALIGN badge counts how many of the three MAs are stacked in bullish order (−3…+3). Read direction + reliability + stack in one glance.`}
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
