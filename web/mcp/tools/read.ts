import { z } from "zod";

import { endpointsCache, matchEndpoint } from "../lib/endpoints";
import type { McpTool } from "../types";

function badPath(path: string): boolean {
  // '%' must be rejected outright: WHATWG URL normalization decodes
  // percent-encoded dot segments (%2e%2e → ..) inside fetch, which would
  // bypass the literal checks below. Encoded values arrive via `params`
  // (encodeURIComponent'd) instead.
  return (
    path.includes("%") ||
    path.includes("//") ||
    path.split("/").some((s) => s === "." || s === "..")
  );
}

type ReadArgs = {
  path: string;
  params?: Record<string, string | number | boolean>;
};

export const tool: McpTool = {
  name: "read",
  description:
    "Read an allowlisted GET endpoint of the Argon API. `path` is one of the " +
    "templates from list_endpoints (e.g. /stock/{ticker}/technicals); supply " +
    "{placeholder} values and query params via `params`.",
  inputSchema: {
    path: z
      .string()
      .describe("Endpoint path or template, e.g. /stock/AAPL/technicals"),
    params: z
      .record(z.string(), z.union([z.string(), z.number(), z.boolean()]))
      .optional()
      .describe("Path-template values and query params (GET only)."),
  },
  handler: async (args, ctx) => {
    const { path, params } = args as ReadArgs;
    if (badPath(path)) {
      throw new Error(
        `read: invalid path '${path}' ('%', '.', '..' or '//' not allowed)`,
      );
    }
    // Convenience: /api-prefixed paths are the same endpoints (apiGet re-adds it).
    let resolved =
      path.startsWith("/api/") && path.length > 5 ? path.slice(4) : path;

    // Fill {placeholder} segments from params; leftovers stay query params.
    const query: Record<string, string | number | boolean> = { ...params };
    resolved = resolved.replace(/\{(\w+)\}/g, (_m, name: string) => {
      const v = query[name];
      if (v === undefined) {
        throw new Error(`read: missing value for path param '${name}'`);
      }
      const s = String(v);
      if (s === "." || s === "..") {
        throw new Error(`read: invalid value for path param '${name}'`);
      }
      delete query[name];
      return encodeURIComponent(s);
    });
    if (badPath(resolved) || resolved.includes("{") || resolved.includes("}")) {
      throw new Error(`read: invalid path '${resolved}'`);
    }

    const endpoints = await endpointsCache.get();
    if (!matchEndpoint(endpoints, resolved)) {
      throw new Error(
        `read: '${resolved}' is not an allowlisted GET endpoint. ` +
          "Call list_endpoints() for the allowed paths.",
      );
    }
    return ctx.apiGet(resolved, query);
  },
};
