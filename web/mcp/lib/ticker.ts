// Ticker normalization for every value that lands in an apiGet path. An
// unvalidated segment is a path-traversal primitive — the probe
// "../%68%65%61%6c%74%68#" interpolated into /stock/<t>/technicals resolved
// to /api/health on the FastAPI side. Every tool validates before a URL is
// built; path interpolation also wraps the normalized value in
// encodeURIComponent as defence in depth.
//
// The charset is what argon actually carries: equities (AAPL), class shares
// in both spellings (BRK.B, BRK-B) and "^" index symbols (^VIX), 1–10 chars.

// zod-schema form is case-insensitive so lower-case args pass validation and
// reach the handler, where normalizeTicker upper-cases them.
export const TICKER_RE = /^[A-Z0-9.^-]{1,10}$/i;

/** Trim + upper-case, then require the ticker charset. Throws on anything else. */
export function normalizeTicker(raw: string): string {
  const t = raw.trim().toUpperCase();
  // A pure-dots value ("..") satisfies the charset but is a path segment, not
  // a ticker — reject it explicitly.
  if (!TICKER_RE.test(t) || /^\.+$/.test(t)) {
    throw new Error(`invalid ticker: ${JSON.stringify(raw)}`);
  }
  return t;
}
