"use client";

import InfoTooltip from "./InfoTooltip";

interface Props {
  vrp: number | null | undefined;
  vixZscore: number | null | undefined;
  vixVix3mRatio: number | null | undefined;
  vixDelta3d: number | null | undefined;
}

const TOOLTIPS = {
  VRP: "Variance Risk Premium (vol-unit form) = VIX − 20d realized vol of SPX. Positive (the modal case): implied > realized; potential vol compression. Negative: realized exceeded implied (post-spike). Academic VRP uses variance units (VIX² − RV²); we surface vol units for readability — same sign, same semantics.",
  "VIX Z (30d)":
    "Today's VIX in standard deviations from the trailing-30d mean. |z| > 2 = stretched (mean-reversion trigger threshold per the rolling-z-score convention).",
  "VIX / VIX3M":
    "Front-end vs 3-month VIX (CBOE term-structure ratio). < 0.85 deep contango; 0.85–0.95 normal contango; 0.95–1.0 warning (curve flattening); 1.0–1.1 backwardation (front-end stress); > 1.1 deep backwardation (panic). Contango dominates ~85% of days; the cross above 1.0 has historically preceded every major drawdown 1990–2025.",
  "VIX Δ (3d)":
    "Absolute change in VIX over the last 3 sessions, in VIX points (NOT %). Positive = vol expanding fast. Practitioner velocity signal — complementary to VIX Z (30d) which normalizes against the trailing 30d distribution. ~+3 points = moderate stress; ~+30 points = Volmageddon territory.",
};

function tileColor(label: string, v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-muted)";
  if (label === "VRP") return v > 0 ? "var(--positive)" : "var(--negative)";
  if (label === "VIX Z (30d)")
    return Math.abs(v) > 2 ? "var(--warning)" : "var(--text-primary)";
  if (label === "VIX / VIX3M") {
    if (v >= 1.1) return "var(--negative)";
    if (v >= 1.0) return "var(--warning)";
    if (v >= 0.95) return "var(--text-primary)";
    return "var(--positive)";
  }
  if (label === "VIX Δ (3d)") {
    if (v >= 3) return "var(--negative)"; // big expansion
    if (v >= 1) return "var(--warning)"; // moderate
    if (v <= -2) return "var(--positive)"; // compression
    return "var(--text-primary)";
  }
  return "var(--text-primary)";
}

function Tile({
  label,
  value,
  dec = 2,
  signed = false,
}: {
  label: string;
  value: number | null | undefined;
  dec?: number;
  signed?: boolean;
}) {
  let display = "—";
  if (value != null && Number.isFinite(value)) {
    const formatted = value.toFixed(dec);
    display = signed && value > 0 ? `+${formatted}` : formatted;
  }
  return (
    <div className="regime-tile" data-testid={`meanrev-tile-${label}`}>
      <div className="regime-tile-label">
        {label}{" "}
        <InfoTooltip text={TOOLTIPS[label as keyof typeof TOOLTIPS] ?? ""} />
      </div>
      <div
        className="regime-tile-value"
        style={{ color: tileColor(label, value) }}
      >
        {display}
      </div>
    </div>
  );
}

export function MeanReversionTiles({
  vrp,
  vixZscore,
  vixVix3mRatio,
  vixDelta3d,
}: Props) {
  return (
    <div className="regime-meanrev-row" data-testid="meanrev-row">
      <Tile label="VRP" value={vrp} />
      <Tile label="VIX Z (30d)" value={vixZscore} />
      <Tile label="VIX / VIX3M" value={vixVix3mRatio} dec={3} />
      <Tile label="VIX Δ (3d)" value={vixDelta3d} signed />
    </div>
  );
}
