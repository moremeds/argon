"use client";

import InfoTooltip from "./InfoTooltip";
import type { DispersionData } from "@/lib/regime/useDispersion";

// Descriptive correlation/dispersion CONTEXT for the CRI view. Deliberately
// NOT a signal: low correlation is not a warning (high correlation is the crash
// marker — see the CRI crash trigger). Verdict + evidence:
// docs/research/2026-07-19-dispersion-signals-eval.md.

const TOOLTIPS = {
  "COR1M %ILE (20Y)":
    "Where the latest COR1M (S&P 500 implied correlation) sits within ~20yr of history: 0 = lowest correlation ever (max dispersion), 100 = highest (herding). Context only — HIGH correlation is the crash marker (CRI crash trigger), low is NOT a warning. See docs/research/2026-07-19-dispersion-signals-eval.md.",
  "VIX / COR1M":
    "Index implied vol ÷ implied correlation — the dispersion axis, nearly orthogonal to VIX level (Pearson 0.06). High ratio ⟺ low correlation / high single-stock vol (equivalent to VIXEQ/VIX high). Descriptive regime context, not a validated timing signal.",
  "VIX/COR1M Z":
    "Trailing-252 z-score of the VIX/COR1M ratio. |z| > 2 = dispersion unusually stretched vs the past year. Context, not a trade trigger.",
};

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
    <div className="regime-tile" data-testid={`dispersion-tile-${label}`}>
      <div className="regime-tile-label">
        {label}{" "}
        <InfoTooltip text={TOOLTIPS[label as keyof typeof TOOLTIPS] ?? ""} />
      </div>
      {/* Neutral color throughout — context, not a directional signal. */}
      <div
        className="regime-tile-value"
        style={{ color: "var(--text-primary)" }}
      >
        {display}
      </div>
    </div>
  );
}

export function DispersionTiles({ data }: { data: DispersionData | null }) {
  if (!data || data.n_obs === 0) return null;
  const pct =
    data.cor1m_percentile != null ? data.cor1m_percentile * 100 : null;
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
            color: "var(--text-muted)",
            textTransform: "none",
          }}
        >
          descriptive · not a signal
        </span>
      </div>
      <div className="regime-meanrev-row" data-testid="dispersion-row">
        <Tile label="COR1M %ILE (20Y)" value={pct} dec={1} />
        <Tile label="VIX / COR1M" value={data.vix_cor1m_ratio} dec={2} />
        <Tile
          label="VIX/COR1M Z"
          value={data.vix_cor1m_ratio_z}
          dec={2}
          signed
        />
      </div>
    </div>
  );
}
