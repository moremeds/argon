# Vanna & Charm — Market Structure sub-tabs (per-ticker)

**Status:** Draft · 2026-05-21
**Scope:** Per-ticker stock detail page → `Market Structure` tab → new `GEX | VANNA | CHARM` sub-tab switcher. Vanna and Charm panels mirror the UnusualWhales reference experience (header narrative + 4 tiles + expiry dropdown + Net + Call/Put curves). All derived summary values are persisted to Postgres.

## Motivation

Vanna (∂Δ/∂σ) and Charm (∂Δ/∂t) are already persisted at `(run_id, ticker, expiry, strike)` granularity in `uw_scan.exposures_by_expiry_strike`. They are unsurfaced in `SingleStockReport` and never rendered. The Market Structure tab today shows GEX-centric panels only.

This spec adds two new analytical surfaces — vanna and charm — using the same per-strike exposure data, organised as sub-tabs under Market Structure. Each surface tells a different dealer-positioning story:

- **Vanna** answers *"how does dealer Δ change when IV moves?"* — i.e., spot impact of a vol shock.
- **Charm** answers *"how does dealer Δ decay through time?"* — i.e., mechanical hedge flow into expiration.

## Out of scope (v1)

- Historical time-series of vanna/charm (the `greek_exposure_daily` table doesn't have these columns — would need a backfill).
- Vanna/charm regime quadrant against the existing Volatility-tab regime view.
- Vanna/charm signals contributing to Scanner / Trade Plan output.

These are good follow-ups; flagged but not blocking.

## User-facing layout

### `MarketStructureTab.tsx` — after this change

```
[ existing summary panels — kept unchanged ]
  GexLevelTiles
  ExpectedRangeBar | DirectionalBiasPanel        (2-col)
  MarketStructureHistoryTable
  MaxPainTable

[ NEW: Greek-exposure sub-tabs ]
  ┌─[ GEX ]─[ VANNA ]─[ CHARM ]──────────────────────────┐
  │                                                       │
  │  (one panel rendered at a time)                       │
  └───────────────────────────────────────────────────────┘
```

The summary panels are tab-agnostic context, so they stay above the sub-tab switcher. The existing `GexProfileChart` moves into the `[GEX]` sub-tab.

### Vanna sub-tab (mirrors UW reference image 1)

```
VANNA · VOLATILITY
Long Vanna — IV spikes pressure stock lower via dealer selling
If IV rises, dealers gain delta and will likely sell stock to rehedge.

┌──────────────┬──────────────────┬─────────────────────┬──────────────────┐
│ Net Vanna    │ Top vol-sensitive │ Δ from +1pt IV     │ Vol-shock regime │
│ +$1.3M Long  │ $450.00 / $227K   │ +$4.14M sell-Δ     │ Procyclical      │
└──────────────┴──────────────────┴─────────────────────┴──────────────────┘

Expiry: [ 2026-05-18 ▼ ]

┌─ Net Vanna Exposure ─────────────┐  ┌─ Vanna Exposure (Call/Put) ──────┐
│ purple line                       │  │ green Call · red Put             │
│ yellow Price · purple-dashed Flip │  │ yellow Price                     │
│ peak strike labels                │  │ peak strike labels               │
└───────────────────────────────────┘  └───────────────────────────────────┘
```

### Charm sub-tab (mirrors UW reference image 2)

Same shell. Tile row reads:

```
┌──────────────┬─────────────────────────────┬──────────────────────────┬──────────────────────┐
│ Live charm   │ Positioning                  │ Signal quality           │ Where it matters     │
│ Sell -$15.5T │ Sell -$100M · 67% imbalance  │ live + positioning align │ $425 · 3.7% > spot   │
└──────────────┴─────────────────────────────┴──────────────────────────┴──────────────────────┘
```

Headline narrative: e.g. *"Mechanical SELL pressure into the close"* / *"Mechanical BUY pressure into the close"*, sign-driven by `net_charm`.

## Backend — data model & persistence

### Existing — already populated

```sql
-- exposures_by_expiry_strike (migration 001)
(run_id, ticker, market_date, expiry, strike, dte,
 call_delta, put_delta, call_gex, put_gex,
 call_vanna, put_vanna, call_charm, put_charm)
```

Written by `repo.insert_greek_exposure_rows()` from `pipeline.py` and `cockpit_daily_snapshot.py`. No change here.

### New — `051_exposures_summary.sql`

Per-expiry derived summary. One row per `(run_id, ticker, expiry)`. `run_id` is `BIGINT` with FK `ON DELETE CASCADE` to `scan_runs(run_id)` — matches the convention used by every other run-keyed table (`scan_runs.run_id` is `BIGSERIAL`; `INTEGER` would overflow):

```sql
CREATE TABLE IF NOT EXISTS uw_scan.exposures_summary (
    run_id              BIGINT  NOT NULL
                                REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker              TEXT    NOT NULL,
    expiry              DATE    NOT NULL,
    market_date         DATE    NOT NULL,
    dte                 INTEGER,
    spot                NUMERIC,

    -- Vanna derivatives
    net_vanna           NUMERIC,
    top_vanna_strike    NUMERIC,
    top_vanna_value     NUMERIC,
    delta_shock_1pt_iv  NUMERIC,
    vanna_regime        TEXT,    -- 'procyclical' | 'countercyclical' | 'neutral'
    vanna_flip          NUMERIC, -- strike where cumulative net vanna flips sign
    vanna_headline      TEXT,
    vanna_subtitle      TEXT,

    -- Charm derivatives
    net_charm           NUMERIC,
    charm_pin_strike    NUMERIC,
    charm_above_sum     NUMERIC,
    charm_below_sum     NUMERIC,
    charm_imbalance_pct NUMERIC,
    charm_signal_quality TEXT,   -- 'aligned' | 'mixed' | 'weak'
    charm_flip          NUMERIC,
    charm_headline      TEXT,
    charm_subtitle      TEXT,

    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker, expiry)
);

CREATE INDEX IF NOT EXISTS exposures_summary_ticker_date
    ON uw_scan.exposures_summary (ticker, market_date);
```

Idempotent per `storage/CLAUDE.md` rules; `IF NOT EXISTS`, upsert on PK.

### New — Pydantic models (`src/uw_scan/models/scanner.py`)

```python
class StrikeExposureRow(_UwBase):
    """One per-(expiry, strike) raw row from exposures_by_expiry_strike."""
    strike: Decimal
    expiry: _date
    dte: int | None = None
    call_vanna: Decimal | None = None
    put_vanna:  Decimal | None = None
    call_charm: Decimal | None = None
    put_charm:  Decimal | None = None

class ExposuresSummaryRow(_UwBase):
    """One per-(expiry) derived summary for the Market Structure tab."""
    expiry: _date
    dte: int | None = None
    spot: Decimal | None = None
    # vanna
    net_vanna: Decimal | None = None
    top_vanna_strike: Decimal | None = None
    top_vanna_value:  Decimal | None = None
    delta_shock_1pt_iv: Decimal | None = None
    vanna_regime: str | None = None
    vanna_flip: Decimal | None = None
    vanna_headline: str | None = None
    vanna_subtitle: str | None = None
    # charm
    net_charm: Decimal | None = None
    charm_pin_strike: Decimal | None = None
    charm_above_sum:  Decimal | None = None
    charm_below_sum:  Decimal | None = None
    charm_imbalance_pct: Decimal | None = None
    charm_signal_quality: str | None = None
    charm_flip: Decimal | None = None
    charm_headline: str | None = None
    charm_subtitle: str | None = None
```

`SingleStockReport` adds two fields (additive, no contract break):

```python
strike_exposures: list[StrikeExposureRow] = []
exposures_summary: list[ExposuresSummaryRow] = []
```

### New — derivers (`src/uw_scan/cards/exposures.py`)

Pure functions over `list[GreekExposureRow]`. Domain seam separate from `cards/gex.py`.

```python
def per_expiry_groups(rows) -> dict[date, list[GreekExposureRow]]: ...

def net_vanna(rows) -> Decimal | None
def top_vanna_strike(rows) -> tuple[Decimal, Decimal] | None    # (strike, value)
def delta_shock_1pt_iv(rows) -> Decimal | None                  # Σ net_vanna × 0.01
def vanna_regime(net_vanna) -> Literal["procyclical","countercyclical","neutral"]
def vanna_flip(rows, spot) -> Decimal | None                    # cum-sum sign-flip strike
def vanna_narrative(net_vanna, regime) -> tuple[str, str]       # (headline, subtitle)

def net_charm(rows) -> Decimal | None
def charm_pin_strike(rows) -> Decimal | None                    # argmax|net_charm|
def charm_imbalance(rows, spot) -> tuple[Decimal, Decimal, Decimal]
                                                                # (above, below, imbalance_pct)
def charm_signal_quality(live, positioning) -> str
def charm_flip(rows, spot) -> Decimal | None
def charm_narrative(net_charm, signal_quality) -> tuple[str, str]
```

**Sign conventions:**
- Per-strike `net = call_x + put_x` (consistent with the existing `net_gex` rule).
- `vanna_regime`: `procyclical` when `net_vanna > 0` (dealers sell into vol rises), `countercyclical` when `< 0`. Threshold for `neutral`: |net| < 1e3 (tunable; lives as a constant in the deriver).
- `delta_shock_1pt_iv`: how much net delta dealers must hedge if IV rises 1 vol-point. Σ vanna × 0.01 (vanna is dΔ per 1.0 of vol; 1pt = 0.01).
- `charm_signal_quality`: `aligned` when `sign(live) == sign(net_positioning_imbalance)`; `mixed` otherwise; `weak` when either is near zero.

### New — fetcher (`src/uw_scan/storage/fetchers.py`)

```python
def fetch_strike_exposures(self, run_id: int, ticker: str) -> list[dict]: ...
def fetch_exposures_summary(self, run_id: int, ticker: str) -> list[dict]: ...
                                                            # NOTE: existing fn is per-aggregate;
                                                            # this is per-expiry summary rows.
                                                            # Rename existing → fetch_exposures_aggregate.
```

The existing `fetch_exposures_summary` (returns `total_call_gex` / `total_put_gex` / etc. as a single dict) is renamed to `fetch_exposures_aggregate` to free the name. Single caller in `reports/single_stock.py` is updated. No external contract change.

### New — repository method (`storage/options.py`)

```python
def upsert_exposures_summary(self, run_id: int, ticker: str, rows: list[ExposuresSummaryRow]) -> int
```

Called from `pipeline.py` and `cockpit_daily_snapshot.py` directly after `insert_greek_exposure_rows()`.

### Report assembler (`reports/single_stock.py`)

After the existing `strike_gex_curve` block:

```python
strike_exp_raw = repo.fetch_strike_exposures(run_id, ticker)
strike_exposures = [StrikeExposureRow(...) for row in strike_exp_raw]

summary_raw = repo.fetch_exposures_summary(run_id, ticker)
exposures_summary = [ExposuresSummaryRow(...) for row in summary_raw]
```

Both attached to the response.

## Frontend

### Layout changes

**`web/components/stock/tabs/MarketStructureTab.tsx`** — append the sub-tab switcher after the existing panels. The current page is a server component; the sub-tab switcher needs local UI state, so we extract a small client wrapper:

```tsx
// MarketStructureTab.tsx (unchanged top portion)
<GexLevelTiles report={report} />
<div /* 2-col */>
  <ExpectedRangeBar />
  <DirectionalBiasPanel />
</div>
<MarketStructureHistoryTable />
<MaxPainTable />

// NEW
<GreekSubTabs report={report} />
```

### New components

```
web/components/stock/panels/greeks/
├── GreekSubTabs.tsx              "use client" — renders [GEX | VANNA | CHARM] switcher
├── VannaPanel.tsx                header + tiles + dropdown + charts
├── CharmPanel.tsx                header + tiles + dropdown + charts
├── NetExposureChart.tsx          shared SVG line chart (single purple line)
├── CallPutExposureChart.tsx      shared SVG line chart (green call + red put)
├── ExpiryDropdown.tsx            HTML <select> styled to match
└── ExposureTile.tsx              4-up tile pattern (mono label + value + sub-line)
```

`GexProfileChart` is unchanged; it's just *rendered inside* the `[GEX]` sub-tab now.

### Chart contract

`NetExposureChart` and `CallPutExposureChart` both take:

```ts
type Props = {
  curve: { strike: number; netValue: number | null;
           callValue?: number | null; putValue?: number | null }[];
  spot: number | null;
  flipStrike: number | null;       // null → don't render flip line
  yLabel: "Vanna" | "Charm";
  title: string;                   // "Net Vanna Exposure (12 DTE) — TSLA"
  width?: number;                  // default 560
  height?: number;                 // default 360
};
```

Implementation: hand-rolled SVG using existing `linearScale` / `pathFromPoints` / `finiteDomain` from `lib/svgChart.ts`. Smoothing is **linear polyline** (no Bezier) in v1 — matches `SmileChart` / `TermStructureChart` styling. If we want spline smoothing later, that's an enhancement on the shared helpers, not this panel.

Reference lines:
- Spot: vertical `var(--warning)` solid line + "Price: X.XX" label above.
- Flip: vertical `var(--accent-vol)` (purple) dashed line + "Vanna/Charm flip: X.XX" label.

Peak labels: annotate the global min and global max strike on the curve with the strike value in the curve's color. Mirrors UW reference.

### Derive helpers (frontend)

The narrative strings + tile values come pre-computed from the API (`ExposuresSummaryRow`). The frontend only needs to:

1. Look up the row matching the selected `expiry`.
2. Filter `strike_exposures` by `expiry === selected` and pass to the charts.
3. Format the tile values (existing `lib/formatters.ts` covers `fmtSigned`, `fmtMoney`-style → we may add a `fmtMoneyAbbrev` helper for `+$1.3M` / `-$15.5T` ranges).

No analytical computation lives client-side. (This is what differentiates this design from the "client-side derive util" option that was considered.)

### Expiry dropdown

```tsx
<ExpiryDropdown
  options={summaryRows.map(r => ({ value: r.expiry, label: `${r.expiry} (${r.dte}d)` }))}
  value={selected}
  onChange={setSelected}
/>
```

Default selected: nearest-expiry (smallest `dte` ≥ 0). Persist selection in `useState`; not in URL for v1 — can lift to query param later if useful.

## Data flow (request lifecycle)

```
GET /stock/{ticker}/report
  → reports.single_stock.build_single_stock_report()
     ├─ repo.fetch_strike_exposures(run_id, ticker)         (NEW: raw per-strike rows)
     ├─ repo.fetch_exposures_summary(run_id, ticker)        (NEW: per-expiry summary rows)
     └─ assemble SingleStockReport with two new fields

Page render (RSC) →
  MarketStructureTab (server)
    ↳ GreekSubTabs ("use client")
        ↳ [GEX]   → existing GexProfileChart
        ↳ [VANNA] → VannaPanel
            ├─ Headline / subtitle from summary_row.vanna_*
            ├─ 4 tiles from summary_row.*
            ├─ ExpiryDropdown over summary rows
            └─ NetExposureChart + CallPutExposureChart filtered by expiry
        ↳ [CHARM] → CharmPanel (same shape, charm_*)
```

### Job lifecycle

```
worker → cockpit_daily_snapshot job
  ↳ fetch /greek-exposure/expiry/strike from UW
  ↳ normalize → list[GreekExposureRow]
  ↳ repo.insert_greek_exposure_rows()
  ↳ NEW: derive per-expiry summary via cards/exposures.py
  ↳ NEW: repo.upsert_exposures_summary()
```

Re-running is a no-op — the summary table has PK `(run_id, ticker, expiry)` with `ON CONFLICT DO UPDATE`.

## Error handling

- **Missing UW data** (a ticker with no `/greek-exposure` rows for `run_id`): both new lists empty. Frontend renders an empty-state per panel: *"Vanna data not yet available for this run."*
- **Single expiry has only one strike with non-null vanna**: curve renders as a single point; chart still draws the spot reference line. Empty-state copy clarifies why no curve is visible.
- **`net_vanna` near zero**: regime classified as `neutral` (constant threshold in deriver); headline switches to a neutral narrative.
- **NULL guards**: All `Decimal | None` fields skip the row in cum-sum / flip calculations (re-uses the existing `finiteDomain` pattern on the frontend).

## Testing

### Python — `tests/unit/cards/test_exposures.py`

- `net_vanna` / `net_charm`: sums correctly when call/put both present, when only one side present, when all None.
- `vanna_flip`: returns the correct strike on monotone curves and on multi-flip curves (picks lowest sign-flip ≥ spot, mirroring `find_flip_strike`).
- `vanna_regime`: each of the three branches with edge-case values around the neutral threshold.
- `charm_imbalance`: split-around-spot math.
- `vanna_narrative` / `charm_narrative`: deterministic string outputs per regime/signal combo (table-driven tests).

### Python — `tests/integration/storage/test_exposures_summary.py`

`pytest-postgresql` fixture; insert `exposures_by_expiry_strike` rows; assert `upsert_exposures_summary` round-trips; re-run idempotency.

### Python — `tests/integration/reports/test_single_stock_exposures.py`

End-to-end: fake run with seeded rows → assert `SingleStockReport.strike_exposures` and `.exposures_summary` populated with expected values.

### Frontend — `web/tests/unit/exposurePanels.test.tsx`

- `VannaPanel`: renders headline + 4 tiles from a fixture summary row.
- `CharmPanel`: renders empty state when summary is missing.
- `ExpiryDropdown`: changing selection re-filters the curves passed to children (data-driven assertion on child props).
- `NetExposureChart` / `CallPutExposureChart`: SVG path `d=` attribute contains expected M/L coordinates for fixture data.
- Sub-tab switcher: clicking `[VANNA]` hides GEX panel, shows VannaPanel.

### Frontend — `web/tests/e2e/marketStructure.spec.ts`

- Existing market-structure E2E continues to pass (no regression in summary panels).
- New: navigate to `/stock/TSLA`, click `Market Structure` tab, click `VANNA` sub-tab, assert headline text appears, change dropdown, assert chart updates.

## Open items deferred

1. **Historical vanna/charm time-series.** Requires extending `greek_exposure_daily` (migration 039) with new columns + backfill from `exposures_by_expiry_strike`. Could power a future "Vanna/Charm history" mini-chart inside each sub-tab.
2. **Spline-smoothed curves.** UW reference uses Catmull-Rom or monotone-cubic. v1 uses linear polylines (consistent with `SmileChart` / `TermStructureChart`). If we want spline, extend `lib/svgChart.ts` with a `pathFromPointsSmooth(points)` helper used by all curve panels.
3. **Persisting derivation thresholds.** The `neutral` threshold (1e3) and the `signal_quality` cut-offs are constants in `cards/exposures.py`. If they get tuned, they should move to a config or per-ticker calibration table.
4. **Vanna/charm contribution to Scanner signals.** Future Scanner gate could use `vanna_regime == 'procyclical'` + high IV-Rank as a confluence signal. Out of scope here.

## Implementation plan (high level — full plan in next step)

The work decomposes into milestone commits, per the project's "milestone commits" rule:

- **Slice 1 — Models + migration.** New Pydantic models, migration `051_exposures_summary.sql`, `__init__.py` exports. Tests: model exports + migration idempotency.
- **Slice 2 — Derivers + unit tests.** `cards/exposures.py` + `tests/unit/cards/test_exposures.py`.
- **Slice 3 — Persistence + integration tests.** `upsert_exposures_summary`, fetchers, wire into `pipeline.py` + `cockpit_daily_snapshot.py`.
- **Slice 4 — Report assembler + API surface.** Wire new fields into `reports/single_stock.py`; rename existing `fetch_exposures_summary` → `fetch_exposures_aggregate`; `npm run gen:types`.
- **Slice 5 — Frontend chart components.** `NetExposureChart`, `CallPutExposureChart`, shared in `panels/greeks/`. Vitest unit tests on SVG path output.
- **Slice 6 — VannaPanel + CharmPanel + ExpiryDropdown.** Tile pattern, dropdown wiring.
- **Slice 7 — GreekSubTabs + integration into MarketStructureTab.** Move `GexProfileChart` rendering into the sub-tab. E2E test.

Each slice ends with `uv run pytest` + `cd web && npm run typecheck && npm run test` green, then a milestone commit.
