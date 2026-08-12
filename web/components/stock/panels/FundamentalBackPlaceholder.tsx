/** The back before its data arrives — or after the fetch failed.
 *
 * These are different states and must read differently. A failed fetch left
 * showing "Loading…" claims progress that will never arrive, and the reader
 * waits instead of reloading. */
export function FundamentalBackPlaceholder({ failed }: { failed: boolean }) {
  return (
    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
      {failed ? (
        <>
          <strong style={{ color: "var(--warning)" }}>
            Components unavailable.
          </strong>{" "}
          The statement history did not load. The ratio on the front of the card
          is unaffected.
        </>
      ) : (
        "Loading components…"
      )}{" "}
      <span style={{ opacity: 0.7 }}>click to flip back</span>
    </div>
  );
}
