"use client";

/**
 * The desk-level boundary.
 *
 * This exists for one throw the per-tab boundary cannot see: `app/macro/layout.tsx`.
 * A segment's own `error.tsx` does not catch throws from that segment's layout, so a
 * tab bar that fails would otherwise take the whole route tree with it and surface as
 * the app-level error page with nothing saying which desk broke.
 *
 * It is a backstop, not the primary mechanism. Individual publishers are settled per
 * card (`app/macro/page.tsx:10-19`) so one dead publisher costs its own card; this
 * catches what those wrappers do not.
 */
export default function MacroDeskError({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <main
      data-testid="macro-desk-error"
      style={{
        minHeight: "100vh",
        padding: 32,
        background: "var(--bg-base)",
        color: "var(--text-primary)",
        fontFamily: "var(--font-sans)",
      }}
    >
      <h1
        style={{
          margin: 0,
          fontFamily: "var(--font-mono)",
          fontSize: 24,
          letterSpacing: 1,
        }}
      >
        MACRO DESK SHELL UNAVAILABLE
      </h1>
      <p style={{ maxWidth: 760, color: "var(--text-secondary)" }}>
        The desk shell itself failed, so no tab could be rendered. This is the
        shell, not a publisher: a single macro domain failing to answer is
        reported on its own card instead.
      </p>
      <pre
        style={{
          maxWidth: 960,
          overflowX: "auto",
          padding: 16,
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          color: "var(--negative)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {error.message}
      </pre>
      <button
        type="button"
        onClick={reset}
        style={{
          padding: "6px 12px",
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          color: "var(--text-primary)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          cursor: "pointer",
        }}
      >
        Retry
      </button>
    </main>
  );
}
