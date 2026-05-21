"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { RegimeVcgResponse } from "@/lib/api";

const PANEL: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 12,
  fontFamily: "var(--font-mono)",
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const LABEL: React.CSSProperties = {
  fontSize: 9,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

function interpColor(interp: string | null | undefined): string {
  switch (interp) {
    case "PANIC":
    case "RISK_OFF":
      return "var(--negative)";
    case "EDR":
    case "WATCH":
      return "var(--warning)";
    case "BOUNCE":
    case "NORMAL":
      return "var(--positive)";
    case "SUPPRESSED":
      return "var(--accent-vol)";
    default:
      return "var(--text-muted)";
  }
}

export function MacroVcgTile() {
  const [data, setData] = useState<RegimeVcgResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .regimeVcg()
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const signal = data?.signal;
  const interp = signal?.interpretation ?? null;
  const vcg = signal?.vcg ?? null;
  const regime = signal?.regime ?? null;

  const color = interpColor(interp);

  return (
    <div style={PANEL} data-testid="macro-vcg-tile">
      <div style={LABEL}>Macro VCG</div>
      <div style={{ fontSize: 16, fontWeight: 700, color }}>
        {interp ?? "—"}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
        regime: {regime ?? "—"} · vcg = {vcg != null ? vcg.toFixed(2) : "—"}
      </div>
    </div>
  );
}
