"use client";

import { useState } from "react";

import {
  BestSetupSection,
  CandidatesSection,
  CatalystSection,
  ConfluenceSection,
  ConvictionSection,
  EntryStateStrip,
  entryStateAutoCorrectNote,
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

const PROVIDER_LABEL: Partial<Record<Provider, string>> = {
  deepseek: "DeepSeek",
};

type ProviderState =
  | {
      kind: "framework";
      framework: Framework;
      entryState: string | null;
      missingData: string[];
    }
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
  const [active, setActive] = useState<Provider>("deepseek");

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
      if (!fw) return { kind: "no-framework" };
      return {
        kind: "framework",
        framework: fw,
        entryState: latest.outcome?.headline?.entry_state ?? null,
        missingData: latest.outcome?.missing_data ?? [],
      };
    }
    return { kind: "empty" };
  };

  const activeState = stateFor(active);

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
                <span>{PROVIDER_LABEL[p] ?? p}</span>
                <Pill text={stateLabel(s)} color={stateColor(s.kind)} />
              </button>
              <button
                type="button"
                onClick={() => runOne(p, true)}
                disabled={pending}
                title={`Run ${PROVIDER_LABEL[p] ?? p}`}
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
        <FrameworkStack
          fw={activeState.framework}
          entryState={activeState.entryState}
          missingData={activeState.missingData}
        />
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

function FrameworkStack({
  fw,
  entryState,
  missingData,
}: {
  fw: Framework;
  entryState: string | null;
  missingData: readonly string[];
}) {
  const autoCorrectNote = entryStateAutoCorrectNote(missingData);
  return (
    <div>
      <EntryStateStrip
        entryState={entryState}
        autoCorrectNote={autoCorrectNote}
      />
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
