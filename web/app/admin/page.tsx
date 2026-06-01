import type { components } from "@/lib/types";

type HealthResponse = components["schemas"]["HealthResponse"];

async function fetchHealth(): Promise<HealthResponse> {
  // RSC fetch — needs an absolute URL. Use `||` so an empty
  // NEXT_PUBLIC_API_BASE_URL (set when the bundle should call relative
  // paths in the browser) still resolves server-side.
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8400";
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
