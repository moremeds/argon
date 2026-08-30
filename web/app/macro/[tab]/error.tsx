"use client";

/**
 * Per-tab error boundary. A route `error.tsx` replaces the whole tab, so this is the
 * backstop for a throw the per-publisher `settle()` wrappers did not catch — one dead
 * publisher is still meant to cost one card, not the tab.
 *
 * It sits below the layout's tab bar, so a failed tab never costs the navigation: the
 * other tabs stay one click away.
 */
export default function MacroTabError({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <div
      data-testid="macro-tab-error"
      style={{
        padding: 24,
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--negative)",
      }}
    >
      <div>This macro tab failed to render: {error.message}</div>
      <button
        type="button"
        onClick={reset}
        style={{
          marginTop: 8,
          padding: "4px 8px",
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          color: "var(--text-primary)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          cursor: "pointer",
        }}
      >
        Retry
      </button>
    </div>
  );
}
