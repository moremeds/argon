import Link from "next/link";

export function StockNotReadyDialog({
  ticker,
  onClose,
}: {
  ticker: string;
  onClose?: () => void;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 80,
        display: "grid",
        placeItems: "center",
        padding: 16,
        pointerEvents: "none",
      }}
    >
      <div
        role="alertdialog"
        aria-labelledby="stock-not-ready-title"
        style={{
          width: "min(380px, calc(100vw - 32px))",
          padding: 18,
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          boxShadow: "0 24px 64px rgba(0, 0, 0, 0.44)",
          color: "var(--text-primary)",
          fontFamily: "var(--font-mono)",
          pointerEvents: "auto",
        }}
      >
        <div
          id="stock-not-ready-title"
          style={{
            fontSize: 15,
            fontWeight: 800,
            letterSpacing: 0.8,
            textTransform: "uppercase",
            marginBottom: 8,
          }}
        >
          {ticker.toUpperCase()} is not ready
        </div>
        <div
          style={{
            color: "var(--text-secondary)",
            fontSize: 12,
            lineHeight: 1.45,
            marginBottom: 14,
          }}
        >
          Run a scan first, then open this ticker again.
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            style={{
              minHeight: 34,
              padding: "0 12px",
              background: "var(--accent-bg)",
              color: "var(--accent-text)",
              border: 0,
              borderRadius: 4,
              fontFamily: "var(--font-mono)",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            Close
          </button>
        ) : (
          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              minHeight: 34,
              padding: "0 12px",
              background: "var(--accent-bg)",
              color: "var(--accent-text)",
              borderRadius: 4,
              textDecoration: "none",
              fontSize: 13,
            }}
          >
            Back to dashboard
          </Link>
        )}
      </div>
    </div>
  );
}
