import type { Provider, ProviderAnalysisPair, ProviderPendingPair } from "./useAiAnalysisPolling";

function providerLabel(p: Provider): string {
  return p.charAt(0).toUpperCase() + p.slice(1);
}

function stateBadge(
  analysis: ProviderAnalysisPair[Provider],
  pending: boolean,
): string {
  if (pending) return "◐";
  if (!analysis) return "○";
  if (analysis.status === "succeeded") return "●";
  if (analysis.status === "failed") return "✕";
  return "○";
}

export function ProviderTabBar({
  active,
  latest,
  pendingIds,
  providers,
  setActive,
}: {
  active: Provider;
  latest: ProviderAnalysisPair;
  pendingIds: ProviderPendingPair;
  providers: readonly Provider[];
  setActive: (provider: Provider) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {providers.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => setActive(p)}
          data-testid={`ai-tab-${p}`}
          style={{
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            background: active === p ? "var(--bg-panel)" : "var(--bg-base)",
            color: "var(--text-primary)",
            cursor: "pointer",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            padding: "5px 10px",
          }}
        >
          {providerLabel(p)}{" "}
          <span aria-hidden="true">
            {stateBadge(latest[p], Boolean(pendingIds[p]))}
          </span>
        </button>
      ))}
    </div>
  );
}
