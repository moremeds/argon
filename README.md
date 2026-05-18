# Unusual Whales Opportunity Scanner

Per-ticker options analytics, watchlist-driven. A worker pulls flow, gamma, IV surface, and OHLC into Postgres; a Next.js UI turns that into two views — a **dashboard** for triage across the watchlist and a **stock page** for the why behind each name.

Data: Unusual Whales (flow, IV, GEX) + massive.com (OHLC). Postgres `option_wizard.uw_scan`.

---

## Dashboard — triage across the watchlist

`http://127.0.0.1:3001/`

![Dashboard](docs/screenshots/dashboard.png)

A grid of ticker cards, one per name on the watchlist. Filter by sector / setup / freshness. Each card is a one-glance read of "is this stock worth opening today?"

### What a card shows

![Single ticker card](docs/screenshots/dashboard-card.png)

| Block | What it tells you |
|---|---|
| **Header** — ticker, last, day % | Spot + intraday move. Color = sign of the day. |
| **Setup badge** (`NEUTRAL` / `MOMENTUM` / `MEAN-REVERT` / …) | Classifier output from the latest scan. |
| **IVR** (top-right) | IV Rank (0–100). High = expensive options today vs the last year. |
| **Sparkline + 1d/1w/30d** | 30-session close path; quick read on trend and drawdown. |
| **Flow aggression dial** | 0–100 score from UW flow alerts — how aggressive today's prints are (size, premium, urgency). |
| **GAMMA block** | GEX flip distance + flip price, GEX per 1% move, max GEX strike, % of total GEX expiring soon. Tells you where dealers will push price. |
| **SKEW (30d) / 25Δ RR** | Risk reversal — sign and magnitude of put-vs-call demand. |
| **POSITIONING** | Raw call/put counts + put/call ratios (OI, volume, 30d Δ). Bar shows balance at a glance. |

Cards refresh on the worker's full-scan cron (`0 5-16 * * 1-5` ET) and on demand via the **rescan** button. Automatic UW scans only query tickers with no persisted card data or card data older than 8 hours; explicit rescans always run.

---

## Stock page — the why behind a single name

`http://127.0.0.1:3001/stock/<TICKER>` — five tabs.

### Market Structure (default)

![Market Structure tab](docs/screenshots/stock-market-structure.png)

The dealer-positioning view. Built from UW spot-exposure and per-strike GEX.

- **Top row tiles** — spot, GEX flip, net GEX (gamma at spot), net DEX (delta at spot), IV 30d, vol P/C
- **Level tiles** — GEX flip support, max magnet, secondary magnet, max acceleration zone, put wall
- **Expected range bar** — today's expected high/low vs flip + close, scaled to IV
- **Directional bias panel** — classifier reasoning (above/below flip, net GEX sign, magnet pull)
- **GEX profile chart** — net gamma by strike, with call/put walls labeled. Where dealers buy or sell to delta-hedge.

### Volatility

![Volatility tab](docs/screenshots/stock-volatility.png)

The IV-surface view. Today's snapshot tiles on top, analytical time series below.

**Today's snapshot:** VRP (IV minus realized — the vol risk premium), ATM IV, RV, IV Rank, IV %ile 30d, implied move 30d, 52w highs/lows for IV and RV, 25Δ skew.

**Analytical series:**
- **IV / IV-of-IV** — level of IV and volatility of IV (regime stability)
- **RV / SPY-corr 1M** — realized vol vs rolling correlation to SPY (idio vs systematic)
- **Regime Quadrant** — 20 sessions plotted by (IV-z, RV-corr) with a corr-cutoff divider; the active dot is today
- **IV-z vs RV-z** — 20-session standardized overlay
- **Smile** — today's IV by strike, one curve per expiration date, spot marker
- **Term Structure** — ATM IV by expiry out to next year-end
- **VRP Spread Panel** — IV (fwd ~30d) vs RV (trailing 21d); the lag is the VRP
- **IV Percentile Distribution** — where today sits in the 1y IV histogram

A backfill kicks automatically the first time you open the tab for a ticker; subsequent loads serve from Postgres.

### Flow, Trade Plan, Tables

- **Flow** — UW flow alerts and dark pool prints for the day, filterable
- **Trade Plan** — defined-risk structure suggestions consistent with the regime + IV surface
- **Tables** — raw rows behind the views (greek exposure, OI per strike, max pain, …) for verification

---

## Other views

| Route | What it is |
|---|---|
| `/scanner` | Detector-driven candidate list (DCF, Dark Pool, EIC, GEX) ranked by bias. Splits into **watchlist candidates** (full detector suite) and **discovered** tickers from the market-wide flow-alerts feed (DCF-only). |
| `/regime` | Market-wide indicators ported from xenon — CRI (Crash Risk), VCG (Vol-Curve Gauge), and SPX GEX with profile chart. Vol-backdrop strip across the top. |
| `/gold` | GOLD COMPASS five-tier cockpit on the gold complex (GLD, IAU, GDX, etc.) — physical/ETF/miner posture from WGC + ETF flow + dealer positioning. Has a `/gold/replay/<YYYY-MM-DD>` history view. |
| `/cockpit/<TICKER>` | Index-only dealer-state research view (SPX / SPY / QQQ / IWM). Tabs: state, dealer, surface, flow-IM, VRP. Optional `?asof=YYYY-MM-DD` for historical snapshots. |
| `/admin` | Health + scheduler controls. |

---

## Run it

```bash
uv sync --extra postgres
cp .env.example .env       # fill UW_SCAN_API_KEY + MASSIVE_API_KEY

bash scripts/migrate.sh    # idempotent SQL migrations against option_wizard.uw_scan
bash scripts/dev.sh        # next (3001) + fastapi (8400) + 2 UW workers + 2 massive workers
```

- Web: <http://127.0.0.1:3001>
- API: <http://127.0.0.1:8400>
- OpenAPI: <http://127.0.0.1:8400/openapi.json>

## Architecture in one breath

```
UW + massive.com  →  sharded workers (APScheduler, src/uw_scan/worker)
                  →  Postgres uw_scan.*
                  →  FastAPI (src/uw_scan/api, port 8400)
                  →  Next.js 16 + React 19 (web/, port 3001)
```

Six dev processes, one database, one schema. UW workers own UW scan/rescan/flow jobs; massive workers own spot/OHLC jobs. Per-ticker loops use stable shard ownership and rescans use DB claiming, so parallel workers do not duplicate provider work. The workers are the only writers; the API is read-only; mutations cross through `/api/jobs` and are drained by the UW workers' 1s rescan loop.

Details by layer live in the `CLAUDE.md` files under `src/uw_scan/`, `web/`, and `tests/`.

## Status

Active rework (2026-05-12 onward) — Streamlit prototype replaced with a card-grid dashboard and a tabbed regime-style detail page. Specs and plans live under [`docs/superpowers/`](docs/superpowers/).
