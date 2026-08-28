import { toNum } from "@/lib/formatters";

/**
 * A confidence as a whole percent, or an em dash.
 *
 * `MacroDomainStateResponse.confidence` is a Pydantic `Decimal`, which serialises as a
 * STRING on the wire (the frozen fixture carries `"0.71"`), so every reader has to accept
 * both. Shared rather than copied because tab 00 prints the same number in three places
 * -- the daily loop, the transmission-health row and the card -- and three roundings that
 * disagree by a point is a bug nobody would look for.
 *
 * Deliberately NOT a colour or a band. A percentage rendered green above some threshold
 * would be a judgement the engine did not make; the desk prints the number and the terms
 * behind it (`ConfidenceArithmetic`) and lets the reader argue with them.
 */
export function confidencePct(raw: string | number | null | undefined): string {
  const n = toNum(raw);
  if (n === null) return "—";
  return `${Math.round(n * 100)}%`;
}

/** `2026-08-24T07:40:00Z` -> `2026-08-24 07:40 UTC`. Always UTC: every instant on this
 *  desk is compared against a UTC day boundary, so rendering one in a local zone would
 *  put the reader's arithmetic in a different frame from the desk's. */
export function instantUtc(value: string | null | undefined): string {
  if (!value) return "—";
  const normalized = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
  const ms = Date.parse(normalized);
  if (Number.isNaN(ms)) return value;
  return `${new Date(ms).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}
