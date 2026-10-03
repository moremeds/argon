// Allowlist of GET endpoints derived from the internal API's OpenAPI doc.
// Paths are stored WITHOUT the /api prefix — the same universe apiGet and the
// tools speak: read("/stock/AAPL/technicals") → apiGet → /api/stock/…/technicals.
import { fetchOpenApiDoc, resolveApiBase } from "./openapi";

export type EndpointParam = {
  name: string;
  in: "path" | "query";
  required: boolean;
};

export type EndpointInfo = {
  /** OpenAPI path template minus the /api prefix, e.g. /stock/{ticker}/technicals. */
  path: string;
  summary: string;
  params: EndpointParam[];
};

/** Operator denylist: exact (post-/api-strip) path templates to exclude.
 *  - /stock/{ticker}/trade-insights: its GET handler BUILDS and persists a
 *    snapshot (repo.conn.commit(), routers/trade_insights.py) — a GET that
 *    writes, so it cannot stay on a read-only allowlist. Agents use the
 *    read-only twin /stock/{ticker}/trade-insights/preview instead.
 *  - /stock/{ticker}/volatility/series: a GET that enqueues a volatility
 *    backfill row (routers/volatility.py) → the uw-0 worker spends UW on it.
 *  Guard test: tests/unit/api/test_mcp_get_side_effects.py fails if a new
 *  side-effecting GET is added without being denylisted here. */
export const DENYLIST: ReadonlySet<string> = new Set<string>([
  "/stock/{ticker}/trade-insights",
  "/stock/{ticker}/volatility/series",
]);

type OpenApiOperation = {
  summary?: string;
  parameters?: Array<{ name?: string; in?: string; required?: boolean }>;
};

/** Extract allowlisted GET operations from a parsed OpenAPI document. */
export function parseOpenApiEndpoints(doc: unknown): EndpointInfo[] {
  const paths = (doc as { paths?: Record<string, { get?: OpenApiOperation }> })
    ?.paths;
  if (!paths || typeof paths !== "object") {
    throw new Error("openapi.json: no paths object");
  }
  const out: EndpointInfo[] = [];
  for (const [rawPath, item] of Object.entries(paths)) {
    if (!item?.get) continue; // allowlist is GET-only — non-GET ops never enter
    const path = rawPath.startsWith("/api/")
      ? rawPath.slice(4)
      : rawPath === "/api"
        ? "/"
        : rawPath;
    if (DENYLIST.has(path)) continue;
    const params = (item.get.parameters ?? [])
      .filter(
        (p): p is { name: string; in: string; required?: boolean } =>
          typeof p?.name === "string" && (p.in === "path" || p.in === "query"),
      )
      .map((p) => ({
        name: p.name,
        in: p.in as "path" | "query",
        required: p.required ?? false,
      }));
    out.push({ path, summary: item.get.summary ?? "", params });
  }
  out.sort((a, b) => a.path.localeCompare(b.path));
  return out;
}

/** Segment-wise match of a concrete path against a {param} template. */
export function matchEndpoint(
  endpoints: EndpointInfo[],
  concretePath: string,
): EndpointInfo | null {
  const segs = concretePath.split("/");
  for (const ep of endpoints) {
    const t = ep.path.split("/");
    if (t.length !== segs.length) continue;
    const ok = t.every(
      (ts, i) =>
        ts === segs[i] ||
        (ts.startsWith("{") && ts.endsWith("}") && segs[i].length > 0),
    );
    if (ok) return ep;
  }
  return null;
}

export class EndpointsCache {
  constructor(
    private readonly fetchDoc: () => Promise<unknown>,
    private readonly now: () => number = Date.now,
    private readonly ttlMs: number = 3_600_000,
  ) {}

  private cache: { at: number; eps: EndpointInfo[] } | null = null;
  private inflight: Promise<EndpointInfo[]> | null = null;

  /** First call fetches; thereafter the doc is re-fetched once per ttlMs.
   *  A failed refresh keeps serving the stale copy. */
  async get(): Promise<EndpointInfo[]> {
    if (this.cache && this.now() - this.cache.at <= this.ttlMs) {
      return this.cache.eps;
    }
    this.inflight ??= this.fetchDoc()
      .then((doc) => {
        const eps = parseOpenApiEndpoints(doc);
        this.cache = { at: this.now(), eps };
        return eps;
      })
      .catch((err) => {
        if (this.cache) {
          console.error("openapi refresh failed, serving stale", err);
          return this.cache.eps;
        }
        throw err;
      })
      .finally(() => {
        this.inflight = null;
      });
    return this.inflight;
  }
}

/** Shared singleton used by the read/list_endpoints tools. */
export const endpointsCache = new EndpointsCache(() =>
  fetchOpenApiDoc(resolveApiBase()),
);
