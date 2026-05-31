import type {
  Provider,
  ProviderAnalysisPair,
  ProviderPendingPair,
} from "./useAiAnalysisPolling";

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
  onRun,
}: {
  active: Provider;
  latest: ProviderAnalysisPair;
  pendingIds: ProviderPendingPair;
  providers: readonly Provider[];
  setActive: (provider: Provider) => void;
  onRun?: (provider: Provider) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {providers.map((p) => {
        const pending = Boolean(pendingIds[p]);
        return (
          <div key={p} style={{ display: "flex", gap: 2 }}>
            <button
              type="button"
              onClick={() => setActive(p)}
              data-testid={`ai-tab-${p}`}
              style={{
                border: "1px solid var(--border-dim)",
                borderRadius: onRun ? "4px 0 0 4px" : 4,
                background: active === p ? "var(--bg-panel)" : "var(--bg-base)",
                color: "var(--text-primary)",
                cursor: "pointer",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                padding: "5px 10px",
              }}
            >
              {providerLabel(p)}{" "}
              <span aria-hidden="true">{stateBadge(latest[p], pending)}</span>
            </button>
            {onRun && (
              <button
                type="button"
                onClick={() => onRun(p)}
                disabled={pending}
                data-testid={`ai-run-${p}`}
                title={`Run ${providerLabel(p)}`}
                style={{
                  borderTop: "1px solid var(--border-dim)",
                  borderRight: "1px solid var(--border-dim)",
                  borderBottom: "1px solid var(--border-dim)",
                  borderLeft: "none",
                  borderRadius: "0 4px 4px 0",
                  background: pending ? "var(--bg-panel)" : "var(--bg-base)",
                  color: pending
                    ? "var(--text-muted)"
                    : "var(--text-secondary)",
                  cursor: pending ? "not-allowed" : "pointer",
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  padding: "5px 6px",
                  lineHeight: 1,
                }}
              >
                ▶
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
