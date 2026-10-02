// GET-only fetch of the internal API's OpenAPI document.
// FastAPI serves /openapi.json at the APP ROOT (FastAPI() default
// openapi_url), not under the /api router prefix — so ToolCtx.apiGet, which
// prepends "/api", cannot reach it. This is the only other fetch in web/mcp;
// it is GET-only like apiGet.

export function resolveApiBase(): string {
  return process.env.ARGON_API_URL ?? "http://api:8400";
}

export async function fetchOpenApiDoc(base: string): Promise<unknown> {
  const res = await fetch(`${base}/openapi.json`, { method: "GET" });
  if (!res.ok) throw new Error(`openapi.json fetch failed: ${res.status}`);
  return res.json();
}
