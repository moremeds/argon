export default function ScannerLoading() {
  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <h1
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 24,
          letterSpacing: 1,
          marginBottom: 16,
        }}
      >
        SCANNER
      </h1>
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: 96,
            marginBottom: 8,
            backgroundColor: "var(--bg-panel)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            opacity: 0.5,
          }}
        />
      ))}
    </div>
  );
}
