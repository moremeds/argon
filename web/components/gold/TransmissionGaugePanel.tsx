import type { components } from "@/lib/types";

import { Tile } from "./Tile";

type Gauge = components["schemas"]["GoldGaugeState"];

/**
 * The panel the board opens tab 05 with, and the reason the tab is ordered the way it is.
 *
 * The audit that produced this found gold's problem was framing, not absence: every lens
 * was present, and the one question that governs how to read them was a single tile in a
 * five-tile strip. The gauge is not one reading among five — it decides whether the
 * cyclical lens below it means anything at all, which is why the layout dims that lens
 * when this reads `suspended`. A page whose governing condition is discoverable only by
 * scanning a KPI row has buried its own instructions.
 *
 * "Collapse" is the board's word and it is a TERM STRUCTURE claim, not a level claim:
 * the nearest windows can hold a firm relationship while the widest one goes to zero,
 * which is precisely what it looks like when a regime ends part-way through the lookback.
 * So all four windows are shown together, and the sentence beneath them is derived from
 * the spread between the narrowest and widest available window rather than asserted.
 *
 * An absent window renders absent. `corr_504d` is routinely null — the series does not
 * reach back far enough — and a missing window is a fact about our history, never a zero.
 */
const WINDOWS = [
  { key: "corr_60d", label: "60D" },
  { key: "corr_126d", label: "126D" },
  { key: "corr_252d", label: "252D" },
  { key: "corr_504d", label: "504D" },
] as const;

const REGIME_COPY: Record<
  Gauge["state"],
  { label: string; tone: "positive" | "warning" | "default"; body: string }
> = {
  operative: {
    label: "OPERATIVE",
    tone: "positive",
    body: "The real-rate channel is transmitting, so the cyclical lens below is reading a relationship that currently holds.",
  },
  partial: {
    label: "PARTIAL",
    tone: "default",
    body: "The real-rate channel is transmitting on some windows and not others. Treat the cyclical lens as weakened rather than either sound or void.",
  },
  suspended: {
    label: "SUSPENDED",
    tone: "warning",
    body: "The real-rate channel is not transmitting. The cyclical lens below is informative only — it is dimmed for that reason, and nothing on this page should be read as gold tracking real rates today.",
  },
};

function num(raw: string | number | null | undefined): number {
  const n = typeof raw === "string" ? Number(raw) : raw;
  return n === null || n === undefined || !Number.isFinite(n) ? NaN : n;
}

function fmt(raw: string | number | null | undefined): string {
  const n = num(raw);
  return Number.isFinite(n) ? n.toFixed(2) : "—";
}

export function TransmissionGaugePanel({ gauge }: { gauge: Gauge }) {
  const regime = REGIME_COPY[gauge.state] ?? {
    label: gauge.state.toUpperCase(),
    tone: "default" as const,
    body: "",
  };

  const present = WINDOWS.map((w) => ({
    ...w,
    value: num(gauge[w.key]),
  })).filter((w) => Number.isFinite(w.value));

  // The collapse read: the narrowest and widest windows we actually have. Both must
  // exist, and there must be two of them, or there is no term structure to describe.
  const narrowest = present[0];
  const widest = present[present.length - 1];
  const spread =
    present.length >= 2
      ? Math.abs(narrowest.value) - Math.abs(widest.value)
      : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          flexWrap: "wrap",
          justifyContent: "space-between",
        }}
      >
        <h2
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            letterSpacing: 1.8,
            textTransform: "uppercase",
            color: "var(--text-primary, #cfd2db)",
            margin: 0,
          }}
        >
          TRANSMISSION GAUGE · GOLD ↔ DFII10
        </h2>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: 1.5,
            color:
              regime.tone === "warning"
                ? "var(--warning, #f5a623)"
                : regime.tone === "positive"
                  ? "var(--positive, #05ad98)"
                  : "var(--text-secondary, #9aa3b2)",
          }}
        >
          {regime.label}
        </span>
      </div>

      <div
        data-testid="gold-gauge-term-structure"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${WINDOWS.length}, minmax(0, 1fr))`,
          gap: 12,
        }}
      >
        {WINDOWS.map((w) => (
          <Tile
            key={w.key}
            label={w.label}
            value={fmt(gauge[w.key])}
            sub={
              Number.isFinite(num(gauge[w.key]))
                ? "rolling correlation"
                : "history does not reach back this far"
            }
          />
        ))}
      </div>

      <p
        data-testid="gold-gauge-read"
        style={{
          margin: 0,
          fontSize: 12,
          lineHeight: 1.6,
          color: "var(--text-secondary, #9aa3b2)",
          maxWidth: 900,
        }}
      >
        {spread === null ? (
          <>
            Fewer than two correlation windows are available, so there is no
            term structure to read here yet.
          </>
        ) : spread > 0.3 ? (
          <>
            The relationship holds on the {narrowest.label} window (
            {fmt(narrowest.value)}) and has{" "}
            <strong style={{ color: "var(--text-primary, #cfd2db)" }}>
              collapsed on the {widest.label}
            </strong>{" "}
            ({fmt(widest.value)}). A narrow window firm against a wide window
            near zero is what a regime that ended part-way through the lookback
            looks like — the wider number averages across two different worlds,
            rather than being a weaker version of the nearer one.
          </>
        ) : spread < -0.3 ? (
          <>
            The relationship is firmer on the {widest.label} window (
            {fmt(widest.value)}) than on the {narrowest.label} (
            {fmt(narrowest.value)}), so what is decaying is the recent
            association, not the historical one.
          </>
        ) : (
          <>
            The {narrowest.label} and {widest.label} windows agree to within{" "}
            {Math.abs(spread).toFixed(2)}, so the relationship is behaving
            consistently across the lookback.
          </>
        )}{" "}
        {regime.body}
      </p>
    </div>
  );
}
