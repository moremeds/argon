"use client";

import { AlertTriangle, Shield, TrendingUp, Zap } from "lucide-react";

import InfoTooltip from "./InfoTooltip";
import { VcgHistoryTable } from "./vcg/VcgHistoryTable";
import {
  type VcgResponse,
  type VcgSignal,
  useVcg,
} from "@/lib/regime/useVcg";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "./primitives/format";

/* ─── Helpers (1:1 port from xenon VcgPanel.tsx) ───────────────── */

// Persisted attribution percentages should already sum to 100, but the UI
// renders from JSONB and a corrupted/backfilled payload could surface NaN,
// Infinity, or values > 100 — clamp defensively so the bar can't overflow.
function clampPct(v: number | null | undefined): number {
  if (v == null || !Number.isFinite(v)) return 0;
  return Math.min(100, Math.max(0, v));
}

function interpretationColor(interpretation: string): string {
  switch (interpretation) {
    case "RISK_OFF":
      return "var(--fault, var(--negative))";
    case "EDR":
    case "WATCH":
      return "var(--warning)";
    case "BOUNCE":
    case "NORMAL":
      return "var(--signal-core, var(--positive))";
    case "PANIC":
      return "var(--extreme, var(--negative))";
    case "SUPPRESSED":
      return "var(--text-muted)";
    default:
      return "var(--text-muted)";
  }
}

function interpretationLabel(interpretation: string): string {
  switch (interpretation) {
    case "RISK_OFF":
      return "RISK-OFF";
    case "EDR":
      return "EARLY DIVERGENCE";
    case "WATCH":
      return "WATCH";
    case "BOUNCE":
      return "BOUNCE";
    case "NORMAL":
      return "NORMAL";
    case "PANIC":
      return "PANIC";
    case "SUPPRESSED":
      return "SUPPRESSED";
    default:
      return "INSUFFICIENT DATA";
  }
}

function regimeBadgeColor(regime: string): string {
  switch (regime) {
    case "PANIC":
      return "var(--extreme, var(--negative))";
    case "TRANSITION":
      return "var(--warning)";
    default:
      return "var(--signal-core, var(--positive))";
  }
}

function tierColor(tier: number | null | undefined): string {
  switch (tier) {
    case 1:
    case 2:
      return "var(--fault, var(--negative))";
    case 3:
      return "var(--warning)";
    default:
      return "var(--text-muted)";
  }
}

function tierLabel(tier: number | null | undefined): string {
  switch (tier) {
    case 1:
      return "TIER 1 — CRITICAL";
    case 2:
      return "TIER 2 — HIGH";
    case 3:
      return "TIER 3 — ELEVATED";
    default:
      return "NO ACTIVE TIER";
  }
}

function vvixSeverityColor(sev: string): string {
  switch (sev) {
    case "extreme":
      return "var(--fault, var(--negative))";
    case "elevated":
      return "var(--warning)";
    default:
      return "var(--signal-core, var(--positive))";
  }
}

function vvixSeverityDesc(sev: string): string {
  switch (sev) {
    case "extreme":
      return "VVIX far above 120 — maximum vol-of-vol stress";
    case "elevated":
      return "VVIX above 110 — second-order stress signal";
    default:
      return "VVIX below 110 — vol regime stable";
  }
}

/* ─── Main view (1:1 mirror of xenon VcgPanel) ───────────────── */

export function VcgSubTabView({
  data,
  onSyncNow,
  syncing = false,
}: {
  data: VcgResponse | null;
  onSyncNow?: () => void;
  syncing?: boolean;
}) {
  if (
    !data ||
    data.status === "empty" ||
    (!data.signal?.vcg && data.signal?.vcg !== 0)
  ) {
    return (
      <div className="regime-empty" data-testid="vcg-empty-state">
        <Shield size={32} strokeWidth={1} />
        <p>
          No VCG data available. Click Sync Now to run a scan for{" "}
          {data?.credit_proxy ?? "HYG"}.
        </p>
        {onSyncNow && (
          <button
            type="button"
            onClick={onSyncNow}
            disabled={syncing}
            data-testid="vcg-sync-now"
            style={{
              marginTop: "12px",
              padding: "6px 14px",
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              background: "var(--bg-panel-raised, var(--bg-panel))",
              border: "1px solid var(--border-dim, var(--line-grid))",
              color: "var(--text-primary)",
              cursor: syncing ? "default" : "pointer",
              opacity: syncing ? 0.6 : 1,
            }}
          >
            {syncing ? "Syncing…" : "Sync Now"}
          </button>
        )}
      </div>
    );
  }

  const sig: VcgSignal = data.signal;
  const attr = sig.attribution ?? {
    vvix_pct: 0,
    vix_pct: 0,
    vvix_component: 0,
    vix_component: 0,
    model_implied: 0,
  };
  const interpColor = interpretationColor(sig.interpretation);
  const lastSync = data.scan_time;
  const history = data.history ?? [];

  return (
    <div className="regime-panel" data-testid="vcg-subtab">
      {/* ── Signal strip ───────────────────────────────────── */}
      <div className="section">
        <div className="section-header">
          <div className="section-title">
            <Zap size={14} />
            VCG Signal
            <InfoTooltip text="Volatility-Credit Gap: detects divergence between the vol complex (VIX/VVIX) and credit markets (HYG/JNK/LQD). Signals: RISK_OFF (tier 1–2), EDR (early divergence), BOUNCE (counter-signal), NORMAL." />
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              flexWrap: "wrap",
            }}
          >
            {/* Regime badge */}
            <span
              className="pill"
              style={{
                background: regimeBadgeColor(sig.regime),
                color: "#fff",
                fontSize: "9px",
              }}
              data-testid="vcg-regime-badge"
            >
              {sig.regime}
            </span>
            {/* RISK-OFF */}
            {sig.ro === 1 && (
              <span
                className="pill"
                style={{
                  background: "var(--fault, var(--negative))",
                  color: "#fff",
                  fontSize: "9px",
                }}
                data-testid="vcg-ro-badge"
              >
                <AlertTriangle size={10} style={{ marginRight: "3px" }} />
                RISK-OFF
              </span>
            )}
            {/* EDR (only when not already RISK-OFF) */}
            {sig.edr === 1 && sig.ro !== 1 && (
              <span
                className="pill"
                style={{
                  background: "var(--warning)",
                  color: "#000",
                  fontSize: "9px",
                  fontWeight: 700,
                }}
                data-testid="vcg-edr-badge"
              >
                EDR
              </span>
            )}
            {/* Tier badge */}
            {sig.tier != null && (
              <span
                className="pill"
                style={{
                  background: tierColor(sig.tier),
                  color: "#fff",
                  fontSize: "9px",
                }}
                data-testid="vcg-tier-badge"
              >
                T{sig.tier}
              </span>
            )}
            {/* Bounce */}
            {sig.bounce === 1 && (
              <span
                className="pill"
                style={{
                  background: "var(--signal-core, var(--positive))",
                  color: "#000",
                  fontSize: "9px",
                  fontWeight: 700,
                }}
                data-testid="vcg-bounce-badge"
              >
                <TrendingUp size={10} style={{ marginRight: "3px" }} />
                BOUNCE
              </span>
            )}
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "9px",
                color: "var(--text-muted)",
              }}
              data-testid="vcg-proxy"
            >
              {data.credit_proxy}
            </span>
            {lastSync && (
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "9px",
                  color: "var(--text-muted)",
                }}
              >
                {new Date(lastSync).toLocaleTimeString("en-US", {
                  hour: "numeric",
                  minute: "2-digit",
                })}
              </span>
            )}
          </div>
        </div>

        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-label">VCG Z-Score</div>
            <div
              className="metric-value"
              style={{ color: interpColor }}
              data-testid="vcg-z-score"
            >
              {formatSignedNumber(sig.vcg)}
            </div>
            <div className="metric-change" style={{ color: interpColor }}>
              {interpretationLabel(sig.interpretation)}
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">VCG Adj (Panic-Adj)</div>
            <div className="metric-value">{formatSignedNumber(sig.vcg_adj)}</div>
            <div className="metric-change neutral">
              {sig.pi_panic > 0
                ? `π = ${sig.pi_panic.toFixed(2)} SUPPRESSED`
                : "NO SUPPRESSION"}
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Credit 5d Return</div>
            <div
              className={`metric-value ${
                sig.credit_5d_return_pct >= 0 ? "positive" : "negative"
              }`}
            >
              {formatPercent(sig.credit_5d_return_pct)}
            </div>
            <div className="metric-change neutral">
              {data.credit_proxy} @ ${formatNumber(sig.credit_price)}
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Residual</div>
            <div className="metric-value">
              {sig.residual != null ? sig.residual.toFixed(6) : "---"}
            </div>
            <div className="metric-change neutral">MODEL ε</div>
          </div>
        </div>
      </div>

      {/* ── Signal Detail + Attribution ─────────────────────── */}
      <div className="section">
        <div className="section-header">
          <div className="section-title">
            <Zap size={14} />
            Signal Detail
            <InfoTooltip text="Severity tier (1=critical, 2=high, 3=elevated), VVIX amplifier, and bounce conditions. Tier activates when ro=1 (Tier 1/2) or edr=1 (Tier 3)." />
          </div>
          <span
            className="pill"
            style={{
              background: interpColor,
              color:
                sig.interpretation === "NORMAL" ||
                sig.interpretation === "BOUNCE"
                  ? "#000"
                  : "#fff",
              fontSize: "9px",
            }}
            data-testid="vcg-interpretation-pill"
          >
            {interpretationLabel(sig.interpretation)}
          </span>
        </div>

        <div
          className="metrics-grid"
          style={{ gridTemplateColumns: "1fr 1fr" }}
        >
          {/* Left: Tier + VVIX severity + EDR/Bounce */}
          <div className="metric-card" style={{ padding: "12px 16px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                paddingBottom: "8px",
                borderBottom: "1px solid var(--border-dim, var(--line-grid))",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "10px",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  color: "var(--text-muted)",
                }}
              >
                Severity Tier
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  fontWeight: 700,
                  color: tierColor(sig.tier),
                  background:
                    sig.tier != null
                      ? `${tierColor(sig.tier)}18`
                      : "transparent",
                  padding: "2px 8px",
                  borderRadius: "999px",
                  border:
                    sig.tier != null
                      ? `1px solid ${tierColor(sig.tier)}40`
                      : "none",
                }}
                data-testid="vcg-tier-label"
              >
                {tierLabel(sig.tier)}
              </span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "8px 0",
                borderBottom: "1px solid var(--border-dim, var(--line-grid))",
              }}
            >
              <div>
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "10px",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                    color: "var(--text-muted)",
                  }}
                >
                  VVIX Severity
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "9px",
                    color: "var(--text-muted)",
                    marginTop: "2px",
                  }}
                >
                  {vvixSeverityDesc(sig.vvix_severity)}
                </div>
              </div>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  fontWeight: 700,
                  color: vvixSeverityColor(sig.vvix_severity),
                  textTransform: "uppercase",
                  marginLeft: "12px",
                  flexShrink: 0,
                }}
                data-testid="vcg-vvix-severity"
              >
                {sig.vvix_severity}
              </span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "8px 0",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "10px",
                  color: "var(--text-muted)",
                }}
              >
                EDR
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  fontWeight: 700,
                  color: sig.edr === 1 ? "var(--warning)" : "var(--text-muted)",
                }}
                data-testid="vcg-edr-state"
              >
                {sig.edr === 1 ? "ACTIVE" : "INACTIVE"}
              </span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                paddingTop: "0",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "10px",
                  color: "var(--text-muted)",
                }}
              >
                Bounce
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  fontWeight: 700,
                  color:
                    sig.bounce === 1
                      ? "var(--signal-core, var(--positive))"
                      : "var(--text-muted)",
                }}
                data-testid="vcg-bounce-state"
              >
                {sig.bounce === 1 ? "DETECTED" : "—"}
              </span>
            </div>
          </div>

          {/* Right: Attribution bars */}
          <div className="metric-card" style={{ padding: "12px 16px" }}>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "10px",
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                color: "var(--text-muted)",
                marginBottom: "8px",
              }}
            >
              Attribution
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                marginBottom: "8px",
              }}
            >
              <div
                style={{
                  flex: 1,
                  height: "6px",
                  borderRadius: "3px",
                  background: "var(--bg-panel-raised, var(--bg-panel))",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${clampPct(attr.vvix_pct)}%`,
                    height: "100%",
                    background: "var(--extreme, var(--negative))",
                    borderRadius: "3px",
                  }}
                  data-testid="vcg-attr-vvix-bar"
                />
              </div>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  color: "var(--text-primary)",
                  minWidth: "60px",
                }}
              >
                VVIX {clampPct(attr.vvix_pct).toFixed(0)}%
              </span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                marginBottom: "12px",
              }}
            >
              <div
                style={{
                  flex: 1,
                  height: "6px",
                  borderRadius: "3px",
                  background: "var(--bg-panel-raised, var(--bg-panel))",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${clampPct(attr.vix_pct)}%`,
                    height: "100%",
                    background: "var(--signal-core, var(--positive))",
                    borderRadius: "3px",
                  }}
                  data-testid="vcg-attr-vix-bar"
                />
              </div>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  color: "var(--text-primary)",
                  minWidth: "60px",
                }}
              >
                VIX {clampPct(attr.vix_pct).toFixed(0)}%
              </span>
            </div>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "10px",
                color: "var(--text-muted)",
                borderTop: "1px solid var(--border-dim, var(--line-grid))",
                paddingTop: "8px",
              }}
            >
              β₁(VVIX) = {formatNumber(sig.beta1_vvix, 6)} | β₂(VIX) ={" "}
              {formatNumber(sig.beta2_vix, 6)}
              {sig.sign_suppressed && (
                <span style={{ color: "var(--warning)", marginLeft: "8px" }}>
                  SIGN REVERSED
                </span>
              )}
            </div>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "10px",
                color: "var(--text-muted)",
                marginTop: "6px",
              }}
            >
              VVIX {formatNumber(sig.vvix)} · VIX {formatNumber(sig.vix)}
            </div>
          </div>
        </div>
      </div>

      {/* ── History table (sortable) ────────────────────────── */}
      <div className="section">
        <div className="section-header">
          <div className="section-title">VCG History (20d)</div>
        </div>
        <div className="section-body table-wrap">
          <VcgHistoryTable history={history} creditProxy={data.credit_proxy} />
        </div>
      </div>
    </div>
  );
}

export default function VcgSubTab() {
  const { data, syncing, syncNow } = useVcg();
  return <VcgSubTabView data={data} syncing={syncing} onSyncNow={syncNow} />;
}
