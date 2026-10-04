"use client";

import { formatNumber } from "../primitives/format";
import { type VcgSignal } from "@/lib/regime/useVcg";
import { clampPct } from "./format";

/* Signal Detail, right card: VVIX/VIX attribution bars + betas. */
export default function VcgAttribution({
  sig,
  attr,
}: {
  sig: VcgSignal;
  attr: NonNullable<VcgSignal["attribution"]>;
}) {
  return (
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
  );
}
