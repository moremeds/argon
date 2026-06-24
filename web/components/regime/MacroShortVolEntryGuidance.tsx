"use client";

import { useState } from "react";

import MacroShortVolSizingTable from "./MacroShortVolSizingTable";
import { regimeApi } from "@/lib/regime/api";
import { useVrpMacroLive } from "@/lib/regime/useVrpMacroLive";
import {
  useVrpMacroEntryPreview,
  type VrpMacroEntryLeg,
} from "@/lib/regime/useVrpMacroEntryPreview";

const f = (x: number | null | undefined, d = 2) =>
  x == null ? "—" : x.toFixed(d);

const legMid = (l: VrpMacroEntryLeg): number | null =>
  l.nbbo_bid != null && l.nbbo_ask != null
    ? (l.nbbo_bid + l.nbbo_ask) / 2
    : null;

// leg-name → display label (Δ magnitude + bracket side)
const LEG_LABEL: Record<string, string> = {
  short_above: "0.25↑",
  short_below: "0.25↓",
  wing_above: "0.125↑",
  wing_below: "0.125↓",
};
const LEG_ORDER = ["short_above", "short_below", "wing_above", "wing_below"];

// Capital unit for the live sizing line + the contract multiplier (max_loss is
// quoted in index points). base_risk_pct levels mirror the static guidance table.
const CAPITAL_UNIT = 60_000;
const CONTRACT_MULTIPLIER = 100;
const REC_BRP = [0.2, 0.32, 0.5];

/**
 * The tracked-entry + sizing-guidance row for the macro short-vol signal,
 * rendered full-width below the bias row as TWO cards: a smaller tracked-entry
 * card (ETD + the 4 bracketing puts + a one-click Capture) and a larger guidance
 * card (the static 2006–2026 backtest table + a live $60k-unit sizing line).
 *
 * Owns both hooks because the live $60k line needs the signal's modeled max_loss
 * (on TRADE) AND the preview bracket (on SKIP).
 */
export default function MacroShortVolEntryGuidance() {
  const { data } = useVrpMacroLive();
  const { data: preview } = useVrpMacroEntryPreview();
  const [capturing, setCapturing] = useState(false);
  const [capturedId, setCapturedId] = useState<number | null>(null);
  const [captureError, setCaptureError] = useState(false);

  const capture = async () => {
    if (capturing) return; // debounce: one-shot, non-idempotent write
    setCapturing(true);
    setCaptureError(false);
    try {
      const res = await fetch(regimeApi.vrp_macro_entry_capture(), {
        method: "POST",
      });
      if (!res.ok) throw new Error(String(res.status));
      const body = await res.json();
      setCapturedId(body.entry_id ?? null);
    } catch {
      setCaptureError(true);
    } finally {
      setCapturing(false);
    }
  };

  const s = data?.signal ?? null;
  const legs = (preview?.legs ?? [])
    .slice()
    .sort((a, b) => LEG_ORDER.indexOf(a.leg) - LEG_ORDER.indexOf(b.leg));

  // Live per-spread economics for the user's capital unit. max_loss is in index
  // points (put_width − credit); ×100 → dollars. On TRADE the signal's modeled
  // max_loss is authoritative; on SKIP we derive it from the preview bracket
  // (both candidate verticals are the same width here → outer width − modeled
  // credit). This is exactly desired_contracts() at full size, evaluated on
  // TODAY's strikes — NOT the static table's 2006–2026 average ($15.7k). At SPX
  // ~7445 one spread now costs ~$28k margin (1.8× that average), so $60k is
  // sub-scale: floor(brp × $60k / margin) is 0 at the recommended 0.20–0.32.
  const legStrike = (name: string) =>
    preview?.legs?.find((l) => l.leg === name)?.strike ?? null;
  const maxLossPts: number | null = (() => {
    if (s?.max_loss != null) return s.max_loss;
    const sa = legStrike("short_above");
    const wa = legStrike("wing_above");
    const c = preview?.modeled_credit;
    return sa != null && wa != null && c != null ? sa - wa - c : null;
  })();
  const marginPerSpread =
    maxLossPts != null && maxLossPts > 0
      ? maxLossPts * CONTRACT_MULTIPLIER
      : null;
  const spreadsAt = (brp: number) =>
    marginPerSpread != null
      ? Math.floor((brp * CAPITAL_UNIT) / marginPerSpread)
      : null;
  const liveSizingNote =
    marginPerSpread != null ? (
      <>
        <div>
          LIVE · ${(CAPITAL_UNIT / 1000).toFixed(0)}k unit — 1 spread ≈ $
          {(marginPerSpread / 1000).toFixed(1)}k margin ≈{" "}
          {((marginPerSpread / CAPITAL_UNIT) * 100).toFixed(0)}% of $
          {(CAPITAL_UNIT / 1000).toFixed(0)}k
        </div>
        <div>
          Full-size rung →{" "}
          {REC_BRP.map(
            (brp) => `brp ${brp.toFixed(2)}: ${spreadsAt(brp)}`,
          ).join(" · ")}
        </div>
      </>
    ) : null;

  return (
    <div
      style={{
        display: "grid",
        // entry card narrow (4 short columns), guidance card wide (8 columns +
        // footnotes — it carries far more content per row).
        gridTemplateColumns: "1fr 1.9fr",
        gap: 8,
        alignItems: "stretch", // both cards share the taller card's height
      }}
    >
      {/* smaller: tracked-entry card — mirrors the guidance card's structure
          (.gex-range-container → title → table-wrap → table) so the two tables'
          header rows line up exactly. The Capture controls float top-right, out
          of normal flow, so they can't push the title (and the thead) down. */}
      <div
        className="gex-range-container"
        style={{ position: "relative" }}
        data-testid="macro-shortvol-entry-card"
      >
        <div
          style={{
            position: "absolute",
            top: 12,
            right: 12,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          {/* status badge sits to the LEFT of the button */}
          {capturedId != null && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--positive)",
              }}
            >
              Captured #{capturedId}
            </span>
          )}
          {captureError && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--negative)",
              }}
            >
              Capture failed
            </span>
          )}
          <button
            type="button"
            onClick={capture}
            disabled={capturing}
            data-testid="capture-entry-btn"
            style={{
              // match the card header (.gex-range-title) typography
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              color: "var(--text-muted)",
              padding: "4px 10px",
              background: "var(--bg-panel)",
              border: "1px solid var(--border-dim)",
              cursor: capturing ? "default" : "pointer",
              opacity: capturing ? 0.5 : 1,
            }}
          >
            {capturing ? "Capturing…" : "Capture"}
          </button>
        </div>
        <div className="gex-range-title">
          Tracked entry · ETD {preview?.expiry ?? "—"}
        </div>
        {legs.length === 0 ? (
          <div className="gex-bias-reason">No entry preview yet.</div>
        ) : (
          <div className="gex-history-table-wrap">
            <table className="gex-history-table">
              <thead>
                <tr>
                  <th>Leg</th>
                  <th style={{ textAlign: "right" }}>Strike</th>
                  <th style={{ textAlign: "right" }}>Mid</th>
                  <th style={{ textAlign: "right" }}>Delta</th>
                </tr>
              </thead>
              <tbody>
                {legs.map((l) => (
                  <tr key={l.leg} data-testid={`entry-leg-${l.leg}`}>
                    <td style={{ color: "var(--text-muted)" }}>
                      {LEG_LABEL[l.leg] ?? l.leg}
                    </td>
                    <td style={{ textAlign: "right" }}>{f(l.strike, 0)}</td>
                    <td
                      style={{ textAlign: "right", color: "var(--text-muted)" }}
                    >
                      {f(legMid(l))}
                    </td>
                    <td
                      style={{ textAlign: "right", color: "var(--text-muted)" }}
                    >
                      {/* greeks_source "none" → no IV could be marked, so the
                          zeros are uninitialised defaults, not a real 0Δ */}
                      {l.greeks_source === "none" ? "—" : f(l.delta, 3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {liveSizingNote != null && (
          <div
            data-testid="macro-shortvol-unit-sizing"
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-muted)",
              lineHeight: 1.6,
              marginTop: 12,
            }}
          >
            {liveSizingNote}
          </div>
        )}
      </div>

      {/* larger: guidance (static 2006–2026 backtest table) */}
      <MacroShortVolSizingTable />
    </div>
  );
}
