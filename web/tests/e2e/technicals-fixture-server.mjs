import { createServer } from "node:http";
import { SPY_BARS } from "../unit/fixtures/spyBars.ts";

const port = Number(process.env.PORT ?? 18400);

const stock = {
  ticker: "DRYRUN",
  generated_at: "2026-07-10T20:00:00Z",
  spot_quoted_at: "2026-07-10T20:00:00Z",
  market_structure: { spot: 754.95 },
  volatility: { iv: 0.24 },
  setup: null,
};

const technicals = {
  ticker: "DRYRUN",
  backfill_status: "ready",
  as_of: "2026-07-10",
  bars_n: SPY_BARS.length,
  header: {
    price: 754.95,
    sma200: 700,
    dist_pct: 0.0785,
    z: 1.2,
    z_band: "NEUTRAL",
    slope_ann: 0.195,
    slope_regime: "STRONG UPTREND",
    composite: 0.3,
  },
  series: SPY_BARS,
  detail: {},
  forward_returns: [],
  vwap_anchor: null,
};

// Derived from the SAME SPY_BARS above by running the real Python compute
// (all_pivots / magnet_levels / cone / build_read) on 2026-08-09, with the ATM
// IVs read from option_surface_grid_daily for SPY 2026-07-24. Real data through
// real code, frozen — not hand-written numbers. Reproduce:
//   uv run python -c "... magnet_levels(spy_bars_frame(), k=3.0) ..."
const magnets = {
  ticker: "DRYRUN",
  as_of: SPY_BARS.at(-1).as_of,
  levels: {
    resistance: 759.57,
    support: 725.43,
    stretch: 780.66852,
    down: 704.33148,
    sma20: 743.8115,
    last: 754.95,
    leg_state: "rising",
    pivot_a: { index: 43, kind: "top", price: 759.57 },
    pivot_b: { index: 49, kind: "bottom", price: 725.43 },
  },
  bands: [
    // prettier-ignore
    { horizon: 5, band_sigma: 1.0, measured_confidence: 0.709, measured_ci_lo: 0.677, measured_ci_hi: 0.755, measured_n_dates: 149, upper: 772.0204436937619, lower: 737.8795233974398 },
    // prettier-ignore
    { horizon: 5, band_sigma: 1.96, measured_confidence: 0.951, measured_ci_lo: 0.939, measured_ci_hi: 0.963, measured_n_dates: 149, upper: 788.9647597861737, lower: 722.0323467935661 },
    // prettier-ignore
    { horizon: 10, band_sigma: 1.0, measured_confidence: 0.712, measured_ci_lo: 0.666, measured_ci_hi: 0.758, measured_n_dates: 144, upper: 778.0748882417, lower: 731.82500087865 },
    // prettier-ignore
    { horizon: 10, band_sigma: 1.96, measured_confidence: 0.947, measured_ci_lo: 0.924, measured_ci_hi: 0.965, measured_n_dates: 144, upper: 801.3019404356363, lower: 710.6118518339907 },
    // prettier-ignore
    { horizon: 21, band_sigma: 1.0, measured_confidence: 0.677, measured_ci_lo: 0.617, measured_ci_hi: 0.731, measured_n_dates: 133, upper: 788.4411322534144, lower: 721.4583793877041 },
    // prettier-ignore
    { horizon: 21, band_sigma: 1.96, measured_confidence: 0.933, measured_ci_lo: 0.901, measured_ci_hi: 0.964, measured_n_dates: 133, upper: 822.7674626386945, lower: 691.3587220547903 },
  ],
  pivots: [
    { index: 43, kind: "top", price: 759.57 },
    { index: 49, kind: "bottom", price: 725.43 },
  ],
  read: [
    "Leg is rising: support 725.43, resistance 759.57, last 754.95.",
    "0.618 extension sits at 780.67 up / 704.33 down — geometry only, no measured edge.",
    "Price is above SMA20 (743.81).",
    "Options price a 10d range of 710.61-801.30 — that band held 95% of past moves (92%-96%, 144 sessions).",
    "The 0.618 downside extension sits outside that central band — reaching it needs a move in the tail the options surface prices as uncommon, not one it rules out.",
  ],
  candles: SPY_BARS.map((b) => ({
    date: b.as_of,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
    volume: b.volume,
  })),
  atm_iv_30d: 0.1541218069096199,
  atm_iv_30d_chg_5d: null,
};

function json(res, body, status = 200) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  const path = new URL(req.url ?? "/", `http://${req.headers.host}`).pathname;
  if (path === "/health") return json(res, { ok: true });
  if (path === "/api/stock/DRYRUN/technicals") return json(res, technicals);
  if (path === "/api/stock/DRYRUN/magnets") return json(res, magnets);
  if (path === "/api/stock/DRYRUN/technicals/live") {
    return json(res, { ticker: "DRYRUN", available: false });
  }
  if (path === "/api/stock/DRYRUN") return json(res, stock);
  if (path === "/api/watchlist/spots") return json(res, { spots: [] });
  if (path === "/api/watchlist") return json(res, { tickers: [] });
  // Next prefetches sibling stock tabs. They are outside this focused fixture;
  // return a neutral object so speculative requests stay quiet.
  return json(res, {});
}).listen(port, "127.0.0.1");
