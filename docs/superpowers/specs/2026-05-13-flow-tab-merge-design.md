# Flow Tab — Design Spec

**Date:** 2026-05-13
**Author:** chenxi
**Status:** Draft

## Goal

Merge the current `Flow` and `Tables` tabs on the per-stock detail page into a single tab named **Flow**, and upgrade the content with:

1. A snapshot grid that explains its own numbers (info-icon tooltips with definitions + benchmarks).
2. Two daily timeline charts (options volume + put/call ratio, OI + put/call OI ratio) over a 180-day window.
3. Two strike-profile charts (volume by strike, OI by strike) with a shared multi-expiry picker and ITM/OTM bucket tables.
4. Two upgraded drill-down tables (Top Alerts with a rule glossary, OI Movers with decoded symbol + signal columns).

Today the two tabs are mostly raw numbers without context. The merged tab tells one story: at-a-glance snapshot → historical context → where positioning sits → drill-down rows.

## Research findings that anchor the design

A short research brief informs several columns and chart choices. Treat these as the design's "why."

- **Vol/OI ≥ 1.25** is the canonical industry threshold for "unusual" activity; `Vol > OI` is needed to know the trade is *opening* (new positioning), not closing. Source: Barchart UOA, Market Rebellion / Najarian.
- **Vol/|ΔOI| ratio** distinguishes informative flow from noise: ≈1 means clean opening, >>1 means intraday round-trip (day-trader / market-maker churn). Source: Sophie AI vol/OI guide; general practitioner heuristic.
- **Aggressor side (ask% vs bid%)** is the single biggest separator between informative ΔOI and noise. Call bought at ask + ΔOI>0 = bullish new positioning; call sold at bid + ΔOI>0 = overwriter/yield-seller (very different signal). Source: Pan & Poteshman 2006 (RFS), Cremers & Weinbaum 2010 (JFQA), UW / OptionStrat practitioner pages.
- **Short-DTE OTM** carries the most informed-trading premium (Pan & Poteshman channel; Brenner et al. on M&A). DTE + moneyness columns matter.
- **Delta-weighted notional** filters out penny-OTM lottery prints from real-money positioning. Industry standard for flow ranking.
- **Calls-above / puts-below profile** matches the practitioner mental model and supports pin-risk reading (SpotGamma Call Wall / Put Wall framing).

## Out of scope (v1)

- Aggregating Ask% across watchlist (cross-ticker view) — local-to-stock-page only.
- Real-time intraday timeline updates (this is a daily snapshot tool, not a tape reader).
- Dealer GEX overlay on the OI profile — that lives on the Market Structure tab and we don't duplicate it here.
- Earnings-day "spike detection" — markers only, no derived alerts.

---

## Architecture

### Frontend file changes

```
web/components/stock/
├── tabs/
│   ├── FlowTab.tsx                    # rewritten as thin orchestrator (client component)
│   └── TablesTab.tsx                  # DELETED
├── panels/
│   ├── FlowSnapshotGrid.tsx           # NEW — header cards + info-icon tooltips
│   ├── FlowTimelinePanel.tsx          # NEW — reusable timeline (volume OR OI variant)
│   ├── StrikeProfilePanel.tsx         # NEW — reusable profile (volume OR OI variant) + bucket table
│   ├── TopAlertsTable.tsx             # NEW — extracted, with rule glossary tooltip
│   └── OiMoversTable.tsx              # NEW — upgraded columns, decoded OCC symbol
└── DetailHeader.tsx, TabBar.tsx       # TabBar entry "Tables" removed
```

```
web/lib/
├── occ.ts                             # NEW — pure OCC option-symbol parser (Type/Expiry/Strike)
└── uw-alert-rules.ts                  # NEW — static map: rule slug → human-readable description
```

The tab is a **client component** because the strike profile picker holds local state (selected expiries, strike range). Snapshot grid and tables receive props and render statically inside it; timelines and profiles receive their share of the report payload.

### Backend file changes

```
src/uw_scan/
├── api/endpoints.py                   # add OPTIONS_VOLUME_DAILY slug
├── models.py                          # add OptionsDailyRow, OptionChainPerStrikeRow; extend SingleStockReport + OiChangeRow
├── normalize.py                       # add normalize_options_volume_daily; aggregator for option_chain_per_strike lives in cards/
├── sources/uw.py                      # add fetch_options_volume_daily; bump fetch_option_contracts limit
├── cards/option_chain.py              # NEW — group option-contracts payload into OptionChainPerStrikeRow records
├── storage/repository.py              # persistence methods for new tables + extended oi_change_events columns
├── storage/migrations/NNN_flow_tab_merge.sql   # NEW — options_volume_daily + option_chain_per_strike tables + oi_change_events ALTERs
├── reports/single_stock.py            # stitch new rows into SingleStockReport
└── worker/scheduler.py                # add daily refresh job
```

`OiChangeRow` (existing) is extended with `prev_ask_volume`, `prev_bid_volume`, `prev_mid_volume`, `prev_neutral_volume`, `prev_multi_leg_volume`, `prev_total_premium`. **Verified 2026-05-13 via curl against `/api/stock/GOOGL/oi-change`** — UW returns these as `prev_*` fields. Keeping the UW naming (`prev_`) in the model to stay consistent with their payload conventions even though the values describe the *current* row's volume split, not historical.

**Existing-schema notes (verified 2026-05-13 reading repo):**

- The persistence table for `OiChangeRow` is `uw_scan.oi_change_events` (not `oi_change`). All commit-1 `ALTER TABLE` statements target that name.
- `OiChangeRow.avg_price` already exists in `models.py` (line 191) and the `oi_change_events.avg_price` column already exists. `NOTIONAL = volume * avg_price * 100` in the upgraded OI Movers table uses that field as-is — no new column needed for NOTIONAL.
- The existing `OiPerStrikeRow` / `uw_scan.oi_by_strike` table is keyed by `(ticker, market_date, strike)` with **no expiry column** (and UW's `/api/stock/{ticker}/oi-per-strike` endpoint does not break OI down by expiry either). Therefore the **OI strike-profile cannot be served from `oi_by_strike`** when the user wants per-expiry slicing. See Section 3 for the chosen workaround (sourcing both volume *and* OI per `(expiry, strike)` from the `option-contracts` aggregation), which folds OI and volume into a single new table.

### Data flow

```
worker (nightly)
   └─→ fetch_options_volume_daily(ticker, lookback=180d)      ─→ options_volume_daily table (NEW)
   └─→ fetch_option_contracts(ticker, limit=MAX, filter ±60%) ─→ cards/option_chain.aggregate()
                                                              ─→ option_chain_per_strike table (NEW; backs BOTH profiles)
   └─→ fetch_oi_change(ticker)                                ─→ oi_change_events table (existing, schema extended)
   └─→ fetch_flow_alerts(ticker)                              ─→ flow_alerts table (existing)
   └─→ fetch_short_data / fetch_darkpool                       ─→ existing
   (legacy fetch_oi_per_strike → oi_by_strike is NOT consumed by Flow tab — left in place for other tabs)
                            │
                            ▼
              reports/single_stock.assemble(ticker)
                            │
                            ▼
                /api/stock/{ticker}/report  →  SingleStockReport
                            │
                            ▼
                  RSC: stock/[ticker]/page.tsx
                            │
                            ▼
                  <FlowTab report={...} spot={...} />
```

`SingleStockReport` gains:

```python
options_timeline:        list[OptionsDailyRow]            # 180-day daily series
option_chain_per_strike: list[OptionChainPerStrikeRow]    # both volume + OI per (expiry, strike); client filters
# (existing) oi_change_top, flow.*, dark_pool_*, short_data
```

---

## Section 1: Snapshot Grid

A single 3-column `MetricGrid` (existing primitive in `web/components/stock/panels/MetricGrid.tsx`) that merges the three groups currently split between the two tabs.

### Layout

```
SNAPSHOT
ALERTS ⓘ          NET PREMIUM ⓘ        BULL PREMIUM ⓘ
100               $62,231,752          $66,226,289

BEAR PREMIUM ⓘ    ASK-SIDE PREM ⓘ      BID-SIDE PREM ⓘ
$3,994,537        $30,457,880          $35,573,886

DARK POOL PRINTS ⓘ   DARK POOL NOTIONAL ⓘ
481                  $115,366,960

SHARES AVAIL ⓘ    FEE RATE ⓘ           REBATE RATE ⓘ
10,000,000        0.2500               3.3800
```

Visual: same mono-label style as `VolMetricsCard.tsx` Tile pattern. Sub-headings (`FLOW`, `DARK POOL`, `SHORT DATA`) become small uppercase dividers between rows, not separate sections.

### Tooltip content

Each label gets a small `(i)` icon (12px, `var(--text-muted)`). Hover/tap shows a tooltip with three lines:

1. **Definition** — what the metric is.
2. **Benchmark** — typical range for an active ticker.
3. **Context** — this ticker's 30-day average + today's percentile. **(v1.1)** see Open Items.

Concrete copy lives in a static map `FlowTab/snapshotTooltips.ts`. Examples:

| Label | Tooltip |
|---|---|
| Alerts | "Number of UW flow alerts fired today. Each alert is a rule-based pattern flagged by UW (e.g. repeated hits, ask-side accumulation). Median active ticker: 15–40. >100 = elevated." |
| Net Premium | "Sum of bull-premium minus bear-premium across today's flow alerts. Positive = aggregate alert flow is bullish. The absolute size matters less than the sign and the bull/bear ratio." |
| Bull Premium | "Premium spent on contracts whose alerts UW labels as bullish (calls bought at ask, puts sold at bid). Higher than Bear Premium → directional buyer bias." |
| Bear Premium | "Premium on alerts UW labels bearish (puts bought at ask, calls sold at bid)." |
| Ask-side Premium | "Premium where the trade was filled at the ask — aggressive buyer side. Higher Ask% than Bid% typically signals real demand vs accommodating dealers." |
| Bid-side Premium | "Premium filled at the bid — seller-aggressor side. Often dealer overwriting or institutional yield-seeking." |
| Dark Pool Prints | "Number of off-exchange (ATS) trades today. Dark pool prints don't move the lit tape; large notional clusters near round levels often mark institutional accumulation." |
| Dark Pool Notional | "Total dollar value of off-exchange prints. Compare to today's lit-tape dollar volume on the same name." |
| Shares Avail | "Hard-to-borrow availability. Falling availability + rising fee rate is the classic short-squeeze setup." |
| Fee Rate | "Borrow fee for shorting this stock (% annualized). >5% is meaningfully expensive; >20% is acute squeeze territory." |
| Rebate Rate | "Rebate paid to long holders lending out shares. Inverse signal to fee rate — high rebate = high borrow demand." |

### Component contract

```tsx
<FlowSnapshotGrid
  flow={report.flow}
  darkPool={{ prints: report.dark_pool_print_count, notional: report.dark_pool_notional }}
  shortData={report.short_data}
/>
```

Renders 3-col grid, no internal state, no API calls. Tooltip is a small inline component (no library — uses `<details>` or a CSS-only `:hover` reveal to keep with the codebase's "no UI lib" stance).

---

## Section 2: Timeline charts

Two side-by-side panels showing 180 days of daily options activity.

### Volume Timeline

- **Series A (blue line / `--accent-bg`)** — total options volume per day
- **Series B (orange line / `--accent-warm`, secondary axis)** — put/call volume ratio per day
- **Vertical markers** — earnings dates within the window (we already store these on the volatility tab; reuse the same series)
- **X axis** — daily ticks, weekly labels
- **Tooltip on hover** — date, volume, P/C ratio

### OI Timeline

- **Series A (blue area)** — total open interest per day
- **Series B (orange line, secondary axis)** — put/call OI ratio per day
- **No earnings markers** — OI is structural, daily events don't move it

### Component

Both use one component:

```tsx
<FlowTimelinePanel
  title="OPTIONS VOLUME"
  primary={{ label: "Volume", values: timeline.map(r => r.total_volume), color: "var(--accent-bg)", shape: "line" }}
  secondary={{ label: "Put/Call Vol", values: timeline.map(r => r.pc_volume_ratio), color: "var(--accent-warm)", shape: "line", axis: "right" }}
  dates={timeline.map(r => r.date)}
  markers={earningsDates}   // optional
/>
```

Implementation uses existing `lib/svgChart.ts` helpers (`linearScale`, `pathFromPoints`, `finiteDomain`). Wraps with `panels/AnalyticalSeriesPanel.tsx` for the standard title/subtitle frame.

### UW endpoint (verified 2026-05-13)

**Path:** `/api/stock/{ticker}/options-volume` (`limit` param supported; default returns daily rows). Verified against UW: returns up to 500 trading days (~2 years) in a single call. 180-day window is a single fetch.

**Returned fields** (per row):

```
date, call_volume, put_volume,
call_volume_ask_side, call_volume_bid_side,
put_volume_ask_side,  put_volume_bid_side,
net_call_premium, net_put_premium,
call_premium, put_premium,
bearish_premium, bullish_premium,
call_open_interest, put_open_interest,
avg_3_day_call_volume,  avg_3_day_put_volume,
avg_7_day_call_volume,  avg_7_day_put_volume,
avg_30_day_call_volume, avg_30_day_put_volume
```

**`pc_volume_ratio` and `pc_oi_ratio` are computed client/report-side** — UW doesn't return them; derive as `put_volume / call_volume` and `put_open_interest / call_open_interest`.

**Naming-collision warning.** Two different `bullish_premium` / `bearish_premium` fields enter `SingleStockReport` from different sources:

| Source | Field path | Definition |
|---|---|---|
| `flow-alerts` (Snapshot grid) | `report.flow.bull_premium` | Sum of `total_premium` across alerts UW tagged bullish. Alert-scoped. |
| `options-volume` (Timeline panels) | `options_timeline[i].bullish_premium` | UW's whole-tape daily bullish-flow premium. Tape-scoped. |

They share a similar concept but are **not interchangeable** — different denominators, different definitions, different field names in the codebase (note `bull_premium` vs `bullish_premium`). Treat them as separate metrics in the UI (Snapshot uses alert-scoped; Timeline uses tape-scoped). Do not cross-plot or take ratios between them.

**Bonus discovered during curl:** UW already returns `avg_30_day_*` (and 3-day, 7-day). The Snapshot v1.1 percentile work in Open Item #3 simplifies to a single ratio (today vs avg_30_day) — no historical aggregation table needed.

### New backend types

```python
class OptionsDailyRow(_UwBase):
    date: _date
    call_volume: int | None = None
    put_volume: int | None = None
    call_volume_ask_side: int | None = None
    call_volume_bid_side: int | None = None
    put_volume_ask_side:  int | None = None
    put_volume_bid_side:  int | None = None
    call_premium:  Decimal | None = None
    put_premium:   Decimal | None = None
    net_call_premium: Decimal | None = None
    net_put_premium:  Decimal | None = None
    bullish_premium:  Decimal | None = None
    bearish_premium:  Decimal | None = None
    call_open_interest: int | None = None
    put_open_interest:  int | None = None
    avg_3_day_call_volume:  Decimal | None = None
    avg_3_day_put_volume:   Decimal | None = None
    avg_7_day_call_volume:  Decimal | None = None
    avg_7_day_put_volume:   Decimal | None = None
    avg_30_day_call_volume: Decimal | None = None
    avg_30_day_put_volume:  Decimal | None = None
```

Derived fields computed in the report assembler (not stored):
- `total_volume = call_volume + put_volume`
- `total_oi    = call_open_interest + put_open_interest`
- `pc_volume_ratio = put_volume / call_volume`
- `pc_oi_ratio    = put_open_interest / call_open_interest`

### Storage

```sql
CREATE TABLE IF NOT EXISTS uw_scan.options_volume_daily (
    ticker                  TEXT         NOT NULL,
    trade_date              DATE         NOT NULL,
    call_volume             BIGINT,
    put_volume              BIGINT,
    call_volume_ask_side    BIGINT,
    call_volume_bid_side    BIGINT,
    put_volume_ask_side     BIGINT,
    put_volume_bid_side     BIGINT,
    call_premium            NUMERIC(20, 4),
    put_premium             NUMERIC(20, 4),
    net_call_premium        NUMERIC(20, 4),
    net_put_premium         NUMERIC(20, 4),
    bullish_premium         NUMERIC(20, 4),
    bearish_premium         NUMERIC(20, 4),
    call_open_interest      BIGINT,
    put_open_interest       BIGINT,
    avg_3_day_call_volume   NUMERIC(14, 4),
    avg_3_day_put_volume    NUMERIC(14, 4),
    avg_7_day_call_volume   NUMERIC(14, 4),
    avg_7_day_put_volume    NUMERIC(14, 4),
    avg_30_day_call_volume  NUMERIC(14, 4),
    avg_30_day_put_volume   NUMERIC(14, 4),
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_ovd_ticker_date
    ON uw_scan.options_volume_daily(ticker, trade_date DESC);
```

Migration is idempotent (`IF NOT EXISTS` everywhere) per the repo's standing rule.

---

## Section 3: Strike profile charts

Two stacked panels with a **shared** control bar.

### Shared controls

```
EXPIRIES: [05/15 ×] [05/22 ×] [06/19 ×] [09/18 ×]  + add
STRIKE RANGE: [±30% spot ▾]   (options: ±15%, ±30%, ±60%, All)
```

State lives on the parent `FlowTab` and is passed into both `StrikeProfilePanel` children — Volume and OI views stay in sync.

Default selection = nearest 4 expiries that have data (weeklies and monthlies prioritized; LEAPS not auto-selected).

### Chart spec

- X-axis: strike, auto-trimmed to the selected `±N%` range from current spot
- Y-axis: vertical bars
  - Above zero: call volume/OI at that strike, color `var(--positive)` (green)
  - Below zero: put volume/OI at that strike, color `var(--negative)` (red), rendered as negative magnitude
- Vertical dashed reference line at current spot
- Hover tooltip: strike, call value, put value, % from spot
- `role="img"` + `<title>` for a11y per `web/components/CLAUDE.md`

### Bucket table (one per profile, beneath the chart)

|        | Total | ITM | OTM |
|--------|-------|-----|-----|
| Calls  | …     | …   | …   |
| Puts   | …     | …   | …   |
| Total  | …     | …   | …   |

- Calls: ITM = strike < spot, OTM = strike ≥ spot.
- Puts: ITM = strike > spot, OTM = strike ≤ spot.
- Numbers reflect the *currently selected* expiries (sums change with the picker).

### Component contract

```tsx
<StrikeProfilePanel
  title="VOLUME BY STRIKE"
  variant="volume"                          // controls "Calls/Puts" label only
  rows={option_chain_per_strike}            // [{expiry, strike, call_volume, put_volume, call_oi, put_oi}]
  metric={variant === "volume" ? "volume" : "oi"}   // picks (call_volume, put_volume) or (call_oi, put_oi)
  selectedExpiries={selectedExpiries}
  strikeRange={strikeRange}                 // {min, max} computed from spot
  spot={spot}
/>
```

### Per-(expiry, strike) data fetch — covers both Volume and OI

**Why a single combined source instead of two:** The existing `uw_scan.oi_by_strike` table aggregates OI across expiries (key is `(ticker, market_date, strike)`, no `expiry` column), and the underlying UW `oi-per-strike` endpoint matches that shape. To support the per-expiry slicing both profiles need, **OI must come from a new source**. Since we already have to aggregate `option-contracts` for volume, we serve both metrics from the same aggregation — one new table, one fetch.

`/api/stock/{ticker}/option-contracts` (existing UW endpoint slug `OPTION_CONTRACTS`) returns per-contract `volume` and `open_interest`. The existing fetcher in `sources/uw.py:244` is hard-coded to `limit=50` — wholly inadequate for an active large-cap that has 200–1500 contracts within ±60% of spot. **Commit 2 raises this**:

- Bump the call to a UW-documented maximum (verify via curl during commit 2; if UW caps below the size of `SPY` chain, paginate by `expiry` using the `option/expirations` endpoint to drive sub-fetches).
- Filter server-side: drop strikes outside `±60% × spot` and expiries beyond 1 year before aggregation — keeps the resulting row count predictable.
- The aggregator (new helper in `cards/option_chain.py` or under `reports/`) groups filtered contracts by `(expiry, strike, type)` and emits `OptionChainPerStrikeRow` records.

```python
class OptionChainPerStrikeRow(_UwBase):
    expiry:      _date
    strike:      Decimal
    call_volume: int | None = None
    put_volume:  int | None = None
    call_oi:     int | None = None
    put_oi:      int | None = None
```

Storage:

```sql
CREATE TABLE IF NOT EXISTS uw_scan.option_chain_per_strike (
    ticker        TEXT      NOT NULL,
    snapshot_date DATE      NOT NULL,
    expiry        DATE      NOT NULL,
    strike        NUMERIC(14, 4) NOT NULL,
    call_volume   BIGINT,
    put_volume    BIGINT,
    call_oi       BIGINT,
    put_oi        BIGINT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, snapshot_date, expiry, strike)
);
CREATE INDEX IF NOT EXISTS idx_ocps_ticker_snap
    ON uw_scan.option_chain_per_strike(ticker, snapshot_date DESC);
```

The Volume profile reads `(call_volume, put_volume)`; the OI profile reads `(call_oi, put_oi)` — same table, same selected expiries. The legacy `oi_by_strike` table stays as-is (it still backs other consumers like the Market Structure tab); we don't touch it.

**Payload-size sanity check (must complete during commit 2 before code lands):** run the actual fetcher against `SPY`, `QQQ`, `NVDA`, `TSLA`, `AAPL` at the chosen filter window and confirm:

- Single-fetch row count stays under ~3,000 raw contracts (well within Postgres-row-write performance budget).
- Per-ticker write to `option_chain_per_strike` after filtering stays under 1,500 rows.
- If a ticker exceeds these bounds, paginate by expiry. This is a quick empirical check — if it passes, lock single-fetch; if not, paginate.

---

## Section 4: Tables

### Top Alerts

Same data as today. Changes:

- `volume_oi_ratio` truncated to 2 decimals (`fmtDecimal(v, 2)`).
- `id` already truncates to 8 chars; keep.
- **New:** `(i)` icon on the `RULE` column **header** opens a single tooltip listing every UW alert rule with a one-sentence description. Rule descriptions defined in `web/lib/uw-alert-rules.ts`:

```ts
export const UW_ALERT_RULES: Record<string, string> = {
  RepeatedHits:
    "Same strike hit repeatedly throughout the day — suggests a single buyer accumulating a position with multiple child orders.",
  RepeatedHitsDescendingFill:
    "Same strike hit repeatedly with each fill priced lower than the previous — buyer improving fills, often a price-sensitive accumulator.",
  RepeatedHitsAscendingFill:
    "Repeated hits with each fill priced higher than the previous — buyer chasing, classic urgency signal.",
  // ... fill in full UW rule set
};
```

Default sort: `total_premium` desc (current behavior). Limit: 10 rows (current).

### OI Change — Top Movers (upgraded)

| TYPE | EXPIRY | STRIKE | DTE | %SPOT | ΔOI | VOL/\|ΔOI\| | NOTIONAL | ASK% | FLAG |
|---|---|---|---|---|---|---|---|---|---|

Columns:

- **TYPE** — `C` or `P`, parsed from OCC symbol (chr 6 in the strike segment, after the date)
- **EXPIRY** — parsed `YYMMDD` → `YYYY-MM-DD`
- **STRIKE** — parsed integer cents from the OCC symbol → dollars
- **DTE** — `(expiry - today)` in days (client-side, derived from EXPIRY)
- **%SPOT** — `(strike - spot) / spot * 100`, signed, formatted `+6.2%` / `-17.4%`
- **ΔOI** — existing `oi_diff_plain`, signed, thousands-grouped
- **VOL/|ΔOI|** — `volume / abs(oi_diff_plain)`, 2 decimals. Color encoding:
  - `[0.8, 1.5]` → `var(--positive)` (clean opening)
  - `(1.5, 5]`  → default text
  - `> 5` → `var(--warning)` (churn)
  - `< 0.8` → `var(--text-muted)` (probably stale reporting)
- **NOTIONAL** — `volume * avg_price * 100`, formatted as dollars (k/M). Uses existing `OiChangeRow.avg_price` (already present in `models.py:191` and `oi_change_events.avg_price`) — no new column required.
- **ASK%** — `prev_ask_volume / (prev_ask_volume + prev_bid_volume + prev_mid_volume + prev_neutral_volume) * 100`. Verified available in UW payload (2026-05-13). Renders `—` only on null rows.
- **FLAG** — small chip badge, computed from the row:
  - `OPENING ↑` — `vol_oi_ratio ∈ [0.8, 1.5]` AND `type = C` AND (`ask_pct > 60` OR `ask_pct` unknown)
  - `OPENING ↓` — same, `type = P`
  - `0DTE LOTTO` — `DTE = 0`
  - `CHURN` — `vol_oi_ratio > 5`
  - `LEAPS` — `DTE > 365`
  - blank otherwise (multiple flags can stack)

Default sort: `notional` desc. Limit: 10 rows. Drop the existing `Avg Price` and `Prev OI` columns to make room.

### OCC symbol parser (`web/lib/occ.ts`)

```ts
// Parses OCC 21-char option symbol: ROOT(≤6) | YYMMDD | C/P | STRIKE_CENTS(8 digits)
// e.g. "GOOGL260612P00335000" → {root: "GOOGL", expiry: "2026-06-12", type: "P", strike: 335}
export type OccSymbol = {
  root: string;
  expiry: string;    // YYYY-MM-DD
  type: "C" | "P";
  strike: number;    // dollars
};

export function parseOccSymbol(symbol: string): OccSymbol | null { /* ... */ }
```

Pure function. Unit-tested with Vitest. Returns `null` for malformed inputs — callers render the raw `option_symbol` as fallback.

### Backend extension to `OiChangeRow`

Verified UW field names (2026-05-13 curl `/api/stock/GOOGL/oi-change`):

```python
class OiChangeRow(_UwBase):
    # ... existing fields ...
    prev_ask_volume:           int | None = None  # NEW
    prev_bid_volume:           int | None = None  # NEW
    prev_mid_volume:           int | None = None  # NEW
    prev_neutral_volume:       int | None = None  # NEW
    prev_multi_leg_volume:     int | None = None  # NEW
    prev_stock_multi_leg_volume: int | None = None  # NEW (rarely populated)
    prev_total_premium:        Decimal | None = None  # NEW
    last_ask:                  Decimal | None = None  # NEW (top-of-book at print)
    last_bid:                  Decimal | None = None  # NEW
```

`ASK%` derivation lives on the frontend in `OiMoversTable`:

```ts
const denom = (row.prev_ask_volume ?? 0) + (row.prev_bid_volume ?? 0)
            + (row.prev_mid_volume ?? 0) + (row.prev_neutral_volume ?? 0);
const askPct = denom > 0 ? (row.prev_ask_volume ?? 0) / denom * 100 : null;
```

Migration adds the columns to `uw_scan.oi_change_events` (verified table name); pre-existing rows backfill as `NULL`. `ALTER TABLE … ADD COLUMN … NULL` is a Postgres metadata-only operation, safe on a populated table.

---

## Phasing — commit breakdown (single PR)

Eight focused commits within one branch `feat/flow-tab-merge` → one PR to main:

1. **`db: add options_volume_daily + option_chain_per_strike tables, extend oi_change_events`**
   Migration files only. Adds the two new tables and `ALTER TABLE` columns on `uw_scan.oi_change_events` for the `prev_*` aggressor fields. Verifies the schema lands cleanly.

2. **`backend: wire UW options-volume + option-chain aggregation`**
   New `OPTIONS_VOLUME_DAILY` slug → `/api/stock/{ticker}/options-volume` (verified path). New `cards/option_chain.py` aggregator that turns the per-contract `option_contracts` payload (limit raised from 50; filtered to ±60% spot, ≤1y) into `OptionChainPerStrikeRow` records grouped by `(expiry, strike)` with both volume and OI columns. New fetcher in `sources/uw.py`, normalizer, models, repository methods. Includes the empirical payload-size probe against SPY/QQQ/NVDA/TSLA/AAPL before locking the limit. Unit tests on normalization + aggregation with captured payload fixtures. Live integration test marked `live` (skipped by default).

3. **`backend: extend OiChangeRow + normalizer with prev_* aggressor fields`**
   Model + normalizer + repository updates for the `prev_ask_volume` / `prev_bid_volume` / `prev_mid_volume` / `prev_neutral_volume` / `prev_total_premium` / `last_ask` / `last_bid` fields. Fields are confirmed present in the UW payload (2026-05-13).

4. **`backend: include timeline + option_chain_per_strike in SingleStockReport`**
   Wire the new rows into `reports/single_stock.assemble()`. Compute derived `total_volume`, `total_oi`, `pc_volume_ratio`, `pc_oi_ratio` here (not stored). Regenerate `openapi.json` → `web/lib/types.ts` in the same commit.

5. **`worker: nightly refresh for options-volume + option-chain-per-strike`**
   Add to `worker/scheduler.py`. Runs after the existing nightly vol rollup. Single 180-day fetch per ticker.

6. **`web: merge tabs — snapshot grid + tooltips, tables extracted`**
   Delete `TablesTab.tsx`. Rewrite `FlowTab.tsx` as orchestrator. New `FlowSnapshotGrid`, `TopAlertsTable`, `OiMoversTable` (with ASK% wired through from `prev_*` fields). Add `web/lib/occ.ts` + `web/lib/uw-alert-rules.ts` with unit tests. Remove `Tables` from `TabBar`.

7. **`web: add Volume + OI timeline panels`**
   New `FlowTimelinePanel` component used twice. Earnings markers reuse the volatility tab's date series.

8. **`web: add Volume + OI strike-profile panels`**
   New `StrikeProfilePanel` component used twice. Shared expiry picker + strike-range control on parent. ITM/OTM bucket tables.

Test gate (must pass before each commit): `uv run pytest` + `cd web && npm run typecheck && npm run test`. Before opening the PR: `npm run lint`, `npm run test:e2e` (Playwright happy-path on a real ticker).

---

## Testing strategy

**Backend (pytest)**

- Unit: each new normalizer with fixture payloads (happy path + missing fields).
- Unit: `cards/option_chain.aggregate()` — turns per-contract `option_contracts` into `OptionChainPerStrikeRow` records grouped by `(expiry, strike)` (covers happy path, filter pruning, multiple expiries on same strike).
- Integration (pytest-postgresql): repository round-trip for `options_volume_daily` + `option_chain_per_strike` + extended `oi_change_events` columns, idempotency check (re-run = no duplicates).
- Live (marked `live`, opt-in): one ticker against UW production — confirms the verified `options-volume` and extended `oi-change` payload shapes remain stable.

**Frontend (vitest)**

- `parseOccSymbol` — happy path, malformed, exotic roots (`BRK.B`-style if encountered).
- `FlowSnapshotGrid` — renders all tiles with sample report; tooltip rendering.
- `OiMoversTable` — flag derivation, vol/|ΔOI| color encoding, notional formatting, sort by notional.
- `StrikeProfilePanel` — bucket math (ITM/OTM), strike-range trimming.
- `FlowTimelinePanel` — dual-axis scaling, marker placement (snapshot tests on rendered SVG).

**E2E (Playwright)**

- Navigate to a ticker, click Flow tab, expand a tooltip, change strike range from ±30% to ±15% → profile chart re-renders, change expiry chip selection → both profiles update in sync.

---

## Open items / risks

1. ~~UW `oi-change` payload — ask/bid breakdown.~~ **RESOLVED 2026-05-13:** UW returns `prev_ask_volume`, `prev_bid_volume`, `prev_mid_volume`, `prev_neutral_volume`, `prev_total_premium`, `last_ask`, `last_bid`. Wired into commit 3, no Phase-2 deferral.

2. ~~UW historical-options endpoint exact path.~~ **RESOLVED 2026-05-13:** `/api/stock/{ticker}/options-volume`. Returns 500 trading days (~2 years) per call; includes call/put volume + OI + ask/bid aggressor split + bullish/bearish premium + built-in 3d/7d/30d averages. 180-day window is one fetch per ticker.

3. **Snapshot "context" percentile.** v1 ships definition + benchmark only.

   **v1.1 scope — restricted to volume-derived tiles:** UW's `avg_30_day_call_volume` / `avg_30_day_put_volume` come from `options-volume` (whole-tape, not alert-scoped), so the today-vs-30d-avg ratio is well-defined **only for tiles backed by that source**. In practice that means a new tile pair like `TODAY CALL VOL (vs 30d)` and `TODAY PUT VOL (vs 30d)` could ship as a single field read off `options_timeline[today]` — no derivation table needed.

   **Explicitly out of v1.1:** `Alerts`, `Net Premium`, `Bull Premium`, `Bear Premium` ratios. These tiles come from `flow-alerts` (alert-scoped premium), whose history UW does not expose pre-aggregated. A real percentile for those tiles requires a separate daily snapshot table (e.g. `flow_alerts_daily_rollup`) populated by the worker — that is a v1.2+ project, not a v1.1 field read.

   v1.1 stays behind a frontend feature flag until copy + UI position are reviewed.

4. **OCC root parsing for special tickers.** Tickers like `BRK.B` use a non-standard OCC encoding (`BRKB ` etc.). Initial implementation handles standard cases; falls back to raw `option_symbol` display when parse fails. Acceptable for v1 — the watchlist is dominated by standard tickers.

5. **Volume-per-strike storage cost.** Per ticker per day = expiry-count × strike-count rows; for a 20-ticker watchlist with ~20 expiries × ~50 strikes ≈ 20k rows/day. Retention: 90 days. Index tuning revisited if scan times degrade.

---

## Success criteria

- One `Flow` tab on the per-stock page; `Tables` no longer in the TabBar.
- All snapshot metrics have a working `(i)` tooltip with definition + benchmark.
- Both timeline charts render real data for any watchlist ticker.
- Strike-profile expiry picker is multi-select with a default of 4 nearest expiries; strike-range picker trims correctly; both profiles + bucket tables update in lockstep.
- OI Movers table shows decoded Type/Expiry/Strike + DTE + %SPOT + Vol/|ΔOI| + Notional + FLAG; ASK% either shows real values or `—`, never wrong.
- `uv run pytest`, `npm run typecheck`, `npm run test`, `npm run test:e2e` all green.
- PR posted to main, CI green, reviewer can navigate the new tab on a live ticker.
