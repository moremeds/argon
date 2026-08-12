/** The back before its data arrives — or after the fetch failed.
 *
 * These are different states and must read differently. A failed fetch left
 * showing "Loading…" claims progress that will never arrive, and the reader
 * waits instead of reloading. */
export function FundamentalBackPlaceholder({
  failed,
  onClose,
}: {
  failed: boolean;
  onClose: () => void;
}) {
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
      )}
      <button
        type="button"
        onClick={onClose}
        aria-label="Close details"
        style={{
          background: "none",
          border: "1px solid var(--border-dim)",
          borderRadius: 3,
          color: "var(--text-muted)",
          cursor: "pointer",
          fontSize: 10,
          marginLeft: 8,
          padding: "2px 8px",
        }}
      >
        close
      </button>
    </div>
  );
}
