export const dynamic = "force-dynamic";

export default function ScannerPage() {
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
      <div
        style={{
          padding: 24,
          border: "1px dashed var(--border-dim)",
          borderRadius: 4,
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          textAlign: "center",
        }}
      >
        scanner — coming soon
      </div>
    </div>
  );
}
