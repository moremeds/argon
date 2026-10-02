// GEX derivations, verbatim from components/regime/GexSubTab.tsx: the SPOT
// re-tag on a live spot, the live-spot selection (fresh AND not behind the
// scan's tape_time), and the live day-change overrides.
//
// The only adaptation: `quoteIsFresh` in ../useRegimeQuotes reads Date.now()
// internally, so the same body is kept here as `quoteIsFreshAt` with `now`
// injected — callers pass Date.now() (or a fixture-derived value in tests).
import type { GexBucket, GexData, GexLevel } from "../useGex";
import type { RegimeQuotesResponse } from "../useRegimeQuotes";

export type RegimeLiveQuote =
  NonNullable<RegimeQuotesResponse["quotes"]>[string];

// Same fallback as useRegimeQuotes' module-private constant — the backend
// default for REGIME_LIVE_QUOTE_MAX_AGE_SECONDS.
const DEFAULT_FRESH_SECONDS = 900;

/** quoteIsFresh body verbatim, with the clock injected. */
export function quoteIsFreshAt(
  quotedAt: string | null | undefined,
  freshWithinSeconds: number = DEFAULT_FRESH_SECONDS,
  now: number = Date.now(),
): boolean {
  if (!quotedAt) return false;
  return now - new Date(quotedAt).getTime() < freshWithinSeconds * 1000;
}

/**
 * Recompute each bucket's distance from a live spot and re-place the SPOT
 * tag on the nearest strike, mirroring the backend's tag_profile precedence
 * (SPOT first, GEX FLIP overrides, levels fill the remaining strikes) so a
 * spot move can't strand a stale SPOT row.
 *
 * Moved verbatim from GexSubTab.tsx — that file re-exports it so existing
 * imports keep working.
 */
export function retagProfileForSpot(
  profile: GexBucket[],
  liveSpot: number,
  levels:
    | {
        gex_flip?: GexLevel;
        max_magnet?: GexLevel;
        second_magnet?: GexLevel;
        max_accelerator?: GexLevel;
        put_wall?: GexLevel;
        call_wall?: GexLevel;
      }
    | null
    | undefined,
): GexBucket[] {
  if (!profile.length) return profile;
  let nearest: number | null = null;
  let minDist = Infinity;
  for (const b of profile) {
    const d = Math.abs(b.strike - liveSpot);
    if (d < minDist) {
      minDist = d;
      nearest = b.strike;
    }
  }
  const tagMap = new Map<number, string>();
  if (nearest != null) tagMap.set(nearest, "SPOT");
  if (levels?.gex_flip) tagMap.set(levels.gex_flip.strike, "GEX FLIP");
  const labelled: [GexLevel, string][] = [
    [levels?.max_magnet ?? null, "MAX MAGNET"],
    [levels?.second_magnet ?? null, "SECOND MAGNET"],
    [levels?.max_accelerator ?? null, "MAX ACCELERATOR"],
    [levels?.put_wall ?? null, "PUT WALL"],
    [levels?.call_wall ?? null, "CALL WALL"],
  ];
  for (const [level, label] of labelled) {
    if (level && !tagMap.has(level.strike)) tagMap.set(level.strike, label);
  }
  return profile.map((b) => ({
    ...b,
    pct_from_spot: ((b.strike - liveSpot) / liveSpot) * 100,
    tag: tagMap.get(b.strike) ?? null,
  }));
}

/**
 * The component's live-spot splice + tape-time reads, verbatim (clock
 * injected). Takes the two GexData fields it reads as primitives so the call
 * site does not hand the (memoized) `data` object to a cross-file function —
 * the React compiler treats that as a possible post-render mutation.
 */
export function liveSpotSelection(
  ticker: string | null | undefined,
  tapeTime: string | null | undefined,
  quotes: RegimeQuotesResponse | null | undefined,
  now: number = Date.now(),
): {
  liveSpot: number | null;
  spotTapeTime: string | null | undefined;
} {
  // Live SPX splice: when the WS quote is fresh, the SPOT card and the
  // profile chart tick with it; everything else stays on the scan snapshot.
  // The quote must also not predate the snapshot's own tick (tape_time) —
  // a stalled WS feed inside the freshness window must not move spot
  // backwards past a newer scan.
  const spxQuote = ticker === "SPX" ? quotes?.quotes?.SPX : undefined;
  const quoteAtMs = spxQuote?.quoted_at ? Date.parse(spxQuote.quoted_at) : NaN;
  const tapeMs = tapeTime ? Date.parse(tapeTime) : NaN;
  const quoteNotBehindTape =
    !Number.isFinite(quoteAtMs) || !Number.isFinite(tapeMs)
      ? true
      : quoteAtMs >= tapeMs;
  const liveSpot =
    spxQuote &&
    quoteNotBehindTape &&
    quoteIsFreshAt(spxQuote.quoted_at, quotes?.fresh_within_seconds, now)
      ? spxQuote.price
      : null;
  const spotTapeTime = liveSpot != null ? spxQuote?.quoted_at : tapeTime;
  return { liveSpot, spotTapeTime };
}

/**
 * The post-guard display-spot/day-change reads, verbatim — a live spot
 * re-bases the display spot and the day-change math on prev_close (prev_close
 * ≤ 0 counts as missing).
 */
export function gexSpotRead(
  data: Pick<
    GexData,
    "spot" | "prev_close" | "day_change" | "day_change_pct"
  >,
  liveSpot: number | null,
): {
  displaySpot: number;
  prevClose: number | null;
  dayChange: number | null;
  dayChangePct: number | null;
} {
  const displaySpot = liveSpot ?? data.spot;
  // prev_close of 0 means "missing", not a real reference price.
  const prevClose =
    data.prev_close != null && data.prev_close > 0 ? data.prev_close : null;
  const dayChange =
    liveSpot != null && prevClose != null
      ? liveSpot - prevClose
      : data.day_change;
  const dayChangePct =
    liveSpot != null && prevClose != null
      ? ((liveSpot - prevClose) / prevClose) * 100
      : data.day_change_pct;
  return { displaySpot, prevClose, dayChange, dayChangePct };
}
