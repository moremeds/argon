// The one HTTP path from the web app to the FastAPI backend (I-100, I-101).
// lib/api.ts, lib/regime/*, and every component call apiFetch; nothing calls
// fetch() against /api directly.

// URL-agnostic base. In the browser, use a relative URL so requests go back
// through whatever origin served the page (Tailnet IP, MagicDNS, Cloudflare
// Tunnel, etc.) and get proxied to FastAPI by the Next.js rewrite at
// `/api/:path*`. On the server (RSC fetches), hit FastAPI directly because
// relative URLs have no base in a Node fetch context.
// Server (RSC): read NEXT_INTERNAL_API_BASE — a *runtime* (non-NEXT_PUBLIC, so
// not build-inlined) env, the SAME var the rewrite proxy uses. Under launchd it
// is unset → localhost fallback; in Docker it is `http://api:8400` (the compose
// service), never `127.0.0.1` = the container itself. See docker-migration spec
// code change #7.
export const API_BASE =
  typeof window !== "undefined"
    ? ""
    : (process.env.NEXT_INTERNAL_API_BASE ?? "http://127.0.0.1:8400");

/** A non-2xx answer from the API (I-102). The message is unchanged from the
 *  old plain Error (`API <status> for <path>: <body>`), so nothing a user sees
 *  changes; callers branch on `status` / `detail` instead of matching text. */
export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly body: string;

  constructor(status: number, path: string, body: string) {
    super(`API ${status} for ${path}: ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
    this.body = body;
  }

  /** The parsed JSON body, or null when the body is not JSON. */
  get json(): unknown {
    try {
      return JSON.parse(this.body);
    } catch {
      return null;
    }
  }

  /** FastAPI's `detail` (a string for HTTPException, a list for 422), if any. */
  get detail(): unknown {
    const j = this.json;
    return j !== null && typeof j === "object"
      ? (j as { detail?: unknown }).detail
      : undefined;
  }
}

/** GET/POST `path` (e.g. `/api/stock/AAPL`) and return the parsed JSON body.
 *  Throws ApiError on a non-2xx answer; `allow404` returns null instead. A 204
 *  or empty body returns undefined. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  options: { allow404?: boolean } = {},
): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (options.allow404 && r.status === 404) return null as T;
  if (!r.ok) {
    throw new ApiError(r.status, path, await r.text());
  }
  // FastAPI returns 204 No Content with an empty body for DELETE; calling
  // r.json() on an empty body throws SyntaxError. Special-case empty.
  if (r.status === 204) return undefined as unknown as T;
  const text = await r.text();
  if (!text) return undefined as unknown as T;
  return JSON.parse(text) as T;
}

/** The API's `detail` string when it sent one, else `HTTP <status>`; a
 *  non-HTTP failure (network, parse) keeps its own message. For panels that
 *  show the backend's explanation (e.g. "run scripts/backtest_vcg.py ..."). */
export function apiErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    return typeof e.detail === "string" ? e.detail : `HTTP ${e.status}`;
  }
  return e instanceof Error ? e.message : String(e);
}
