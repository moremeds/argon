"use client";

import InfoTooltip from "../InfoTooltip";
import { type VcgSignal } from "@/lib/regime/useVcg";
import {
  formatPctRank,
  pctRankColor,
  tierColor,
  tierLabel,
  vvixSeverityColor,
  vvixSeverityDesc,
} from "./format";

/* Signal Detail, left card: tier + VVIX severity + vol percentiles + EDR/bounce. */
export default function VcgSignalTiers({ sig }: { sig: VcgSignal }) {
  return (
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
              sig.tier != null ? `${tierColor(sig.tier)}18` : "transparent",
            padding: "2px 8px",
            borderRadius: "999px",
            border:
              sig.tier != null ? `1px solid ${tierColor(sig.tier)}40` : "none",
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
          borderBottom: "1px solid var(--border-dim, var(--line-grid))",
        }}
      >
        <div>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "10px",
              color: "var(--text-muted)",
            }}
          >
            VIX 252d %ile
          </span>
          <InfoTooltip text="VIX level's 252-day rolling percentile rank (strict_lt tie rule). When BOTH VIX and VVIX percentile ranks clear 0.95, the v2 cascade fires RISK_OFF via the absolute-vol-stress override — bypassing the sign-discipline SUPPRESSED clause that masked PANIC days in v1." />
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            fontWeight: 700,
            color: pctRankColor(sig.vix_percentile_rank),
          }}
          data-testid="vcg-vix-pct-rank"
        >
          {formatPctRank(sig.vix_percentile_rank)}
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
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "10px",
            color: "var(--text-muted)",
          }}
        >
          VVIX 252d %ile
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            fontWeight: 700,
            color: pctRankColor(sig.vvix_percentile_rank),
          }}
          data-testid="vcg-vvix-pct-rank"
        >
          {formatPctRank(sig.vvix_percentile_rank)}
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
  );
}
