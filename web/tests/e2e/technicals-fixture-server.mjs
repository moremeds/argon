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

function json(res, body, status = 200) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

createServer((req, res) => {
  const path = new URL(req.url ?? "/", `http://${req.headers.host}`).pathname;
  if (path === "/health") return json(res, { ok: true });
  if (path === "/api/stock/DRYRUN/technicals") return json(res, technicals);
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
