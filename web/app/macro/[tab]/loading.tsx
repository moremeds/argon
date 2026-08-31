/**
 * Per-tab loading boundary. Scoped to the tab, not the desk: the shell and its tab bar
 * are already painted by `app/macro/layout.tsx`, so this replaces only the panel area
 * and the operator keeps the navigation while a tab's publishers answer.
 *
 * Carried from `app/rates/loading.tsx` / `app/gold/loading.tsx`, which the port must not
 * silently delete when those pages re-home.
 */
export default function Loading() {
  return (
    <div
      data-testid="macro-tab-loading"
      style={{
        padding: 24,
        color: "var(--text-muted)",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        letterSpacing: 1,
        textTransform: "uppercase",
      }}
    >
      Loading macro desk tab…
    </div>
  );
}
