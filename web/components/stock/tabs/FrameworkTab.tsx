"use client";

import { useState } from "react";

import {
  BestSetupSection,
  CandidatesSection,
  CatalystSection,
  ConfluenceSection,
  ConvictionSection,
  type Framework,
  GammaSection,
  Pill,
  PitfallsSection,
  ThreeAxisSection,
  WhatChangesSection,
} from "@/components/stock/tabs/framework/FrameworkSections";
import {
  type Provider,
  PROVIDERS,
  useAiAnalysisPolling,
} from "@/components/stock/panels/tradeInsightsAi/useAiAnalysisPolling";

const PROVIDER_LABEL: Record<Provider, string> = {
  codex: "Codex",
  claude: "Claude",
  deepseek: "DeepSeek",
};

type ProviderState =
  | { kind: "framework"; framework: Framework }
  | { kind: "queued" }
  | { kind: "running" }
  | { kind: "failed"; reason: string }
  | { kind: "no-framework" }
  | { kind: "empty" };

function stateColor(kind: ProviderState["kind"]): string {
  switch (kind) {
    case "framework":
      return "var(--positive)";
    case "failed":
      return "var(--negative)";
    case "queued":
    case "running":
      return "var(--warning)";
    default:
      return "var(--text-muted)";
  }
}

function stateLabel(state: ProviderState): string {
  switch (state.kind) {
    case "framework":
      return "ready";
    case "queued":
      return "queued";
    case "running":
      return "running";
    case "failed":
      return "failed";
    case "no-framework":
      return "no framework";
    case "empty":
      return "not run";
  }
}

export function FrameworkTab({ ticker }: { ticker: string }) {
  const { latestForTicker, pendingIdsForTicker, runOne, unavailableForTicker } =
    useAiAnalysisPolling(ticker, "blast");
  const [active, setActive] = useState<Provider>("codex");

  const stateFor = (provider: Provider): ProviderState => {
    const pending = pendingIdsForTicker[provider];
    const latest = latestForTicker[provider];
    // In-flight re-run wins over stale terminal state
    if (pending || latest?.status === "running") return { kind: "running" };
    if (latest?.status === "queued") return { kind: "queued" };
    if (latest?.status === "failed") {
      return {
        kind: "failed",
        reason: latest.error_message ?? "unknown error",
      };
    }
    if (latest?.status === "succeeded") {
      const fw = latest.outcome?.framework ?? null;
      return fw
        ? { kind: "framework", framework: fw }
        : { kind: "no-framework" };
    }
    return { kind: "empty" };
  };

  const activeState = stateFor(active);

  // Consensus across providers that produced a framework (need >= 2).
  const frameworks = PROVIDERS.map((p) => stateFor(p)).filter(
    (s): s is { kind: "framework"; framework: Framework } =>
      s.kind === "framework",
  );
  let consensusBanner: string;
  if (frameworks.length < 2) {
    consensusBanner = "single provider — no cross-model consensus yet";
  } else {
    const positions = new Set(
      frameworks.map((s) => s.framework.header.position_type),
    );
    const structures = new Set(
      frameworks.map((s) => s.framework.best_setup.structure),
    );
    consensusBanner =
      positions.size === 1 && structures.size === 1
        ? `consensus: ${[...positions][0]} · ${[...structures][0]}`
        : `divergent: ${frameworks.length} providers disagree on position/structure`;
  }

  return (
    <div style={{ padding: "16px 20px", maxWidth: 920 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 14,
        }}
      >
        <h2 style={{ margin: 0, color: "var(--text-primary)" }}>
          {ticker} · Trade Plan
        </h2>
      </div>

      {unavailableForTicker ? (
        <p style={{ color: "var(--warning)" }}>
          Trade Insights AI is disabled on the server.
        </p>
      ) : null}

      <div
        style={{
          padding: "8px 12px",
          marginBottom: 14,
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          background: "var(--bg-panel)",
          color: "var(--text-secondary)",
          fontSize: 13,
        }}
      >
        {consensusBanner}
      </div>

      {/* Provider toggle with per-provider run buttons + state badges */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {PROVIDERS.map((p) => {
          const s = stateFor(p);
          const isActive = p === active;
          const pending = Boolean(pendingIdsForTicker[p]);
          return (
            <div key={p} style={{ display: "flex", gap: 0 }}>
              <button
                type="button"
                onClick={() => setActive(p)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 12px",
                  borderRadius: "4px 0 0 4px",
                  border: `1px solid ${
                    isActive ? "var(--text-secondary)" : "var(--border-dim)"
                  }`,
                  background: isActive ? "var(--bg-panel)" : "transparent",
                  color: "var(--text-primary)",
                  cursor: "pointer",
                }}
              >
                <span>{PROVIDER_LABEL[p]}</span>
                <Pill text={stateLabel(s)} color={stateColor(s.kind)} />
              </button>
              <button
                type="button"
                onClick={() => runOne(p, true)}
                disabled={pending}
                title={`Run ${PROVIDER_LABEL[p]}`}
                style={{
                  borderTop: `1px solid ${
                    isActive ? "var(--text-secondary)" : "var(--border-dim)"
                  }`,
                  borderRight: `1px solid ${
                    isActive ? "var(--text-secondary)" : "var(--border-dim)"
                  }`,
                  borderBottom: `1px solid ${
                    isActive ? "var(--text-secondary)" : "var(--border-dim)"
                  }`,
                  borderLeft: "none",
                  borderRadius: "0 4px 4px 0",
                  background: pending ? "var(--bg-panel)" : "transparent",
                  color: pending
                    ? "var(--text-muted)"
                    : "var(--text-secondary)",
                  cursor: pending ? "not-allowed" : "pointer",
                  padding: "6px 8px",
                  fontSize: 11,
                  lineHeight: 1,
                }}
              >
                ▶
              </button>
            </div>
          );
        })}
      </div>

      {/* Active provider's decision stack */}
      {activeState.kind === "framework" ? (
        <FrameworkStack fw={activeState.framework} />
      ) : (
        <div
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            border: "1px dashed var(--border-dim)",
            borderRadius: 6,
          }}
        >
          {activeState.kind === "failed"
            ? `Analysis failed: ${activeState.reason}`
            : activeState.kind === "no-framework"
              ? "This provider's analysis has no framework block."
              : activeState.kind === "empty"
                ? "No analysis yet — run it to generate a framework."
                : "Analysis in progress…"}
        </div>
      )}
    </div>
  );
}

function FrameworkStack({ fw }: { fw: Framework }) {
  return (
    <div>
      {fw.header.thesis_one_liner ? (
        <p
          style={{
            color: "var(--text-primary)",
            fontWeight: 600,
            fontSize: 15,
            marginBottom: 12,
          }}
        >
          <Pill text={fw.header.position_type} /> {fw.header.thesis_one_liner}
        </p>
      ) : null}
      <ThreeAxisSection fw={fw} />
      <GammaSection fw={fw} />
      <CatalystSection fw={fw} />
      <ConvictionSection fw={fw} />
      <ConfluenceSection fw={fw} />
      <PitfallsSection fw={fw} />
      <CandidatesSection fw={fw} />
      <BestSetupSection fw={fw} />
      <WhatChangesSection fw={fw} />
    </div>
  );
}
