import type { components } from "@/lib/types";

type HealthResponse = components["schemas"]["HealthResponse"];

async function fetchHealth(): Promise<HealthResponse> {
  // RSC fetch — needs an absolute URL. Read the runtime NEXT_INTERNAL_API_BASE
  // (non-public, not build-inlined; `http://api:8400` in Docker, unset →
  // localhost under launchd). See docker spec code change #7.
  const base = process.env.NEXT_INTERNAL_API_BASE ?? "http://127.0.0.1:8400";
  const r = await fetch(`${base}/api/health`, { cache: "no-store" });
  return r.json();
}

export default async function AdminPage() {
  const health = await fetchHealth();
  return (
    <main
      style={{
        padding: 24,
        fontFamily: "var(--font-mono)",
        color: "var(--text-primary)",
      }}
    >
      <h1>Admin</h1>
      <pre
        style={{
          background: "var(--bg-panel)",
          padding: 12,
          fontSize: 12,
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
        }}
      >
        {JSON.stringify(health, null, 2)}
      </pre>
    </main>
  );
}
