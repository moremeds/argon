"use client";

import { Bird } from "lucide-react";

import { useCanary, useCanaryHistory } from "@/lib/regime/useCanary";

import { CanaryHistoryTable } from "./canary/CanaryHistoryTable";
import { CanaryScoreChart } from "./canary/CanaryScoreChart";
import { ComponentBar } from "./primitives/ComponentBar";
import { RegimePill, type RegimePillState } from "./primitives/RegimePill";

// 252 ≈ one trading year — enough to span a full vol cycle in the chart and
// give the sortable history table meaningful depth.
const HISTORY_DAYS = 252;

function CanaryShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="section gex-panel">
      <div className="section-header">
        <div className="section-title">
          <Bird size={14} />
          5% Canary — Dip-Buy Composite
        </div>
      </div>
      <div className="section-body">{children}</div>
    </div>
  );
}

export default function CanarySubTab() {
  const { data: latest, error: latestErr } = useCanary();
  const { data: history } = useCanaryHistory(HISTORY_DAYS);

  if (latestErr) {
    return (
      <CanaryShell>
        <div className="regime-empty" data-testid="canary-empty-state">
          No 5% Canary snapshot at the current composite_version yet.
        </div>
      </CanaryShell>
    );
  }
  if (!latest) {
    return (
      <CanaryShell>
        <div data-testid="canary-loading">Loading…</div>
      </CanaryShell>
    );
  }

  // The full structured payload sits under `latest.payload` per the API.
  // It's strongly typed at the source but `unknown` here — narrow with
  // explicit field reads.
  const p = latest.payload as {
    canary: { warning_state: string };
    tactical_vol: {
      vix_spike_revert: { score: number };
      vix_vix3m_back: { score: number };
    };
    structural_vol: {
      vrp: { score: number };
      cor1m_decay: { score: number };
      vvix_vix_recovery: { score: number };
    };
    speed: { score: number; state: string };
  };

  const warning = p.canary.warning_state as RegimePillState;
  const speedState = p.speed.state as RegimePillState;

  return (
    <CanaryShell>
      <div className="regime-panel-inner" data-testid="canary-subtab">
        <header
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            marginBottom: 24,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 40,
                fontWeight: 600,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {latest.score.toFixed(1)}
            </div>
            <div
              style={{
                fontSize: 12,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              {latest.band.replace("_", " ")} · score_form: {latest.score_form}
            </div>
          </div>
          <RegimePill state={warning} />
        </header>

        <section style={{ marginBottom: 24 }}>
          <h3
            style={{
              fontSize: 10,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: 8,
            }}
          >
            Tactical Vol (0–30)
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <ComponentBar
              label="VIX Spike Reversion"
              score={p.tactical_vol.vix_spike_revert.score}
              max={15}
            />
            <ComponentBar
              label="VIX/VIX3M Backwardation Normalize"
              score={p.tactical_vol.vix_vix3m_back.score}
              max={15}
            />
          </div>
        </section>

        <section style={{ marginBottom: 24 }}>
          <h3
            style={{
              fontSize: 10,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: 8,
            }}
          >
            Structural Vol (0–50)
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <ComponentBar
              label="Variance Risk Premium"
              score={p.structural_vol.vrp.score}
              max={21}
            />
            <ComponentBar
              label="COR1M Peak-and-Decay"
              score={p.structural_vol.cor1m_decay.score}
              max={17}
            />
            <ComponentBar
              label="VVIX/VIX Recovery"
              score={p.structural_vol.vvix_vix_recovery.score}
              max={12}
            />
          </div>
        </section>

        <section style={{ marginBottom: 24 }}>
          <h3
            style={{
              fontSize: 10,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: 8,
            }}
          >
            Price Speed (Thrasher)
          </h3>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <RegimePill state={speedState} />
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {p.speed.score} of 20 pts
            </span>
          </div>
        </section>

        {history && history.rows.length > 0 && (
          <>
            <section style={{ marginBottom: 24 }}>
              <CanaryScoreChart
                history={history.rows}
                title={`Composite score — last ${history.rows.length} sessions`}
              />
            </section>
            <section>
              <CanaryHistoryTable history={history.rows} />
            </section>
          </>
        )}
      </div>
    </CanaryShell>
  );
}
