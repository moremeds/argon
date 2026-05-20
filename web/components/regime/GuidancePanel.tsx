"use client";

import { useEffect, useState } from "react";

import type { components } from "@/lib/types";
import { regimeApi } from "@/lib/regime/api";

type GuidanceResponse = components["schemas"]["GuidanceResponse"];

function postureColor(posture: string): string {
  switch (posture) {
    case "opportunistic":
      return "var(--positive)";
    case "neutral":
      return "var(--text-muted)";
    case "cautious":
      return "var(--warning)";
    case "defensive":
      return "var(--negative)";
    default:
      return "var(--text-primary)";
  }
}

export function GuidancePanel() {
  const [guidance, setGuidance] = useState<GuidanceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(regimeApi.guidance())
      .then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)),
      )
      .then((data) => {
        if (!cancelled) setGuidance(data);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return null;
  if (!guidance) return null;

  return (
    <div className="regime-guidance-panel" data-testid="guidance-panel">
      <div className="regime-guidance-header">
        <span className="regime-guidance-state">
          {guidance.state.replace(/_/g, " ").toUpperCase()}
        </span>
        <span className="regime-guidance-arrow">→</span>
        <span
          className="regime-guidance-posture"
          style={{ color: postureColor(guidance.posture) }}
          data-testid="guidance-posture"
        >
          {guidance.posture.toUpperCase()}
        </span>
      </div>
      <div className="regime-guidance-body">{guidance.body_md}</div>
    </div>
  );
}
