// Pure series plumbing for the Technicals surface: the timeframe window and
// the live-head merge that turn `/stock/{t}/technicals{,/live}` payloads into
// the rows the chart draws. Shared by the React tab and the Node MCP tools —
// no React/DOM/chart imports in here (types are import-type only).
import type {
  TechnicalsLiveResponse,
  TechnicalsResponse,
} from "@/lib/api";

export type Timeframe = "full" | "1y" | "ytd" | "3m";

// Window the daily series to a timeframe. Anchored on the LAST bar's date (not
// wall-clock now) so a stale/weekend payload never yields an empty window. ISO
// date strings compare lexically === chronologically, so the cutoff is a plain
// string >= test — no Date parsing, no timezone. 'full' returns the input as-is.
// ponytail: 3m month-end anchors (e.g. -3mo of the 31st) land on a non-existent
// day and drop a day or two at the boundary — invisible on a chart, not worth
// clamping.
export function sliceSeriesByTimeframe<T extends { as_of?: string | null }>(
  series: T[],
  timeframe: Timeframe,
): T[] {
  if (timeframe === "full" || series.length === 0) return series;
  // Anchor on the last row that actually has a date — not blindly the last row,
  // which could be a spliced head with a null as_of (would else fall back to the
  // unsliced full series and silently ignore the selector).
  let last: string | null | undefined;
  for (let i = series.length - 1; i >= 0; i--) {
    if (series[i]?.as_of) {
      last = series[i]!.as_of;
      break;
    }
  }
  if (!last) return series;
  let cutoff: string;
  if (timeframe === "ytd") {
    cutoff = `${last.slice(0, 4)}-01-01`;
  } else if (timeframe === "1y") {
    // Same day, previous year — MM-DD carried verbatim (no month arithmetic).
    cutoff = `${Number(last.slice(0, 4)) - 1}${last.slice(4)}`;
  } else {
    const [y, m] = last.split("-").map(Number);
    const months = y * 12 + (m - 1) - 3; // 3 calendar months back, in month-space
    const cy = Math.floor(months / 12);
    const cm = (months % 12) + 1;
    cutoff = `${cy}-${String(cm).padStart(2, "0")}-${last.slice(8, 10)}`;
  }
  return series.filter((r) => (r.as_of ?? "") >= cutoff);
}

// Client-side freshness gate — mirrors the server's default
// TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS (900). Beyond this the live head is
// dropped and the EOD daily payload stands.
export const LIVE_MAX_AGE_SEC = 900;

export function isFresh(
  live: TechnicalsLiveResponse | null,
  now: number = Date.now(),
): boolean {
  if (!live?.available || !live.captured_at) return false;
  const age = (now - new Date(live.captured_at).getTime()) / 1000;
  // age >= 0 rejects a future-dated capture (server/client clock skew or a bad
  // row): a negative age would otherwise pass the upper bound and pin a stale
  // live head for as long as it stays in the future.
  return Number.isFinite(age) && age >= 0 && age <= LIVE_MAX_AGE_SEC;
}

// The live capture's US trading-session date, in ET — NOT the UTC date. A
// capture at e.g. 21:00 ET Friday is already Saturday in UTC, so slicing the
// UTC ISO string (`.slice(0,10)`) would date today's live bar to a non-trading
// Saturday. The ET calendar date keeps it on the real session (Friday) until
// ET midnight. `en-CA` renders YYYY-MM-DD, matching the series' as_of format.
export function etSessionDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-CA", {
    timeZone: "America/New_York",
  });
}

// Splice the live reading onto the daily payload: append one series row (which
// moves the last point of EVERY oscillator chart — z, RSI, dual MACD, RV,
// kinematics — at once) and override the latest detail readouts that drive the
// per-panel headlines. Sigmoid / forward-returns are intentionally untouched
// (static intraday). Returns the original data unchanged when live is stale.
export function mergeLiveHead(
  data: TechnicalsResponse,
  live: TechnicalsLiveResponse | null,
  now: number = Date.now(),
): TechnicalsResponse {
  if (!isFresh(live, now) || !live) return data;
  const kin = (live.kinematics ?? {}) as Record<
    string,
    { slope_atr?: number | null }
  >;
  const dm = (live.dual_macd ?? {}) as Record<string, number | null>;
  // isFresh() guarantees captured_at is present.
  // ET trading-session date, NOT the raw ISO slice: on a machine set to a
  // non-ET zone (e.g. HK), captured_at is +08:00, so slicing would date the
  // live bar to the wrong calendar day (Saturday for a Friday session). isFresh
  // guarantees captured_at is present.
  const asOf = etSessionDate(live.captured_at!);
  // When the live job has accumulated today's session OHLC, draw a REAL forming
  // candle (open/high/low/close) instead of a close-only doji that hides on the
  // price line. Guard on the forming candle's own session_date matching today's
  // ET session so a stale row (weekend / after-hours) can't paint yesterday's
  // range onto today; fall back to the close-only spot when it's absent.
  const fo =
    live.forming_ohlc && live.forming_ohlc.session_date === asOf
      ? live.forming_ohlc
      : null;
  const liveRow = {
    as_of: asOf,
    open: fo?.open ?? null,
    high: fo?.high ?? null,
    low: fo?.low ?? null,
    close: fo?.close ?? live.spot ?? null,
    z: live.z ?? null,
    z_band: live.z_band ?? null,
    rsi14: live.rsi14 ?? null,
    rsi_z: live.rsi_z ?? null,
    rv20: live.rv20 ?? null,
    kin_slope20: kin.sma20?.slope_atr ?? null,
    kin_slope50: kin.sma50?.slope_atr ?? null,
    kin_slope200: kin.sma200?.slope_atr ?? null,
    fast_macd_hist_atr: dm.fast_hist ?? null,
    slow_macd_hist_atr: dm.slow_hist ?? null,
  };
  const series = [...(data.series ?? [])];
  // The live reading is TODAY's provisional bar. A SETTLED bar (one carrying
  // real OHLC, open != null) is final — its close/high/low must never be moved
  // by a live tick, even when the capture's UTC date coincides with it (an
  // after-hours capture, or the ET-evening → next-UTC-day date rollover). So:
  // refresh a prior *provisional* head (close-only, open == null) in place;
  // else append a strictly-newer provisional bar; else leave the settled series
  // untouched (the price tile still reflects live via the header path below).
  // This is the "keep the 7/9 EOD bar intact" fix — apex lags a day, so the
  // last EOD bar is a closed prior session, not today's forming candle.
  const last = series[series.length - 1];
  if (last && last.as_of === asOf && last.open == null) {
    series[series.length - 1] = { ...last, ...liveRow };
  } else if (!last?.as_of || asOf > last.as_of) {
    series.push(liveRow as (typeof series)[number]);
  }
  const detail = { ...(data.detail ?? {}) };
  detail.dual_macd = live.dual_macd ?? detail.dual_macd;
  detail.rsi = { ...(detail.rsi ?? {}), rsi14: live.rsi14 };
  detail.distribution = { ...(detail.distribution ?? {}), rv20: live.rv20 };
  // Consume the live spot in the price-card header too: price, z-band, and the
  // 200DMA distance (recomputed off the live spot). Slope / MACD-pctile are
  // EOD-static and left alone.
  const header = { ...(data.header ?? {}) };
  if (live.spot != null) {
    header.price = live.spot;
    if (header.sma200) header.dist_pct = live.spot / header.sma200 - 1;
  }
  if (live.z != null) header.z = live.z;
  if (live.z_band != null) header.z_band = live.z_band;
  if (live.composite != null) header.composite = live.composite;
  // Advance the payload date to the live ET session when the head is newer, so
  // the Price tile reads today's session date (7/10) instead of the stale EOD
  // as_of (7/09) it would otherwise show beside a live price. Only ever forward
  // (lexical ISO compare) — never rewind past a settled EOD date.
  const nextAsOf = !data.as_of || asOf > data.as_of ? asOf : data.as_of;
  return { ...data, as_of: nextAsOf, series, detail, header };
}
