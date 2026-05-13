"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--negative)",
        padding: 16,
      }}
    >
      <div>Tab failed to load: {error.message}</div>
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
