"use client";

export default function Error({ error }: { error: Error }) {
  return (
    <main
      style={{
        minHeight: "100vh",
        padding: 32,
        background: "#f4f3fd",
        color: "#3b3852",
        fontFamily: "var(--font-sans)",
      }}
    >
      <h1 style={{ margin: 0, fontSize: 24 }}>Rates desk unavailable</h1>
      <p style={{ maxWidth: 760 }}>
        The rates API returned an error instead of a persisted snapshot.
      </p>
      <pre
        style={{
          maxWidth: 960,
          overflowX: "auto",
          padding: 16,
          background: "#ffffff",
          border: "1px solid #dedbec",
          borderRadius: 8,
          color: "#8f2e3c",
        }}
      >
        {error.message}
      </pre>
    </main>
  );
}
