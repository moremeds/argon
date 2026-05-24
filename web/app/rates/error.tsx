"use client";

export default function Error({ error }: { error: Error }) {
  return (
    <main
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
        RATES DESK UNAVAILABLE
      </h1>
      <p style={{ maxWidth: 760, color: "var(--text-secondary)" }}>
        The rates API returned an error instead of a persisted snapshot.
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
    </main>
  );
}
