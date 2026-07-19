"use client";

import InfoTooltip from "./InfoTooltip";
import type { DispersionData } from "@/lib/regime/useDispersion";

// Descriptive correlation/dispersion CONTEXT for the CRI view. Rule-based
// highlighter is TWO-TAILED (regime state), NOT a good/bad axis:
//   RED  (--negative) = herding    — high correlation, crash-adjacent (deepest
//                                     fwd drawdowns; already the CRI crash trigger)
//   AMBER (--warning) = dispersion — low correlation / high single-stock vol
//                                     (the high-beta-derate regime)
//   neutral           = mid-range
// Low correlation is deliberately NOT painted red — the "low corr = warning"
// claim was falsified. Verdict + evidence:
// docs/research/2026-07-19-dispersion-signals-eval.md.

const HERDING = "var(--negative)";
const DISPERSION = "var(--warning)";
const NEUTRAL = "var(--text-primary)";
const MUTED = "var(--text-muted)";

const TOOLTIPS = {
  "COR1M %ILE (20Y)":
    "Where the latest COR1M (S&P 500 implied correlation) sits within ~20yr of history: 0 = lowest correlation ever (max dispersion), 100 = highest (herding). Highlight: ≥80 red (herding / crash-adjacent — the CRI crash marker), ≤20 amber (dispersion). Low correlation is NOT a warning. See docs/research/2026-07-19-dispersion-signals-eval.md.",
  "VIX / COR1M":
    "Index implied vol ÷ implied correlation — the dispersion axis, nearly orthogonal to VIX level (Pearson 0.06). High ratio ⟺ low correlation / high single-stock vol (equivalent to VIXEQ/VIX high). Colored by its z-score below. Descriptive regime context, not a timing signal.",
  "VIX/COR1M Z":
    "Trailing-252 z-score of the VIX/COR1M ratio. Highlight: ≥ +2 amber (dispersion unusually stretched vs the past year), ≤ −2 red (herding stretched — correlation rich). Context, not a trade trigger.",
};

/** COR1M percentile (0–100) → regime color. Two-tailed. */
function pctColor(pct: number | null): string {
  if (pct == null || !Number.isFinite(pct)) return MUTED;
  if (pct >= 80) return HERDING; // high correlation
  if (pct <= 20) return DISPERSION; // low correlation
  return NEUTRAL;
}

/** VIX/COR1M ratio z-score → regime color. High z = dispersion, low = herding. */
function zColor(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return MUTED;
  if (z >= 2) return DISPERSION; // dispersion stretched
  if (z <= -2) return HERDING; // correlation stretched
  return NEUTRAL;
}

function Tile({
  label,
  value,
  color,
  dec = 2,
  signed = false,
}: {
  label: string;
  value: number | null | undefined;
  color: string;
  dec?: number;
  signed?: boolean;
}) {
  let display = "—";
  if (value != null && Number.isFinite(value)) {
    const formatted = value.toFixed(dec);
    display = signed && value > 0 ? `+${formatted}` : formatted;
  }
  return (
    <div className="regime-tile" data-testid={`dispersion-tile-${label}`}>
      <div className="regime-tile-label">
        {label}{" "}
        <InfoTooltip text={TOOLTIPS[label as keyof typeof TOOLTIPS] ?? ""} />
      </div>
      <div className="regime-tile-value" style={{ color }}>
        {display}
      </div>
    </div>
  );
}

function LegendDot({ color, text }: { color: string; text: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: 2,
          background: color,
          display: "inline-block",
        }}
      />
      {text}
    </span>
  );
}

export function DispersionTiles({ data }: { data: DispersionData | null }) {
  if (!data || data.n_obs === 0) return null;
  const pct =
    data.cor1m_percentile != null ? data.cor1m_percentile * 100 : null;
  const z = data.vix_cor1m_ratio_z;
  return (
    <div>
      <div
        className="regime-panel-title"
        style={{ marginBottom: 6 }}
        data-testid="dispersion-row-title"
      >
        DISPERSION CONTEXT
        <span
          style={{
            marginLeft: 8,
            fontSize: 10,
            letterSpacing: "0.08em",
            color: MUTED,
            textTransform: "none",
          }}
        >
          descriptive · not a signal
        </span>
      </div>
      {/* Color-rule legend — two-tailed regime state, not good/bad. */}
      <div
        style={{
          display: "flex",
          gap: 16,
          marginBottom: 8,
          fontSize: 10,
          letterSpacing: "0.04em",
          color: MUTED,
        }}
        data-testid="dispersion-legend"
      >
        <LegendDot
          color={DISPERSION}
          text="dispersion (low corr / high single-stock vol)"
        />
        <LegendDot
          color={HERDING}
          text="herding (high corr · crash-adjacent)"
        />
      </div>
      <div className="regime-meanrev-row" data-testid="dispersion-row">
        <Tile
          label="COR1M %ILE (20Y)"
          value={pct}
          color={pctColor(pct)}
          dec={1}
        />
        <Tile
          label="VIX / COR1M"
          value={data.vix_cor1m_ratio}
          color={zColor(z)}
          dec={2}
        />
        <Tile label="VIX/COR1M Z" value={z} color={zColor(z)} dec={2} signed />
      </div>
    </div>
  );
}
