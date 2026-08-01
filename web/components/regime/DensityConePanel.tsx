"use client";

import { useState } from "react";
import { useSpxDensity } from "@/lib/regime/useSpxDensity";
import DensityConeChart, { type ConeView } from "./DensityConeChart";

// Sessions of realised context drawn to the left of the cone.
//
// This number IS the candle width. lightweight-charts derives bar width from bar
// spacing, and the pane is fixed (no pan/zoom) and full-bleed, so fewer sessions =
// proportionally fatter candles: at 14 they render ~80px wide, as solid blocks with
// stubby wicks. 26 lands at ~35px spacing, which is the normal candle proportion.
const RECENT_N = 26;

const MUTED = "var(--text-muted)";

const px = (anchor: number, cumReturn: number) =>
  (anchor * (1 + cumReturn)).toLocaleString("en-US", {
    maximumFractionDigits: 0,
  });

// Spans are OUR persisted quantiles. Deliberately not relabelled to the more familiar
// 95/68/50 of a Gaussian ±2σ/±1σ chart: v13 publishes q05..q95, and calling a 90%
// interval "95% confidence" would overstate the coverage the model was validated at.
const BAND_LEGEND: Array<[string, number]> = [
  ["50% (q25–q75)", 0.3],
  ["80% (q10–q90)", 0.18],
  ["90% (q05–q95)", 0.1],
];

const VIEWS: Array<[ConeView, string]> = [
  ["fan", "1–5 day fan"],
  ["focused", "Next session"],
];

// Panel chrome. `.section` / `.section-header` / `.section-body` is the repo-wide
// container contract (globals.css) — the same one GexSubTab uses, which is why the
// body padding is repeated here rather than inherited: `.section-body` ships with
// `padding: 0` and each panel opts in (`.gex-panel .section-body { padding: 16px }`).
function Shell({
  meta,
  header,
  children,
}: {
  meta?: React.ReactNode;
  header?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="section" data-testid="spx-density-panel">
      <div className="section-header">
        <div className="section-title">
          SPX 1–5D Density Cone
          {meta}
        </div>
        {header}
      </div>
      <div
        className="section-body"
        style={{
          padding: 16,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {children}
      </div>
    </div>
  );
}

export default function DensityConePanel() {
  const { data, loading, error } = useSpxDensity();
  const [view, setView] = useState<ConeView>("fan");
  const f = data?.forecast ?? null;

  if (loading && !data) {
    return (
      <Shell>
        <span style={{ color: MUTED, fontSize: 12 }}>
          Loading density cone…
        </span>
      </Shell>
    );
  }
  if (error || !f) {
    return (
      <Shell>
        <span style={{ color: MUTED, fontSize: 12 }}>
          {error
            ? `Density cone unavailable: ${error}`
            : "No density forecast issued yet."}
        </span>
      </Shell>
    );
  }

  const rows = f.rows;
  const recent = (data?.recent_path ?? []).slice(-RECENT_N);
  const levels = data?.gamma_levels ?? null;
  const closeOnly = recent.filter((p) => p.open == null).length;
  const head = rows[0];

  return (
    <Shell
      meta={
        <>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: MUTED,
              marginLeft: 8,
            }}
          >
            anchor {f.as_of} · {f.anchor_close.toFixed(2)} · GJR arm G/normal
            {f.origin === "reconstructed" ? " · RECONSTRUCTED" : ""}
          </span>
          {f.fallback_used && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--warning, #f59e0b)",
                marginLeft: 8,
              }}
            >
              EWMA FALLBACK — GJR fit unavailable
            </span>
          )}
        </>
      }
      header={
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{ display: "flex", gap: 4 }}
            data-testid="cone-view-toggle"
          >
            {VIEWS.map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setView(id)}
                aria-pressed={view === id}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  letterSpacing: 0.5,
                  textTransform: "uppercase",
                  padding: "3px 8px",
                  cursor: "pointer",
                  background:
                    view === id ? "var(--accent-bg, #1f2937)" : "transparent",
                  color: view === id ? "var(--text-primary)" : MUTED,
                  border: "1px solid var(--border-dim)",
                  borderRadius: 3,
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: MUTED,
            }}
          >
            DISPLAY ONLY · NOT A TRADING SIGNAL
          </span>
        </div>
      }
    >
      <DensityConeChart
        forecast={f}
        recentPath={recent}
        gammaLevels={levels}
        view={view}
      />

      <div
        data-testid="cone-band-legend"
        style={{
          display: "flex",
          gap: 14,
          flexWrap: "wrap",
          alignItems: "center",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: MUTED,
        }}
      >
        {BAND_LEGEND.map(([label, opacity]) => (
          <span
            key={label}
            style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
          >
            <span
              style={{
                width: 16,
                height: 9,
                background: "var(--accent-vol, #7c6cf0)",
                opacity,
                border: "1px solid var(--border-dim)",
              }}
            />
            {label}
          </span>
        ))}
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <span
            style={{ width: 16, borderTop: `1px dotted ${MUTED}`, height: 1 }}
          />
          median (not a forecast)
        </span>
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: MUTED,
          display: "flex",
          gap: 14,
          flexWrap: "wrap",
        }}
      >
        {view === "focused" && head && (
          <span data-testid="cone-focused-summary">
            {head.target_date} · proj high {px(f.anchor_close, head.q95)} ·
            median {px(f.anchor_close, head.q50)} · proj low{" "}
            {px(f.anchor_close, head.q05)}
            {head.density ? "" : " · no density bins for this cone"}
          </span>
        )}
        {/* Exception-only notes. The running commentary that used to live here (band
            widths, EWMA ratios, the level source, the p50 caveat) was removed as
            clutter; these two stay because they report a DEGRADED render — silence
            would otherwise read as a complete chart. */}
        {closeOnly > 0 && (
          <span data-testid="cone-ohlc-note">
            {closeOnly} session{closeOnly === 1 ? "" : "s"} close-only — no
            candle drawn
          </span>
        )}
        {levels && levels.dropped.length > 0 && (
          <span data-testid="cone-levels-note">
            {levels.dropped.join("/")} not drawn — wrong side of spot
          </span>
        )}
      </div>
    </Shell>
  );
}
