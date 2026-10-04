import { apiFetch } from "@/lib/apiClient";
import type { components } from "@/lib/types";

type HealthResponse = components["schemas"]["HealthResponse"];

async function fetchHealth(): Promise<HealthResponse> {
  // RSC fetch: apiFetch resolves the server-side base (NEXT_INTERNAL_API_BASE).
  return apiFetch<HealthResponse>("/api/health");
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
