import { BoardPanel } from "@/components/macro/domain/BoardPanel";
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
    body: "The real-rate channel is transmitting.",
  },
  partial: {
    label: "PARTIAL",
    tone: "default",
    body: "Transmission is mixed across windows.",
  },
  suspended: {
    label: "SUSPENDED",
    tone: "warning",
    body: "The real-rate channel is not transmitting; the cyclical lens is context only.",
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
    <BoardPanel
      id="transmission-gauge"
      title="Real-yield link"
      questions={["Q4", "Q7"]}
      basis="REAL"
      source={
        <>
          /api/gold/state gauge · rolling gold ↔ DFII10 correlation at four
          windows, as the posture engine stored them
        </>
      }
    >
      <div className="lgd">
        <span>
          gate{" "}
          <b
            style={{
              color:
                regime.tone === "warning"
                  ? "var(--warning)"
                  : regime.tone === "positive"
                    ? "var(--positive)"
                    : "var(--text-secondary)",
            }}
          >
            {regime.label}
          </b>
        </span>
        <span>
          {present.length} of {WINDOWS.length} windows computed
        </span>
      </div>

      <div
        data-testid="gold-gauge-term-structure"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${WINDOWS.length}, minmax(0, 1fr))`,
          gap: 8,
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

      <p data-testid="gold-gauge-read" className="read">
        {spread === null ? (
          <>
            Fewer than two correlation windows are available, so there is no
            term structure to read here yet.
          </>
        ) : spread > 0.3 ? (
          <>
            The link is firm on {narrowest.label} ({fmt(narrowest.value)}) but{" "}
            <strong style={{ color: "var(--text-primary, #cfd2db)" }}>
              weak on {widest.label}
            </strong>{" "}
            ({fmt(widest.value)}), consistent with a recent regime change.
          </>
        ) : spread < -0.3 ? (
          <>
            The historical link ({widest.label} {fmt(widest.value)}) is firmer
            than the recent one ({narrowest.label} {fmt(narrowest.value)}).
          </>
        ) : (
          <>
            {narrowest.label} and {widest.label} agree within{" "}
            {Math.abs(spread).toFixed(2)}.
          </>
        )}{" "}
        {regime.body}
      </p>
    </BoardPanel>
  );
}
