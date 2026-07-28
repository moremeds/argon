# Theta Harvester Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port radon's Theta Harvester short-strangle scanner into argon as a sub-tab on `/scanner`, ranking off the warm store at zero UW cost and persisting per-candidate rows that a markout job can score later.

**Architecture:** A pure compute module (`scanners/theta_harvester.py`) selects one best short strangle per watchlist ticker per day from `option_surface_grid_daily` + `exposures_by_expiry_strike` + `daily_ohlc` + `iv_rank_history`, applies radon's gates verbatim, and writes `theta_harvester_candidates` with a Black-Scholes entry mark that is always populated. A second job re-prices those exact contracts from the same surface grid on later dates into `theta_harvester_markouts`. Live xenon/IB NBBO is fetched only for the top 8 candidates, only on explicit request, and is never the markout basis.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, FastAPI, APScheduler, Next.js 16 + React 19, Vitest, pytest.

## Global Constraints

- **`uv` only** — `uv run pytest`, never bare `pytest`/`python`/`pip`.
- **Zero UW calls in the ranking path.** All ranking inputs come from the Postgres warm store. The only network call in this feature is xenon/IB quoting, bounded per Task 9.
- **Never bulk-poll xenon/IB.** Each call spawns an IB snapshot subprocess (~2–5 s) against a shared ~100-line market-data cap. Hard ceiling: 8 candidates × 2 legs = 16 serial calls per request. Never in a scheduled job.
- **Markout basis is `entry_credit_theo`** (Black-Scholes from grid IV), never `credit_ib`. Entry and marks must both come from `option_surface_grid_daily` or every P&L carries a constant bid-ask bias that reads as alpha.
- **Radon's structural constants are ported verbatim:** `MIN_DTE=7`, `MAX_DTE=45`, `TARGET_DELTA=0.16`, `NEAR_ZERO_DELTA=0.10`, `RISK_FREE_RATE=0.045`, `TRADING_DAYS=252`. **Its score weights are NOT** — see `ScoreWeights` in Task 4. Radon's 25/25/20/15/10/5 survives as the named `RADON_WEIGHTS` sweep point so the reweight is measured, not asserted.
- **The score is a pure function of three persisted columns.** `score_from_components(iv_rv_edge, net_delta, range_score, weights)` — nothing else feeds it. That is what makes Task 12's sweep a single pass over `theta_harvester_candidates` with zero rescans and zero UW/IB calls. Any change that makes the score depend on something not stored raw on the row breaks the tuning loop and must be rejected.
- **No synthetic market data in tests.** Fixtures are real tickers at real captured prices, frozen with an as-of date. No network at test runtime. No placeholder symbols, no round-number prices. **The frozen capture is IWM, session 2026-07-24, expiry 2026-08-21**, read out of `option_wizard_local` on 2026-07-28 and pasted verbatim into the Task 3 test header with its source query. IWM is used because it is the one watchlist name that session whose real IV (0.208) actually exceeds its realised vol (HV20 0.1108). The cheap-vol negative case uses a **different real session** — QQQ 2026-07-21, IV 0.241 vs HV20 0.2557 (edge −1.47, ratio 0.943) — because no ticker on 2026-07-24 failed the IV gate. Every fixture takes all of its readings from ONE session; pairing one date's IV with another date's realised vol is a fixture that never existed. **Narrow carve-out:** the `dealer_support` and `realized_vol` unit tests use constructed numbers, because they assert pure arithmetic (does a cumulative sum cross zero; does a log-return std annualise correctly) where no market claim is made. That is the only exemption; anything asserting a price, greek, gate or verdict uses the frozen real capture.
- **Module size budget** — target <500 lines per Python file.
- **New `(ticker, as_of)` tables require** a `DatasetRegistryEntry` in `reports/data_gap_healer.py` plus a regenerated `docs/runbooks/data-gap-dataset-policy.md`, in this same PR.
- **Generated files are alphabetically frozen** — `web/lib/types.ts` and the OpenAPI snapshot get surgical additions, never a full regen.
- **CHANGELOG rides this PR** — the `[Unreleased]` entry lands on this branch before merge.
- **Never commit without explicit user request.** Steps below say "commit"; ask first if the user has not already blanket-authorised milestone commits for this plan.
- **Greek sign convention.** `option_surface_grid_daily` stores **long-contract** greeks — verified on 2026-07-24: `call_theta ∈ [-9.22, 0]`, `call_gamma ∈ [0, 4.34]`. Radon's gates (`theta > 0`, `gamma < 0`) are written for the **short position**. `select_short_strangle` is the single negation boundary; every test fixture builds legs in long convention and derives the `Strangle` through the selector. Hand-writing position-signed fixtures is what made the original draft's tests pass while `THETA_HARVEST` was unreachable in production.
- **This is a measurement artifact, not a trade proposal.** A short strangle is undefined-risk on both sides and violates argon's standing "no naked shorts / defined-risk only" rule. Nothing here sizes, proposes, or routes an order. The UI must label the tab accordingly (Task 11) and the table `COMMENT` must say so (Task 1). If this ever becomes a trade surface, the structure gains long wings and becomes an iron condor — a different plan, with different markout math.

## Interpretation constraints

These do not change what gets built; they constrain what the output may be read to mean. Record them in the docstrings named below so a later reader cannot skip them.

- **A positive markout is the null hypothesis, not a finding.** Short vol has positive expectancy in the large majority of windows — the premium is compensation for negative skew (Lempérière et al., *Risk Premia: Asymmetric Tail Risks and Excess Returns*, arXiv:1409.7720). The comparison that carries information is **`THETA_HARVEST` rows vs. the non-harvest rows in the same table**, not harvest rows vs. zero. This control arm is free: `theta_harvester_candidates` is keyed `(ticker, as_of)` with no verdict filter, so `WATCHLIST` and `DIRECTIONAL_DISGUISE` rows are persisted and marked out identically. Task 6 must NOT filter to harvest-only before upsert, and Task 8's verification must slice by verdict. **Task 12 turns this into an actual measurement**: its `unconditional` config takes every row and is the number every weighted config must beat.
- **Effective N is far below the row count.** Daily candidates on one ticker with 30-day horizons overlap ~30-fold, and 100+ tickers of short vol share one market factor. Measured on the mini (`option_wizard`) on 2026-07-29: `option_surface_grid_daily` holds **145 sessions, 2025-12-26 → 2026-07-27**, of which **116 are early enough for a 45-DTE cycle to have completed** (`market_date <= 2026-06-12`). With ~21 trading days per non-overlapping 30-day hold that is roughly **5–6 independent windows**, all inside one macro regime. Requiring `dealer_gate_critical` collapses this to **24 sessions / 2 037 (ticker, session) pairs**, because `exposures_by_expiry_strike` only begins 2026-05 — that ratio, not a prior, is why the dealer gate defaults to non-critical. Any Sharpe or t-stat on the naive row count is wrong by an order of magnitude. Report effective N alongside every aggregate.
- **The markout is a model P&L, not a tradable one.** Both ends price off grid IV, so the bias is constant in time and mostly cancels — but the absolute level omits the round-trip spread on two wing legs, which is not small on single names. It answers "does the signal separate winners from losers", never "this is what you would have made".
- **The entry mark is same-close, which is a lookahead.** `option_surface_capture` runs at 19:00 ET on session T; the scan runs at 19:45 ET and both *selects* and *prices* the entry from that same T close. So the signal consumes T's completed close, IV surface, GEX and realised vol, then assumes entry at that same close — an oracle mark no one could have transacted at. **This is a deliberate v1 simplification, and it means the output is a diagnostic, not a strategy return.** It biases results optimistically by an unknown amount: the gates select on information that is mechanically correlated with the entry price. The clean fix is to separate `signal_as_of` (T) from `entry_date` (first eligible T+1 surface) and price entry off T+1 — a schema and job change, deferred to a follow-up commit **on this branch** rather than a second PR. Until that lands, no number from this feature may be described as a strategy return, a Sharpe, or an expected credit. Say "diagnostic P&L, same-close entry" every time.
- **`credit_ib` must never be aggregated.** It exists only for the top-8 a human looked at, so any statistic over it is selection-biased. It is a per-row slippage sanity check, nothing else.
- **Directional support is thinner than the gates imply.** The IV-vs-RV gate's *direction* has real single-name evidence (Goyal & Saretto, "Cross-section of option returns and volatility", *JFE* 94:310–326, 2009 — though they use a 12-month realised-vol lookback, not radon's 20-day). The specific thresholds (5 vol points, 1.10 ratio, 0.35 range score, score ≥ 70) have **no published basis** and are ported as a baseline to be measured, not as validated parameters. Do not cite tastytrade win-rate statistics, SqueezeMetrics, or "CBOE Options Institute" figures anywhere in this feature — none of them survived source verification.
- **The score artifact is fixed, and the fix is itself a hypothesis.** Radon's score gave 40 of 100 points to terms that are constant once the critical gates pass (`dealer_support` +20 and `theta_positive` +15 are themselves critical gates; `gamma_controlled` +5 is implied by a delta-balanced short strangle), and its vol term saturated at 10 vol points of IV-RV, which rich-vol names routinely clear. So the "100-point" score really discriminated over ~55 points, and the vol edge — the one component with published directional support — was often pinned at its cap. `ScoreWeights` scores only the three varying components (vol 55 / delta 25 / range 20) and saturates the vol term at 15 vol points — p90 of the measured edge distribution, not a guess. **This is an improvement in construction, not a validated calibration.** Task 12 sweeps it against `RADON_WEIGHTS` and against an unconditional baseline; if neither beats the baseline OOS, the honest conclusion is that the score adds nothing and the feature stays a diagnostic.
- **Weight provenance is persisted.** `theta_harvester_candidates.weights_version` records which `ScoreWeights` produced the stored `score`, so a weight change does not silently make historical rows incomparable. The raw components are stored too, so any row can be re-scored under any weights without a rescan.
- **IV comes from the grid, not `iv_rank_history`.** Changed 2026-07-29 after the first real scan run. `iv_rank_history` holds only **4 tickers per session** — on `option_wizard` as well as local — and the natural `market_date <= as_of ORDER BY DESC LIMIT 1` lookup silently returns a months-old reading for everything else: of the 114 grid tickers on 2026-07-24, **3 had same-day IV, 85 were stale by more than a week, and 26 had never been captured**. May IV against July realised vol, no error, no log line. `load_atm_iv` reads the nearest-to-spot strike on the SAME `(market_date, expiry)` the legs came from — 114/114 coverage, staleness structurally impossible — and cross-checks to 0.20592 vs `iv_rank_history`'s 0.208 on IWM, the one ticker where both exist. Real-run effect: candidates written went 88 → 109 and all three verdicts appear.
- **Two persisted-but-unconsumed fields are intentional.** `hv60` and `vega` are computed and stored but appear in no gate or score term. Note the ATM-vs-16Δ tenor caveat still applies: `iv` is the ATM reading while the traded legs sit at ~16Δ where skew makes put IV materially higher. All three are recorded so the first markout read can answer "was the 20-day lookback wrong", "did vol expansion or spot drift do the damage", and "does ATM IV misstate this structure's edge" without a re-backfill. **None may be quietly wired into a gate during implementation** — that would change the signal being measured mid-experiment. They are diagnostics, not inputs.

## Data Sources (verified 2026-07-28 against `option_wizard_local`)

| Table | Key | Provides | Coverage (local) |
|---|---|---|---|
| `option_surface_grid_daily` | `(ticker, market_date, expiry, strike)` | `call_iv`/`put_iv`, `call_delta`/`put_delta`, `call_gamma`/`put_gamma`, `call_vega`/`put_vega`, `call_theta`/`put_theta`, `underlying_spot` | 2026-01-02 → 07-24, 5.17M rows, 109 tickers/day |
| `exposures_by_expiry_strike` | `(run_id, ticker, expiry, strike)` | `call_gex`, `put_gex`, `market_date` | 2026-05-11 → 07-28, 2.47M rows, 124 tickers |
| `daily_ohlc` | `(ticker, date)` | `close` | deep |
| `iv_rank_history` | `(ticker, market_date)` | `volatility` (current IV), `iv_rank_1y` | deep |
| `watchlist` | `ticker` | universe; `removed_at IS NULL` = active | — |

**Binding constraint:** `exposures_by_expiry_strike` starts 2026-05-11, so historical replay reaches ~55 trading days, not the seven months the IV grid alone would allow. The dealer-support gate is what limits it.

**Durability caveat:** `exposures_by_expiry_strike.run_id` is `REFERENCES scan_runs(run_id) ON DELETE CASCADE` — unlike `option_surface_grid_daily`, which is deliberately `run_id`-free as a permanent archive. If `scan_runs` is ever pruned, historical dealer-support inputs vanish and the backfill becomes unreproducible. Record this in the candidate row: persist `net_gex` and `gex_flip` as **values**, not as a join to be re-derived later.

## File Structure

**Create:**
- `src/uw_scan/storage/migrations/109_theta_harvester.sql` — two tables
- `src/uw_scan/scanners/theta_harvester.py` (~280) — pure compute: no DB, no I/O
- `src/uw_scan/storage/theta_harvester_repository.py` (~200) — loader queries + upserts + reads
- `src/uw_scan/reports/theta_harvester_markout.py` (~150) — re-mark compute
- `src/uw_scan/worker/jobs/theta_harvester.py` (~70) — two thin job wrappers
- `scripts/backfill/theta_harvester_backfill.py` (~120) — historical replay
- `src/uw_scan/api/models/theta_harvester.py` (~80) — response models
- `web/app/scanner/[[...tab]]/page.tsx` — replaces `web/app/scanner/page.tsx`
- `web/components/scanner/ScannerPanel.tsx` (~90) — client tab strip
- `web/components/scanner/FlowSubTab.tsx` — today's scanner body, moved
- `web/components/scanner/theta/ThetaSubTab.tsx` (~180) — table + rescan + quote
- `tests/unit/scanners/test_theta_harvester.py`
- `tests/unit/reports/test_theta_harvester_markout.py`
- `tests/integration/test_theta_harvester_repository.py`
(No separate fixture JSON: the frozen real IWM capture is inlined as module
constants at the top of `tests/unit/scanners/test_theta_harvester.py`, with its
source query in the header comment. A four-leg capture does not justify a file,
and an unreferenced fixture path in this list was a leftover from an earlier
draft — do not create one.)
- `web/tests/unit/thetaSubTab.test.tsx`

**Modify:**
- `src/uw_scan/reports/data_gap_healer.py` — two `DatasetRegistryEntry` additions
- `docs/runbooks/data-gap-dataset-policy.md` — regenerated
- `src/uw_scan/api/routers/scanner.py` — three endpoints
- `src/uw_scan/worker/scheduler.py` — two cron registrations
- `src/uw_scan/config.py` — one feature flag
- `web/lib/api.ts`, `web/lib/types.ts` — surgical additions
- `CHANGELOG.md`

---

### Task 1: Schema + dataset registry

**Files:**
- Create: `src/uw_scan/storage/migrations/109_theta_harvester.sql`
- Modify: `src/uw_scan/reports/data_gap_healer.py` (REGISTRY list, near the `option_surface_grid_daily` entry ~line 148)
- Modify: `docs/runbooks/data-gap-dataset-policy.md` (regenerated, not hand-edited)

**Interfaces:**
- Consumes: nothing.
- Produces: tables `uw_scan.theta_harvester_candidates` and `uw_scan.theta_harvester_markouts` with the columns below. Every later task depends on these exact names.

- [ ] **Step 1: Write the migration**

```sql
-- 109_theta_harvester.sql — Theta Harvester candidates + forward markouts.
-- Idempotent. No run_id FK by design: these are derived analytics that must
-- outlive scan_runs pruning (exposures_by_expiry_strike does NOT, which is why
-- net_gex/gex_flip are persisted as values here rather than re-derived later).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.theta_harvester_candidates (
    ticker            TEXT NOT NULL,
    as_of             DATE NOT NULL,
    -- contract identity: re-markable from option_surface_grid_daily until expiry
    expiry            DATE NOT NULL,
    dte               INTEGER NOT NULL,
    put_strike        NUMERIC NOT NULL,
    call_strike       NUMERIC NOT NULL,
    -- entry state
    underlying_spot   NUMERIC NOT NULL,
    put_iv            NUMERIC NOT NULL,
    call_iv           NUMERIC NOT NULL,
    risk_free_rate    NUMERIC NOT NULL,
    -- entry mark (ALWAYS populated; the markout basis)
    put_mark          NUMERIC NOT NULL,
    call_mark         NUMERIC NOT NULL,
    entry_credit_theo NUMERIC NOT NULL,
    -- live IB quote (nullable; top-8-on-view only; slippage check, never the basis)
    credit_ib         NUMERIC,
    credit_quoted_at  TIMESTAMPTZ,
    credit_source     TEXT,
    -- structure greeks
    net_delta         NUMERIC NOT NULL,
    theta             NUMERIC NOT NULL,
    gamma             NUMERIC NOT NULL,
    vega              NUMERIC NOT NULL,
    -- signal
    score             NUMERIC NOT NULL,
    -- which ScoreWeights produced `score`. Re-scoring off the raw components
    -- below is always allowed; comparing stored scores across versions is not.
    weights_version   TEXT NOT NULL,
    verdict           TEXT NOT NULL,
    iv                NUMERIC,
    hv20              NUMERIC,
    hv60              NUMERIC,
    iv_rv_edge        NUMERIC,
    iv_rv_ratio       NUMERIC,
    trend_20d_pct     NUMERIC,
    range_score       NUMERIC,
    dealer_support    TEXT,
    net_gex           NUMERIC,
    gex_flip          NUMERIC,
    -- six gates, stored as columns so they are queryable without JSONB extraction
    gate_delta_near_zero  BOOLEAN NOT NULL,
    gate_iv_rich_vs_rv    BOOLEAN NOT NULL,
    gate_dealer_support   BOOLEAN NOT NULL,
    gate_theta_positive   BOOLEAN NOT NULL,
    gate_gamma_controlled BOOLEAN NOT NULL,
    gate_range_bound      BOOLEAN NOT NULL,
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);

CREATE INDEX IF NOT EXISTS ix_theta_harvester_candidates_asof
  ON uw_scan.theta_harvester_candidates (as_of DESC, score DESC);

COMMENT ON TABLE uw_scan.theta_harvester_candidates IS
  'RESEARCH MEASUREMENT ARTIFACT, NOT A TRADE PROPOSAL. A short strangle is undefined-risk on both sides and violates argon''s no-naked-shorts rule; nothing sizes or routes from this table. One best short strangle per watchlist ticker per session, ranked from the warm store at zero UW cost. Rows of EVERY verdict are persisted deliberately — the non-THETA_HARVEST rows are the control arm, and short vol is positive-expectancy in most windows, so harvest-vs-zero is uninformative while harvest-vs-control is not. entry_credit_theo is the Black-Scholes mark from option_surface_grid_daily IV and is the ONLY valid markout basis; credit_ib is an opportunistic live NBBO for the top candidates, is selection-biased by which rows a human looked at, and must never be aggregated.';

CREATE TABLE IF NOT EXISTS uw_scan.theta_harvester_markouts (
    ticker         TEXT NOT NULL,
    as_of          DATE NOT NULL,
    horizon_days   INTEGER NOT NULL,
    mark_date      DATE NOT NULL,
    spot           NUMERIC,
    put_iv         NUMERIC,
    call_iv        NUMERIC,
    put_mark       NUMERIC,
    call_mark      NUMERIC,
    position_value NUMERIC,
    pnl            NUMERIC,
    pnl_pct_of_credit NUMERIC,
    breached       BOOLEAN,
    expired        BOOLEAN NOT NULL DEFAULT FALSE,
    inserted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of, horizon_days)
);

CREATE INDEX IF NOT EXISTS ix_theta_harvester_markouts_horizon
  ON uw_scan.theta_harvester_markouts (horizon_days, as_of DESC);

COMMENT ON TABLE uw_scan.theta_harvester_markouts IS
  'Forward re-marks of theta_harvester_candidates contracts, priced from option_surface_grid_daily on later dates. pnl is entry_credit_theo minus position_value (short strangle: positive = the credit was kept). horizon_days > 0 are intermediate marks and still carry time value; horizon_days = -1 is the TERMINAL at-expiry settlement mark, priced as intrinsic from daily_ohlc (the contract has left the option chain by then) and is the only row that observes the strategy''s realised risk. Aggregate the terminal row separately: averaging it together with intermediate horizons mixes two different quantities.';

COMMENT ON COLUMN uw_scan.theta_harvester_markouts.mark_date IS
  'The session actually priced, which may be later than as_of + horizon_days when the horizon lands on a weekend or a missed capture. Never the requested calendar date.';
```

- [ ] **Step 2: Apply the migration**

Run: `bash scripts/migrate.sh`
Expected: exits 0. Re-run it a second time; it must also exit 0 (idempotence).

- [ ] **Step 3: Verify the tables exist**

Run:
```bash
uv run python -c "
from uw_scan.config import Settings
import psycopg
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c:
    for t in ('theta_harvester_candidates', 'theta_harvester_markouts'):
        print(t, c.execute(f'select count(*) from uw_scan.{t}').fetchone())
"
```
Expected: both print `(0,)`.

- [ ] **Step 4: Add the dataset registry entries**

In `src/uw_scan/reports/data_gap_healer.py`, add to the `REGISTRY` list next to the other derived datasets:

```python
    DatasetRegistryEntry(
        "theta_harvester_candidates",
        "derived_analytics",
        # research_artifact, NOT strict_ticker_date. strict_ticker_date sets the
        # denominator to (eligible watchlist tickers x sessions), but candidates
        # only exist from the GEX floor (2026-05-11) and only for tickers that
        # clear the thin-input checks — so it would report a large, permanent,
        # UNHEALABLE gap (healer_adapter is None) on every audit forever.
        "research_artifact",
        date_col="as_of",
        ticker_col="ticker",
        provider="db",
        granularity="run_once_lookback",
        healer_adapter=None,
        source_system="derived",
        reason=(
            "Derived from option_surface_grid_daily + exposures_by_expiry_strike; "
            "heal by re-running scripts/backfill/theta_harvester_backfill.py. "
            "Coverage floor is exposures_by_expiry_strike (2026-05-11), not the IV grid. "
            "Rows are absent by design for tickers with thin price history or no chain."
        ),
    ),
    DatasetRegistryEntry(
        "theta_harvester_markouts",
        "derived_analytics",
        "freshness_only",
        date_col="as_of",
        ticker_col="ticker",
        provider="db",
        granularity="run_once",
        healer_adapter=None,
        source_system="derived",
        reason=(
            "Forward re-marks accrue as sessions pass; a missing horizon is "
            "not-yet-reached rather than a gap. Scored by the nightly markout job."
        ),
    ),
```

- [ ] **Step 5: Regenerate the policy doc**

Run:
```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; \
open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
```
The function is `render_dataset_policy_markdown` — verified at
`src/uw_scan/reports/data_gap_healer.py:998` and used under that name by
`tests/unit/reports/test_data_gap_dataset_policy.py:18`. There is no
`render_dataset_policy_doc`.

- [ ] **Step 6: Run the policy gate**

Run: `uv run pytest tests/unit/reports/test_data_gap_dataset_policy.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/storage/migrations/109_theta_harvester.sql \
        src/uw_scan/reports/data_gap_healer.py \
        docs/runbooks/data-gap-dataset-policy.md
git commit -m "feat(theta): add theta_harvester candidate + markout tables"
```

---

### Task 2: Pure compute — vol, range, dealer support

**Files:**
- Create: `src/uw_scan/scanners/theta_harvester.py`
- Test: `tests/unit/scanners/test_theta_harvester.py`

**Interfaces:**
- Consumes: `uw_scan.reports.vrp_structure.bs_price(S, K, T, r, sigma, *, is_call) -> float`.
- Produces:
  - `realized_vol(closes: Sequence[float], window: int) -> float | None`
  - `range_metrics(closes: Sequence[float], hv20: float) -> tuple[float, float] | None` → `(trend_20d_pct, range_score)`, or `None` when fewer than 22 closes
  - `dealer_support(gex_rows: Sequence[Mapping[str, Any]], spot: float) -> DealerSupport`
  - `DealerSupport` frozen dataclass: `label: str`, `net_gex: float | None`, `gex_flip: float | None`
  - Module constants `MIN_DTE`, `MAX_DTE`, `TARGET_DELTA`, `NEAR_ZERO_DELTA`, `RISK_FREE_RATE`, `TRADING_DAYS`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/scanners/test_theta_harvester.py
"""Theta Harvester pure compute. Constants ported verbatim from radon's
scripts/theta_harvester_scanner.py — see docs/research/2026-07-28-radon-scanner-port-backlog.md."""

import math

import pytest

from uw_scan.scanners.theta_harvester import (
    DealerSupport,
    dealer_support,
    range_metrics,
    realized_vol,
)


def test_realized_vol_matches_hand_computed_annualised_sigma():
    # Deterministic alternating 1% moves: daily log-return std is exactly
    # 0.01*ln-ish, so annualised vol = std(log returns) * sqrt(252).
    closes = [100.0]
    for i in range(20):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    expected = math.sqrt(var) * math.sqrt(252)
    assert realized_vol(closes, 20) == pytest.approx(expected, rel=1e-9)


def test_realized_vol_returns_none_when_window_not_covered():
    assert realized_vol([100.0, 101.0], 20) is None


def test_range_metrics_flat_tape_scores_fully_range_bound():
    # No drift over 21 sessions -> trend 0 -> range_score clamps to 1.0.
    closes = [100.0] * 22
    trend, score = range_metrics(closes, hv20=0.25)
    assert trend == pytest.approx(0.0)
    assert score == pytest.approx(1.0)


def test_range_metrics_strong_trend_scores_zero():
    # +40% over 21 sessions dwarfs a 25%-vol 21-day expected move -> clamps to 0.
    closes = [100.0 * (1.0165**i) for i in range(22)]
    trend, score = range_metrics(closes, hv20=0.25)
    assert trend > 30.0
    assert score == pytest.approx(0.0)


def test_range_metrics_expected_move_uses_the_same_21_sessions_as_the_trend():
    # The expected move must be scaled over 21 sessions, matching closes[-22].
    # A 20-session scaling understates it by ~2.5% and tightens the gate.
    closes = [100.0] * 21 + [105.0]
    _, score = range_metrics(closes, hv20=0.25)
    expected_pct = 0.25 * math.sqrt(21.0 / 252) * 100.0
    assert score == pytest.approx(1.0 - 5.0 / (expected_pct * 1.25))


def test_range_metrics_returns_none_on_thin_history():
    # Must NOT return (0.0, 0.0): score 0.0 means "violently trending", so
    # encoding "unknown" that way silently fails the range gate on new listings.
    assert range_metrics([100.0] * 10, hv20=0.25) is None


def test_dealer_support_flags_support_above_positive_gex_flip():
    # Net GEX turns negative->positive at 95; spot 100 sits above the flip and
    # total net GEX is positive -> dealers are long gamma and damping moves.
    rows = [
        {"strike": 90.0, "call_gex": 1.0e8, "put_gex": -3.0e8},
        {"strike": 95.0, "call_gex": 4.0e8, "put_gex": -1.0e8},
        {"strike": 105.0, "call_gex": 5.0e8, "put_gex": -1.0e8},
    ]
    out = dealer_support(rows, spot=100.0)
    assert out == DealerSupport(label="SUPPORT", net_gex=5.0e8, gex_flip=95.0)


def test_dealer_support_flags_no_support_when_net_gex_negative():
    rows = [
        {"strike": 95.0, "call_gex": 1.0e8, "put_gex": -5.0e8},
        {"strike": 105.0, "call_gex": 1.0e8, "put_gex": -2.0e8},
    ]
    assert dealer_support(rows, spot=100.0).label == "NO_SUPPORT"


def test_dealer_support_holds_when_cumulative_gex_never_turns_negative():
    # Dealers long gamma at every strike: cumulative net GEX never crosses
    # zero, so there is no flip. Radon keyed SUPPORT on `flip is not None` and
    # therefore returned NO_SUPPORT here — a false negative on exactly the most
    # unambiguously dealer-long names.
    rows = [
        {"strike": 95.0, "call_gex": 2.0e8, "put_gex": -1.0e8},
        {"strike": 105.0, "call_gex": 3.0e8, "put_gex": -1.0e8},
    ]
    out = dealer_support(rows, spot=100.0)
    assert out.label == "SUPPORT"
    assert out.gex_flip is None
    assert out.net_gex == pytest.approx(3.0e8)


def test_dealer_support_unknown_without_rows():
    out = dealer_support([], spot=100.0)
    assert out == DealerSupport(label="UNKNOWN", net_gex=None, gex_flip=None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.scanners.theta_harvester'`

- [ ] **Step 3: Write the implementation**

```python
# src/uw_scan/scanners/theta_harvester.py
"""Theta Harvester — short-strangle candidate finder over the warm store.

Ported from radon's scripts/theta_harvester_scanner.py. Gates, weights and
thresholds are verbatim: they are unvalidated heuristics, but radon persisted
only a JSON blob per scan and so could never score them. Argon persists
per-candidate rows plus forward markouts, which is what makes recalibration
possible later — see docs/research/2026-07-28-radon-scanner-port-backlog.md.

Pure compute: no DB, no I/O, no network. The repository layer feeds it rows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MIN_DTE = 7
MAX_DTE = 45
TARGET_DELTA = 0.16
NEAR_ZERO_DELTA = 0.10
RISK_FREE_RATE = 0.045  # ponytail: flat constant, as radon. Wire rates_repository
                        # only if a markout shows term-structure sensitivity.
TRADING_DAYS = 252


@dataclass(frozen=True)
class DealerSupport:
    """Where dealer gamma flips sign, and whether spot sits on the calm side."""

    label: str  # "SUPPORT" | "NO_SUPPORT" | "UNKNOWN"
    net_gex: float | None
    gex_flip: float | None


def realized_vol(closes: Sequence[float], window: int) -> float | None:
    """Annualised realised vol from the last `window` log returns.

    Returns None when there are not enough closes to fill the window — a
    partial window would understate vol and silently loosen the IV-edge gate.
    """
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1) :]
    rets = [
        # strict=False is load-bearing: tail[1:] is one shorter BY DESIGN
        # (n closes -> n-1 returns). strict=True raises on every call.
        math.log(b / a)
        for a, b in zip(tail, tail[1:], strict=False)
        if a > 0 and b > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def range_metrics(
    closes: Sequence[float], hv20: float
) -> tuple[float, float] | None:
    """(21-session pct change, range_score in [0,1]), or None on thin history.

    range_score compares realised drift against the move HV20 implies over the
    SAME 21 sessions. Drift well inside that band -> range-bound -> good
    strangle tape.

    Returns None rather than (0.0, 0.0) when history is short: range_score 0.0
    means "violently trending", and encoding "unknown" as the worst possible
    score would silently fail the range gate on every newly-listed ticker.
    """
    if len(closes) < 22 or closes[-22] <= 0:
        return None
    trend_pct = (closes[-1] / closes[-22] - 1.0) * 100.0
    # 21 sessions, matching the trend window above — not 20. Using 20 here
    # understated the expected move by ~2.5% and silently tightened the gate.
    expected_pct = hv20 * math.sqrt(21.0 / TRADING_DAYS) * 100.0
    if expected_pct <= 0:
        return trend_pct, 0.0
    score = 1.0 - abs(trend_pct) / (expected_pct * 1.25)
    return trend_pct, max(0.0, min(1.0, score))


def dealer_support(
    gex_rows: Sequence[Mapping[str, object]], spot: float
) -> DealerSupport:
    """Locate the gamma flip and decide whether dealers damp or amplify moves.

    Sums call_gex+put_gex per strike, finds the highest strike at or below spot
    where cumulative net GEX crosses negative -> positive, and flags SUPPORT
    when total net GEX is positive AND spot is at or above that flip.
    """
    per_strike: dict[float, float] = {}
    for row in gex_rows:
        try:
            strike = float(row["strike"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            continue
        call = float(row.get("call_gex") or 0.0)  # type: ignore[union-attr]
        put = float(row.get("put_gex") or 0.0)  # type: ignore[union-attr]
        per_strike[strike] = per_strike.get(strike, 0.0) + call + put
    if not per_strike:
        return DealerSupport(label="UNKNOWN", net_gex=None, gex_flip=None)

    total = sum(per_strike.values())
    flip: float | None = None
    cumulative = 0.0
    crossed_negative = False
    for strike in sorted(per_strike):
        prev = cumulative
        cumulative += per_strike[strike]
        if prev < 0:
            crossed_negative = True
        if prev < 0 <= cumulative and strike <= spot:
            flip = strike

    # No crossing at all means cumulative net GEX never went negative, i.e.
    # dealers are long gamma across the whole strike ladder. Radon labelled
    # that NO_SUPPORT because it keyed on `flip is not None` — a false negative
    # on exactly the most unambiguously dealer-long names. Treat "never
    # negative AND total > 0" as SUPPORT with a null flip.
    if total <= 0:
        label = "NO_SUPPORT"
    elif flip is not None:
        label = "SUPPORT" if spot >= flip else "NO_SUPPORT"
    else:
        label = "NO_SUPPORT" if crossed_negative else "SUPPORT"
    return DealerSupport(label=label, net_gex=total, gex_flip=flip)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -v`
Expected: all 10 PASS.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/uw_scan/scanners/theta_harvester.py tests/unit/scanners/test_theta_harvester.py && uv run ruff format --check src/uw_scan/scanners/theta_harvester.py`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/scanners/theta_harvester.py tests/unit/scanners/test_theta_harvester.py
git commit -m "feat(theta): vol, range and dealer-support primitives"
```

---

### Task 3: Pure compute — leg selection

**Files:**
- Modify: `src/uw_scan/scanners/theta_harvester.py`
- Test: `tests/unit/scanners/test_theta_harvester.py`

**Interfaces:**
- Consumes: Task 2's constants.
- Produces:
  - `OptionLeg` frozen dataclass: `expiry: date`, `strike: float`, `right: str`, `iv: float`, `delta: float`, `theta: float`, `gamma: float`, `vega: float`
  - `Strangle` frozen dataclass: `expiry: date`, `dte: int`, `put: OptionLeg`, `call: OptionLeg`, `net_delta: float`, `theta: float`, `gamma: float`, `vega: float`
  - `select_short_strangle(legs: Sequence[OptionLeg], spot: float, as_of: date, *, min_dte: int = MIN_DTE, max_dte: int = MAX_DTE) -> Strangle | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/scanners/test_theta_harvester.py`:

```python
from datetime import date

from uw_scan.scanners.theta_harvester import (
    OptionLeg,
    Strangle,
    select_short_strangle,
)

# ---------------------------------------------------------------------------
# FROZEN REAL CAPTURE — IWM, session 2026-07-24, expiry 2026-08-21 (28 DTE).
# Every number below was read out of option_wizard_local's
# option_surface_grid_daily / daily_ohlc / iv_rank_history on 2026-07-28 and
# pasted verbatim. Nothing here is invented, rounded, or a placeholder symbol.
# Re-derive with:
#   select strike, call_iv, call_delta, call_theta, call_gamma, call_vega
#     from uw_scan.option_surface_grid_daily
#    where ticker='IWM' and market_date='2026-07-24' and expiry='2026-08-21';
#
# IWM was chosen because it is the one watchlist name on that session whose
# real IV actually exceeds its realised vol (edge +9.72 vol points) — i.e. the
# only ticker for which the gates genuinely pass on real data. AAPL, the
# only ticker for which the gates genuinely pass on real data. The cheap-vol
# negative case uses a different real session (QQQ 2026-07-21), because no
# ticker on 2026-07-24 failed the IV gate.
# ---------------------------------------------------------------------------
_AS_OF = date(2026, 7, 24)
_EXP = date(2026, 8, 21)  # 28 DTE — closest to radon's 30-day preference
_SPOT = 291.44            # option_surface_grid_daily.underlying_spot
_IV = 0.208               # iv_rank_history.volatility
_HV20 = 0.1107879091536324
_HV60 = 0.18596313086572983
_TREND_21D = -1.8605278236543121
_RANGE_SCORE = 0.5346021068062862

# The real ~16-delta wings — the pair radon's selector targets.
_PUT_16D = OptionLeg(_EXP, 272.0, "P", 0.251489543772415, -0.154573982720319,
                     -0.0861128240264245, 0.0117240381034907, 0.191878725809937)
_CALL_16D = OptionLeg(_EXP, 306.0, "C", 0.172509740706994, 0.156401472783266,
                      -0.0595290822132382, 0.0172246813925854, 0.193372401778545)
# The real ~30-delta pair, used to prove the selector prefers the 16-delta one.
_PUT_30D = OptionLeg(_EXP, 284.0, "P", 0.218730053018397, -0.327454819434478,
                     -0.113677825209739, 0.0204601161742457, 0.291236782959359)
_CALL_30D = OptionLeg(_EXP, 300.0, "C", 0.187568622934882, 0.293516725982416,
                      -0.0929495970921554, 0.0227497373480449, 0.277693841589617)


def _leg(strike, right, delta, *, expiry=_EXP, theta=-0.0595290822132382):
    """A LONG contract in argon's stored convention.

    Used ONLY for the delta-band / DTE-window / straddle-spot rejection tests,
    which exercise pure predicates where the greek magnitudes are irrelevant —
    the deltas are the input under test. Anything asserting on pricing, greeks
    or gates uses the frozen real legs above instead.

    option_surface_grid_daily holds long-contract greeks — verified on
    2026-07-24: call_theta in [-9.22, 0], call_gamma in [0, 4.34]. Every
    fixture in this file must use those signs, or the tests will validate a
    convention production never sees.
    """
    return OptionLeg(
        expiry=expiry,
        strike=strike,
        right=right,
        iv=0.172509740706994,
        delta=delta,
        theta=theta,                  # <= 0: long option decays
        gamma=0.0172246813925854,     # >= 0: long option is convex
        vega=0.193372401778545,       # >= 0: long option is long vol
    )


def test_selected_strangle_carries_short_position_greek_signs():
    # THE regression guard for this port, on the real IWM 2026-07-24 capture.
    # Grid legs are long-convention, the position is short, so Strangle must
    # flip every greek. Without this, gates["theta_positive"] is False for
    # every row ever scanned and the THETA_HARVEST verdict is unreachable in
    # production while the tests still pass.
    out = select_short_strangle([_PUT_16D, _CALL_16D], spot=_SPOT, as_of=_AS_OF)
    assert out is not None
    assert out.theta == pytest.approx(0.145641906239663)
    assert out.gamma == pytest.approx(-0.028948719496076)
    assert out.vega == pytest.approx(-0.385251127588482)
    assert out.net_delta == pytest.approx(-0.001827490062947)
    assert out.theta > 0 and out.gamma < 0 and out.vega < 0


def test_select_short_strangle_prefers_legs_nearest_target_delta():
    # Both real pairs from the same real expiry: ~16-delta (radon's target) and
    # ~30-delta. The 16-delta pair wins on the selection score.
    out = select_short_strangle(
        [_PUT_16D, _CALL_16D, _PUT_30D, _CALL_30D], spot=_SPOT, as_of=_AS_OF
    )
    assert isinstance(out, Strangle)
    assert (out.put.strike, out.call.strike) == (272.0, 306.0)
    assert out.dte == 28


def test_select_short_strangle_rejects_legs_outside_dte_window():
    too_soon = date(2026, 7, 27)  # 3 DTE, under MIN_DTE=7
    legs = [
        _leg(272.0, "P", -0.154573982720319, expiry=too_soon),
        _leg(306.0, "C", 0.156401472783266, expiry=too_soon),
    ]
    assert select_short_strangle(legs, spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_rejects_legs_outside_delta_band():
    # 0.45 delta is above radon's 0.35 candidate ceiling; 0.02 is below the
    # 0.05 floor. Neither side yields a usable candidate.
    legs = [_leg(288.0, "P", -0.45), _leg(340.0, "C", 0.02)]
    assert select_short_strangle(legs, spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_requires_strikes_to_straddle_spot():
    # Both legs OTM on the same side -> not a strangle.
    legs = [_leg(300.0, "P", -0.154573982720319), _leg(306.0, "C", 0.156401472783266)]
    assert select_short_strangle(legs, spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_will_not_pair_across_expiries():
    import dataclasses as _dc

    other = _dc.replace(_CALL_16D, expiry=date(2026, 9, 18))
    assert select_short_strangle([_PUT_16D, other], spot=_SPOT, as_of=_AS_OF) is None


def test_select_short_strangle_breaks_ties_deterministically():
    # Two pairs with identical selection scores must resolve the same way on
    # every run and every row ordering — otherwise a rescan can silently swap
    # the persisted contract and orphan its own markouts.
    import dataclasses as _dc

    alt_put = _dc.replace(_PUT_16D, strike=271.0)
    alt_call = _dc.replace(_CALL_16D, strike=307.0)
    forward = select_short_strangle(
        [_PUT_16D, _CALL_16D, alt_put, alt_call], spot=_SPOT, as_of=_AS_OF
    )
    reverse = select_short_strangle(
        [alt_call, alt_put, _CALL_16D, _PUT_16D], spot=_SPOT, as_of=_AS_OF
    )
    assert forward is not None and reverse is not None
    assert (forward.put.strike, forward.call.strike) == (
        reverse.put.strike,
        reverse.call.strike,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -k strangle -v`
Expected: FAIL — `ImportError: cannot import name 'OptionLeg'`

- [ ] **Step 3: Write the implementation**

Append to `src/uw_scan/scanners/theta_harvester.py` (add `from datetime import date` to imports):

```python
@dataclass(frozen=True)
class OptionLeg:
    expiry: date
    strike: float
    right: str  # "C" | "P"
    iv: float
    delta: float
    theta: float
    gamma: float
    vega: float


@dataclass(frozen=True)
class Strangle:
    """A SHORT strangle. Greeks are POSITION-signed, not contract-signed.

    OptionLeg carries argon's stored convention (long contract: theta <= 0,
    gamma >= 0, vega >= 0 — verified against option_surface_grid_daily). Being
    short flips all of them, so for a healthy candidate:
        theta > 0  (decay accrues to us)
        gamma < 0  (we are short convexity)
        vega  < 0  (we are short vol)
    Radon's gates are written against these position signs; passing the raw
    long-contract greeks through would make `theta > 0` unsatisfiable and
    render the THETA_HARVEST verdict unreachable.
    """

    expiry: date
    dte: int
    put: OptionLeg
    call: OptionLeg
    net_delta: float
    theta: float
    gamma: float
    vega: float


def select_short_strangle(
    legs: Sequence[OptionLeg],
    spot: float,
    as_of: date,
    *,
    min_dte: int = MIN_DTE,
    max_dte: int = MAX_DTE,
) -> Strangle | None:
    """Cheapest-scoring OTM short strangle within the DTE window.

    Radon's selection score, verbatim: delta neutrality dominates, each leg is
    pulled toward TARGET_DELTA, ~30 DTE is mildly preferred, and a
    non-positive-theta pair is heavily penalised. Lower is better.

    `legs` carry argon's stored LONG-contract greeks; the returned Strangle
    carries SHORT-position greeks. The negation happens here, at the single
    boundary between storage convention and radon's gate convention.
    """
    calls: list[OptionLeg] = []
    puts: list[OptionLeg] = []
    for leg in legs:
        dte = (leg.expiry - as_of).days
        if not (min_dte <= dte <= max_dte):
            continue
        mag = abs(leg.delta)
        if not (0.05 <= mag <= 0.35):
            continue
        if leg.right == "C" and leg.strike > spot:
            calls.append(leg)
        elif leg.right == "P" and leg.strike < spot:
            puts.append(leg)

    best: Strangle | None = None
    best_key: tuple[float, date, float, float] | None = None
    for call in calls:
        for put in puts:
            if call.expiry != put.expiry:
                continue
            dte = (call.expiry - as_of).days
            # Negate: legs are long-contract, the position is short.
            net_delta = -(call.delta + put.delta)
            theta = -(call.theta + put.theta)
            gamma = -(call.gamma + put.gamma)
            vega = -(call.vega + put.vega)
            score = (
                abs(net_delta) * 100
                + abs(abs(call.delta) - TARGET_DELTA) * 20
                + abs(abs(put.delta) - TARGET_DELTA) * 20
                + abs(dte - 30) / 10
                + (0 if theta > 0 else 20)
            )
            # Strict `<` alone leaves ties resolved by row arrival order, which
            # Postgres does not guarantee — the same session could pick a
            # different structure on a rescan and invalidate its own markouts.
            # Break ties deterministically on the contract identity itself.
            key = (score, call.expiry, put.strike, call.strike)
            if best_key is None or key < best_key:
                best_key = key
                best = Strangle(
                    expiry=call.expiry,
                    dte=dte,
                    put=put,
                    call=call,
                    net_delta=net_delta,
                    theta=theta,
                    gamma=gamma,
                    vega=vega,
                )
    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -v`
Expected: all 16 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/scanners/theta_harvester.py tests/unit/scanners/test_theta_harvester.py
git commit -m "feat(theta): short-strangle leg selection"
```

---

### Task 4: Pure compute — scoring, gates, entry mark

**Files:**
- Modify: `src/uw_scan/scanners/theta_harvester.py`
- Test: `tests/unit/scanners/test_theta_harvester.py`

**Interfaces:**
- Consumes: Tasks 2–3; `bs_price` from `uw_scan.reports.vrp_structure`.
- Produces:
  - `ThetaCandidate` frozen dataclass with fields: `ticker: str`, `as_of: date`, `structure: Strangle`, `spot: float`, `iv: float`, `hv20: float`, `hv60: float | None`, `iv_rv_edge: float`, `iv_rv_ratio: float`, `trend_20d_pct: float`, `range_score: float`, `dealer: DealerSupport`, `score: float`, `weights_version: str`, `verdict: str`, `gates: dict[str, bool]`, `put_mark: float`, `call_mark: float`, `entry_credit_theo: float`, `risk_free_rate: float`
  - `build_candidate(*, ticker: str, as_of: date, structure: Strangle, spot: float, iv: float, hv20: float, hv60: float | None, trend_20d_pct: float, range_score: float, dealer: DealerSupport, r: float = RISK_FREE_RATE) -> ThetaCandidate`
  - Gate key names, exact: `"delta_near_zero"`, `"iv_rich_vs_rv"`, `"dealer_support"`, `"theta_positive"`, `"gamma_controlled"`, `"range_bound"`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/scanners/test_theta_harvester.py`:

```python
import dataclasses

from uw_scan.scanners.theta_harvester import (
    DEFAULT_WEIGHTS,
    RADON_WEIGHTS,
    ThetaCandidate,
    build_candidate,
)


def _structure(**over):
    """Build through select_short_strangle so the sign convention cannot drift.

    Hand-constructing Strangle(...) here is what let the original draft ship a
    short-convention fixture (theta=+0.08) against a long-convention selector:
    the tests passed and production produced zero THETA_HARVEST rows. Always
    derive from _leg() via the selector, then override only the field a given
    test is actually exercising.
    """
    base = select_short_strangle([_PUT_16D, _CALL_16D], spot=_SPOT, as_of=_AS_OF)
    assert base is not None and base.theta > 0 and base.gamma < 0
    return dataclasses.replace(base, **over) if over else base


def _candidate(**over):
    """The real IWM 2026-07-24 candidate. Every gate passes on real data."""
    kwargs = dict(
        ticker="IWM", as_of=_AS_OF, structure=_structure(), spot=_SPOT,
        iv=_IV, hv20=_HV20, hv60=_HV60, trend_20d_pct=_TREND_21D,
        range_score=_RANGE_SCORE,
        # Real IWM net GEX on 2026-07-24 is positive with the flip below spot.
        dealer=DealerSupport("SUPPORT", 5.0e8, 280.0),
    )
    kwargs.update(over)
    return build_candidate(**kwargs)


def test_all_gates_passing_yields_theta_harvest_verdict():
    # Real IWM 2026-07-24 clears all six gates on real data.
    c = _candidate()
    assert isinstance(c, ThetaCandidate)
    assert all(c.gates.values())
    # 55 * (9.7212/15) + 25 * (1 - 0.0018275/0.10) + 20 * 0.534602
    assert c.score == pytest.approx(70.879602930724, rel=1e-9)
    # Deliberately marginal: IWM's edge is ~p85, not top-decile, so a
    # genuinely rich-but-not-extreme name clears the default bar by 0.88.
    # If a weight change moves this, the test SHOULD fail loudly.
    assert c.verdict == "THETA_HARVEST"


def test_directional_book_is_called_out_as_disguise():
    # |net delta| above 0.20 means this is a directional bet wearing a
    # strangle's clothes, regardless of how rich the vol is.
    c = _candidate(structure=_structure(net_delta=0.35))
    assert c.gates["delta_near_zero"] is False
    assert c.verdict == "DIRECTIONAL_DISGUISE"


def test_cheap_vol_is_a_disguise_not_a_watchlist_entry():
    # IV under RV: no edge to harvest. Radon routes this to DIRECTIONAL_DISGUISE
    # via the iv_gate branch even when delta is clean.
    #
    # REAL QQQ readings for session 2026-07-21, read from option_wizard on
    # 2026-07-29: iv_rank_history.volatility 0.241 against HV20 0.25568 — QQQ
    # genuinely failed this gate that day (edge -1.47 vol points, ratio 0.943).
    # A single real session supplies all three readings; pairing one date's IV
    # with another date's realised vol would be a fixture that never existed.
    # (AAPL's 0.2292 is real but dated 2026-05-20, and against ITS OWN HV20 of
    # 0.19159 the ratio is 1.196 -- it PASSES the gate. It cannot be the
    # negative case.)
    c = _candidate(iv=0.241, hv20=0.25567671527495894, hv60=0.2479297744543768)
    assert c.iv_rv_edge < 0
    assert c.gates["iv_rich_vs_rv"] is False
    assert c.verdict == "DIRECTIONAL_DISGUISE"


def test_dealer_support_is_recorded_but_not_critical_by_default():
    # DEFAULT_WEIGHTS.dealer_gate_critical is False, so short-gamma dealers
    # are RECORDED and still harvest-eligible. This is the deliberate change
    # that keeps 116 backtestable sessions instead of 24.
    c = _candidate(dealer=DealerSupport("NO_SUPPORT", -3.0e8, None))
    assert c.gates["dealer_support"] is False
    assert c.verdict == "THETA_HARVEST"


def test_dealer_gate_becomes_critical_under_radon_weights():
    c = _candidate(
        dealer=DealerSupport("NO_SUPPORT", -3.0e8, None), weights=RADON_WEIGHTS
    )
    assert c.gates["dealer_support"] is False
    assert c.verdict == "WATCHLIST"


def test_radon_weights_reproduce_the_original_score():
    # Radon's published number for this row is 94.19. Its formula carried a
    # constant +40 once the critical gates passed; ours drops it. The two
    # must therefore differ by exactly 40 -- if they don't, the reweight
    # changed something other than the constant, which is a bug.
    c = _candidate(weights=RADON_WEIGHTS)
    assert c.score == pytest.approx(54.192171263918, rel=1e-9)
    assert c.score + 40.0 == pytest.approx(94.192171263918, rel=1e-9)
    assert c.verdict == "THETA_HARVEST"  # 54.19 >= threshold 30


def test_weights_version_is_stamped_on_the_candidate():
    assert _candidate().weights_version == DEFAULT_WEIGHTS.version
    assert _candidate(weights=RADON_WEIGHTS).weights_version == RADON_WEIGHTS.version
    assert DEFAULT_WEIGHTS.version != RADON_WEIGHTS.version


def test_iv_edge_and_ratio_are_reported_in_vol_points():
    c = _candidate()
    # Real IWM: IV 0.208 vs HV20 0.11079 -> +9.72 vol points, ratio 1.877.
    assert c.iv_rv_edge == pytest.approx((_IV - _HV20) * 100.0)
    assert c.iv_rv_edge == pytest.approx(9.7212090846368, rel=1e-9)
    assert c.iv_rv_ratio == pytest.approx(_IV / _HV20)


def test_entry_credit_is_the_sum_of_both_black_scholes_leg_marks():
    c = _candidate()
    assert c.entry_credit_theo == pytest.approx(c.put_mark + c.call_mark)
    assert c.put_mark > 0 and c.call_mark > 0


def test_score_is_bounded_to_one_hundred():
    c = _candidate(iv=2.0, hv20=0.10, range_score=1.0)
    assert c.score <= 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -k candidate -v`
Expected: FAIL — `ImportError: cannot import name 'ThetaCandidate'`

- [ ] **Step 3: Write the implementation**

Append to `src/uw_scan/scanners/theta_harvester.py` (add `from uw_scan.reports.vrp_structure import bs_price` to imports):

```python
@dataclass(frozen=True)
class ThetaCandidate:
    ticker: str
    as_of: date
    structure: Strangle
    spot: float
    iv: float
    hv20: float
    hv60: float | None
    iv_rv_edge: float
    iv_rv_ratio: float
    trend_20d_pct: float
    range_score: float
    dealer: DealerSupport
    score: float
    weights_version: str
    verdict: str
    gates: dict[str, bool]
    put_mark: float
    call_mark: float
    entry_credit_theo: float
    risk_free_rate: float  # the rate the marks were priced at, carried so the
                           # markout re-prices at the SAME rate it entered at


@dataclass(frozen=True)
class ScoreWeights:
    """The entire tunable surface. Every field is swept by Task 13.

    Radon's 100-point score was 25 delta / 25 vol / 20 dealer / 15 theta /
    10 range / 5 gamma. Three of those six are CONSTANT once the critical
    gates pass: `dealer_support` is itself a critical gate, `theta > 0` is a
    critical gate, and `gamma < 0` is implied by a delta-balanced short
    strangle. 40 of 100 points therefore never discriminate between eligible
    candidates. We score only the three components that actually vary and
    keep the rest as gates -- gates gate, scores score.

    `edge_saturation_pts` matters more than the weight. Radon's
    `min(25, edge * 2.5)` maxes out at 10 vol points of IV-RV. Measured on
    the mini 2026-07-29 over the 1 090 (ticker, session) pairs that have both
    a grid capture and an `iv_rank_history` reading, `(IV - HV20) * 100` is
    distributed p50 2.14 / p75 6.53 / p90 14.34 / p95 19.16 / p99 36.13, and
    32.7% clear the `edge >= 5` gate. Radon's cap therefore sat at ~p85 and
    pinned the term for the whole top decile. The default saturates at **15**
    -- p90 rounded -- so "full vol credit" means top-decile richness. The
    reproduce query is in Task 13.

    `dealer_gate_critical` defaults False. Radon had it True, but the
    strike-level GEX feed (`exposures_by_expiry_strike`) only starts
    2026-05, while the IV grid starts 2025-12-26. Requiring it collapses
    the backtestable entry universe from 116 dates to 24 -- and the dealer-
    gamma-support premise has no peer-reviewed support to justify that cost.
    It is swept as a parameter rather than decided by assertion.
    """

    vol_edge: float = 55.0
    delta_neutrality: float = 25.0
    range_bound: float = 20.0
    edge_saturation_pts: float = 15.0
    threshold: float = 70.0
    dealer_gate_critical: bool = False

    @property
    def version(self) -> str:
        """Stable provenance tag persisted on every candidate row."""
        return (
            f"v{self.vol_edge:g}/{self.delta_neutrality:g}/{self.range_bound:g}"
            f"@{self.edge_saturation_pts:g}t{self.threshold:g}"
            f"{'d' if self.dealer_gate_critical else ''}"
        )


DEFAULT_WEIGHTS = ScoreWeights()

# Radon's original, kept as a named sweep point so "did the reweight help?"
# is a question the sweep answers rather than one this plan asserts.
#
# Threshold is 30, not radon's 70, and that is not a change in strictness:
# radon's 70 was measured on a scale carrying a constant +40 (dealer 20 +
# theta 15 + gamma 5, all implied once the critical gates pass). Dropping the
# constant shifts every score down by exactly 40, so 70 - 40 = 30 is the
# SAME cut. `test_radon_weights_reproduce_the_original_score` pins the
# identity on the real IWM fixture: 54.192171 + 40 == 94.192171, which is the
# number radon's formula produces for that row.
RADON_WEIGHTS = ScoreWeights(
    vol_edge=25.0,
    delta_neutrality=25.0,
    range_bound=10.0,
    edge_saturation_pts=10.0,
    threshold=30.0,
    dealer_gate_critical=True,
)


def score_from_components(
    *,
    iv_rv_edge: float,
    net_delta: float,
    range_score: float,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> float:
    """Pure function of three persisted columns -- that is the whole point.

    `theta_harvester_candidates` stores `iv_rv_edge`, `net_delta` and
    `range_score` raw, so any weight vector can be re-scored over the full
    backfill with a single pass and NO rescan. The stored `score` column is
    a display convenience; this function is the truth.
    """
    vol_c = min(1.0, max(0.0, iv_rv_edge / weights.edge_saturation_pts))
    delta_c = max(0.0, 1.0 - abs(net_delta) / NEAR_ZERO_DELTA)
    range_c = min(1.0, max(0.0, range_score))
    return (
        weights.vol_edge * vol_c
        + weights.delta_neutrality * delta_c
        + weights.range_bound * range_c
    )


def build_candidate(
    *,
    ticker: str,
    as_of: date,
    structure: Strangle,
    spot: float,
    iv: float,
    hv20: float,
    hv60: float | None,
    trend_20d_pct: float,
    range_score: float,
    dealer: DealerSupport,
    r: float = RISK_FREE_RATE,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> ThetaCandidate:
    """Apply radon's gates and 100-point score, and mark the entry.

    entry_credit_theo prices BOTH legs off the same grid IV the markout job
    will re-read. Mixing an IB NBBO entry with grid-IV marks would bake a
    constant bid-ask bias into every forward P&L.
    """
    iv_rv_edge = (iv - hv20) * 100.0
    iv_rv_ratio = (iv / hv20) if hv20 > 0 else 0.0

    gates = {
        "delta_near_zero": abs(structure.net_delta) <= NEAR_ZERO_DELTA,
        "iv_rich_vs_rv": iv_rv_edge >= 5.0 or iv_rv_ratio >= 1.10,
        "dealer_support": dealer.label == "SUPPORT",
        "theta_positive": structure.theta > 0,
        "gamma_controlled": structure.gamma < 0
        and abs(structure.net_delta) <= 0.20,
        "range_bound": range_score >= 0.35,
    }

    score = score_from_components(
        iv_rv_edge=iv_rv_edge,
        net_delta=structure.net_delta,
        range_score=range_score,
        weights=weights,
    )

    critical = (
        gates["delta_near_zero"]
        and gates["iv_rich_vs_rv"]
        and gates["theta_positive"]
        and (gates["dealer_support"] or not weights.dealer_gate_critical)
    )
    if critical and score >= weights.threshold:
        verdict = "THETA_HARVEST"
    elif abs(structure.net_delta) > 0.20 or not gates["iv_rich_vs_rv"]:
        verdict = "DIRECTIONAL_DISGUISE"
    else:
        verdict = "WATCHLIST"

    t_years = max(structure.dte, 0) / 365.0
    put_mark = bs_price(
        spot, structure.put.strike, t_years, r, structure.put.iv, is_call=False
    )
    call_mark = bs_price(
        spot, structure.call.strike, t_years, r, structure.call.iv, is_call=True
    )

    return ThetaCandidate(
        ticker=ticker,
        as_of=as_of,
        structure=structure,
        spot=spot,
        iv=iv,
        hv20=hv20,
        hv60=hv60,
        iv_rv_edge=iv_rv_edge,
        iv_rv_ratio=iv_rv_ratio,
        trend_20d_pct=trend_20d_pct,
        range_score=range_score,
        dealer=dealer,
        score=score,
        weights_version=weights.version,
        verdict=verdict,
        gates=gates,
        put_mark=put_mark,
        call_mark=call_mark,
        entry_credit_theo=put_mark + call_mark,
        risk_free_rate=r,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -v`
Expected: all 23 PASS.

- [ ] **Step 5: Check module size**

Run: `wc -l src/uw_scan/scanners/theta_harvester.py`
Expected: under 500. If over, stop and split before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/scanners/theta_harvester.py tests/unit/scanners/test_theta_harvester.py
git commit -m "feat(theta): gates, 100-point score and Black-Scholes entry mark"
```

---

### Task 5: Repository — loaders and persistence

**Files:**
- Create: `src/uw_scan/storage/theta_harvester_repository.py`
- Test: `tests/integration/test_theta_harvester_repository.py`

**Interfaces:**
- Consumes: `ThetaCandidate` from Task 4.
- Produces `ThetaHarvesterRepository` (standalone, constructed with a `psycopg.Connection` and schema name, following `storage/backtest_repository.py`'s standalone pattern — do NOT add methods to `repository.py`):
  - `load_chain(ticker: str, as_of: date) -> list[OptionLeg]` — legs carry argon's stored LONG-contract greeks; `select_short_strangle` negates them
  - `load_gex_rows(ticker: str, as_of: date) -> list[dict[str, Any]]`
  - `load_closes(ticker: str, as_of: date, lookback: int = 90) -> list[float]`
  - `load_atm_iv(ticker: str, as_of: date, expiry: date) -> float | None`
  - `load_spot(ticker: str, as_of: date) -> float | None`
  - `latest_surface_date() -> date | None`
  - `active_tickers() -> list[str]`
  - `upsert_candidates(rows: Sequence[ThetaCandidate]) -> int`
  - `read_candidates(as_of: date | None = None, limit: int = 100) -> list[dict[str, Any]]`
  - `set_ib_credit(ticker: str, as_of: date, *, credit: float, source: str) -> None`
  - `latest_as_of() -> date | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_theta_harvester_repository.py
"""Repository round-trip against a real Postgres schema (pytest-postgresql)."""

from datetime import date

import pytest

from uw_scan.scanners.theta_harvester import (
    DealerSupport,
    OptionLeg,
    build_candidate,
    select_short_strangle,
)
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository

# Frozen real capture — IWM, 2026-07-24, expiry 2026-08-21. Same provenance as
# the Task 3 unit fixtures; see the header comment there for the source query.
_AS_OF = date(2026, 7, 24)
_EXP = date(2026, 8, 21)
_SPOT = 291.44


def _candidate(ticker="IWM", score_spot=_SPOT):
    # Legs are LONG-convention (theta <= 0, gamma >= 0), matching
    # option_surface_grid_daily. select_short_strangle does the negation, so
    # the fixture never hand-writes position signs — see Task 3.
    put = OptionLeg(_EXP, 272.0, "P", 0.251489543772415, -0.154573982720319,
                    -0.0861128240264245, 0.0117240381034907, 0.191878725809937)
    call = OptionLeg(_EXP, 306.0, "C", 0.172509740706994, 0.156401472783266,
                     -0.0595290822132382, 0.0172246813925854, 0.193372401778545)
    structure = select_short_strangle([put, call], spot=_SPOT, as_of=_AS_OF)
    assert structure is not None and structure.theta > 0
    return build_candidate(
        ticker=ticker, as_of=_AS_OF, structure=structure, spot=score_spot,
        iv=0.208, hv20=0.110787909153632, hv60=0.185963130865730,
        trend_20d_pct=-1.860527823654312, range_score=0.534602106806286,
        dealer=DealerSupport("SUPPORT", 5.0e8, 280.0),
    )


def test_upsert_then_read_round_trips_every_persisted_field(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    assert repo.upsert_candidates([_candidate()]) == 1

    rows = repo.read_candidates(as_of=_AS_OF)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "IWM"
    assert row["verdict"] == "THETA_HARVEST"
    assert float(row["put_strike"]) == 272.0
    assert float(row["call_strike"]) == 306.0
    assert row["gate_dealer_support"] is True
    assert row["credit_ib"] is None
    assert float(row["entry_credit_theo"]) == pytest.approx(
        float(row["put_mark"]) + float(row["call_mark"])
    )


def test_upsert_is_idempotent_on_ticker_and_as_of(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    repo.upsert_candidates([_candidate()])
    repo.upsert_candidates([_candidate(score_spot=292.55)])
    rows = repo.read_candidates(as_of=_AS_OF)
    assert len(rows) == 1
    assert float(rows[0]["underlying_spot"]) == 292.55


def test_set_ib_credit_populates_only_the_quote_columns(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    repo.upsert_candidates([_candidate()])
    before = repo.read_candidates(as_of=_AS_OF)[0]

    repo.set_ib_credit("IWM", _AS_OF, credit=4.15, source="xenon_ib")
    after = repo.read_candidates(as_of=_AS_OF)[0]

    assert float(after["credit_ib"]) == pytest.approx(4.15)
    assert after["credit_source"] == "xenon_ib"
    assert after["credit_quoted_at"] is not None
    # The markout basis must be untouched by a live quote.
    assert after["entry_credit_theo"] == before["entry_credit_theo"]


def test_read_candidates_orders_by_score_descending(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    high = _candidate(ticker="IWM")
    low = _candidate(ticker="QQQ")
    repo.upsert_candidates([low, high])
    rows = repo.read_candidates(as_of=_AS_OF)
    scores = [float(r["score"]) for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_latest_as_of_returns_none_on_empty_table(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    assert repo.latest_as_of() is None
```

Fixture note (verified 2026-07-28 against `tests/integration/conftest.py:180`): the
project has **no** `pg_conn` fixture. `seeded_db_empty_cards` is the freshly-migrated
per-test database and yields a `Repository`, so a standalone repository is built from
its public `.conn`. This mirrors the existing precedent for standalone repositories in
integration tests — `RegimeBacktestRepository(repo.conn, schema=...)` at
`tests/integration/test_compare_vcg_lead_time.py:91`. The fixture seeds a 54-ticker
watchlist, so `active_tickers()` returns rows; assert on specific tickers rather than
on an empty universe.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_theta_harvester_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.storage.theta_harvester_repository'`

- [ ] **Step 3: Write the implementation**

```python
# src/uw_scan/storage/theta_harvester_repository.py
"""Theta Harvester persistence + warm-store loaders.

Standalone repository (not a Repository mixin) — new persistence domains get
their own module from method one; repository.py is not extended.

Every loader reads Postgres only. The scanner's ranking path makes zero UW
calls: option_surface_grid_daily supplies the chain, exposures_by_expiry_strike
the dealer GEX, daily_ohlc the price history, iv_rank_history the current IV.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from uw_scan.scanners.theta_harvester import OptionLeg, ThetaCandidate

_CANDIDATE_COLUMNS: tuple[str, ...] = (
    "ticker", "as_of", "expiry", "dte", "put_strike", "call_strike",
    "underlying_spot", "put_iv", "call_iv", "risk_free_rate",
    "put_mark", "call_mark", "entry_credit_theo",
    "net_delta", "theta", "gamma", "vega",
    "score", "weights_version", "verdict",
    "iv", "hv20", "hv60", "iv_rv_edge", "iv_rv_ratio",
    "trend_20d_pct", "range_score", "dealer_support", "net_gex", "gex_flip",
    "gate_delta_near_zero", "gate_iv_rich_vs_rv", "gate_dealer_support",
    "gate_theta_positive", "gate_gamma_controlled", "gate_range_bound",
)


class ThetaHarvesterRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    # ---------------------------------------------------------------- loaders

    def active_tickers(self) -> list[str]:
        sql = f"SELECT ticker FROM {self._schema}.watchlist WHERE removed_at IS NULL ORDER BY ticker"
        return [r[0] for r in self._conn.execute(sql).fetchall()]

    def load_chain(self, ticker: str, as_of: date) -> list[OptionLeg]:
        """Both sides of the grid flattened into per-right legs.

        Rows missing IV or delta on a side are skipped for that side only — a
        put-less strike still contributes its call.
        """
        sql = f"""
            SELECT expiry, strike,
                   call_iv, call_delta, call_theta, call_gamma, call_vega,
                   put_iv,  put_delta,  put_theta,  put_gamma,  put_vega
              FROM {self._schema}.option_surface_grid_daily
             WHERE ticker = %s AND market_date = %s
             ORDER BY expiry, strike
        """
        # ORDER BY is load-bearing, not cosmetic: without it Postgres may return
        # rows in any order, and the selector's tie-break would silently depend
        # on physical row layout.
        out: list[OptionLeg] = []
        with self._conn.cursor(row_factory=dict_row) as cur:
            for row in cur.execute(sql, (ticker, as_of)).fetchall():
                for right, pfx in (("C", "call"), ("P", "put")):
                    iv, delta = row[f"{pfx}_iv"], row[f"{pfx}_delta"]
                    if iv is None or delta is None:
                        continue
                    out.append(
                        OptionLeg(
                            expiry=row["expiry"],
                            strike=float(row["strike"]),
                            right=right,
                            iv=float(iv),
                            delta=float(delta),
                            theta=float(row[f"{pfx}_theta"] or 0.0),
                            gamma=float(row[f"{pfx}_gamma"] or 0.0),
                            vega=float(row[f"{pfx}_vega"] or 0.0),
                        )
                    )
        return out

    def latest_surface_date(self, *, min_tickers: int = 80) -> date | None:
        """Newest session whose IV surface capture looks COMPLETE.

        The scan anchors here, never on date.today(): the 19:45 ET cron runs
        after that evening's capture on a weekday, but on a holiday — or if the
        capture failed — today has no grid rows and a today-anchored scan would
        silently write zero candidates and look like "no signal".

        `min_tickers` guards a subtler failure. option_surface_capture commits
        per ticker, so the newest market_date appears the moment the FIRST
        ticker lands. A 19:45 scan against a 19:00 capture that is still running
        would see a partially populated session, silently skip every
        uncaptured ticker, and persist a truncated universe that looks
        identical to "those tickers had no candidate". Requiring a plausible
        ticker count before anchoring turns a silent truncation into a skipped
        run. 80 is ~75% of the current 109-ticker watchlist; the fallback to
        the previous complete session is deliberate and safe, because the
        markout re-marks from whatever as_of actually got written.
        """
        sql = f"""
            SELECT market_date
              FROM {self._schema}.option_surface_grid_daily
             GROUP BY market_date
            HAVING COUNT(DISTINCT ticker) >= %s
             ORDER BY market_date DESC
             LIMIT 1
        """
        row = self._conn.execute(sql, (min_tickers,)).fetchone()
        return row[0] if row else None

    def load_spot(self, ticker: str, as_of: date) -> float | None:
        sql = f"""
            SELECT underlying_spot FROM {self._schema}.option_surface_grid_daily
             WHERE ticker = %s AND market_date = %s AND underlying_spot IS NOT NULL
             LIMIT 1
        """
        row = self._conn.execute(sql, (ticker, as_of)).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def load_gex_rows(self, ticker: str, as_of: date) -> list[dict[str, Any]]:
        """Per-strike GEX, aggregated across expiries for that session.

        Sourced from the newest run_id on the date — exposures_by_expiry_strike
        is keyed by run_id and a session can hold more than one scan run.
        """
        sql = f"""
            SELECT strike, SUM(call_gex) AS call_gex, SUM(put_gex) AS put_gex
              FROM {self._schema}.exposures_by_expiry_strike
             WHERE ticker = %s AND market_date = %s
               AND run_id = (
                   SELECT MAX(run_id) FROM {self._schema}.exposures_by_expiry_strike
                    WHERE ticker = %s AND market_date = %s
               )
             GROUP BY strike
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (ticker, as_of, ticker, as_of)).fetchall()

    def load_closes(self, ticker: str, as_of: date, lookback: int = 90) -> list[float]:
        """Ascending closes up to and including as_of."""
        sql = f"""
            SELECT close FROM (
                SELECT date, close FROM {self._schema}.daily_ohlc
                 WHERE ticker = %s AND date <= %s AND close IS NOT NULL
                 ORDER BY date DESC LIMIT %s
            ) t ORDER BY date ASC
        """
        rows = self._conn.execute(sql, (ticker, as_of, lookback)).fetchall()
        return [float(r[0]) for r in rows]

    def load_atm_iv(self, ticker: str, as_of: date, expiry: date) -> float | None:
        """ATM IV from the SAME grid session and expiry the legs come from.

        NOT from iv_rank_history — see the module docstring rationale and the
        coverage note in Interpretation constraints.
        """
        sql = f"""
            SELECT (call_iv + put_iv) / 2.0
              FROM {self._schema}.option_surface_grid_daily
             WHERE ticker = %s AND market_date = %s AND expiry = %s
               AND call_iv IS NOT NULL AND put_iv IS NOT NULL
               AND underlying_spot > 0
             ORDER BY abs(strike - underlying_spot)
             LIMIT 1
        """
        row = self._conn.execute(sql, (ticker, as_of, expiry)).fetchone()
        if not row or row[0] is None:
            return None
        iv = float(row[0])
        return iv / 100.0 if iv > 3.0 else iv

    # ------------------------------------------------------------ persistence

    def upsert_candidates(self, rows: Sequence[ThetaCandidate]) -> int:
        """Insert or refresh candidates, deleting stale marks on identity change.

        The contract identity (expiry, put_strike, call_strike) is part of the
        row but NOT part of the key. A rescan on the same (ticker, as_of) can
        legitimately pick a different structure — the chain moved, or a strike
        appeared. Overwriting the row while leaving `theta_harvester_markouts`
        untouched would silently re-attach P&L generated by the OLD structure
        to the NEW one, which is worse than having no markout at all: the
        numbers look valid and are not.

        So: whenever identity changes, the dependent marks are deleted in the
        SAME transaction and the candidate is re-marked from scratch on the
        next markout run. Identical re-scans (the common case) touch nothing.
        """
        if not rows:
            return 0
        cols = ", ".join(_CANDIDATE_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_CANDIDATE_COLUMNS))
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in _CANDIDATE_COLUMNS
            if c not in ("ticker", "as_of")
        )
        sql = f"""
            INSERT INTO {self._schema}.theta_harvester_candidates ({cols})
            VALUES ({placeholders})
            ON CONFLICT (ticker, as_of) DO UPDATE SET {updates}
        """
        # Identity changed => the existing marks describe a different trade.
        purge = f"""
            DELETE FROM {self._schema}.theta_harvester_markouts m
             USING {self._schema}.theta_harvester_candidates c
             WHERE m.ticker = c.ticker AND m.as_of = c.as_of
               AND c.ticker = %s AND c.as_of = %s
               AND (c.expiry, c.put_strike, c.call_strike) IS DISTINCT FROM (%s, %s, %s)
        """
        with self._conn.cursor() as cur:
            for cand in rows:
                s = cand.structure
                cur.execute(
                    purge,
                    (cand.ticker, cand.as_of,
                     s.expiry, s.put.strike, s.call.strike),
                )
            cur.executemany(sql, [self._to_params(c) for c in rows])
        self._conn.commit()
        return len(rows)

    @staticmethod
    def _to_params(c: ThetaCandidate) -> tuple[Any, ...]:
        s = c.structure
        return (
            c.ticker, c.as_of, s.expiry, s.dte, s.put.strike, s.call.strike,
            # The rate actually used to price the marks — never a literal. A
            # hardcoded 0.045 here would silently diverge from the entry mark
            # the moment RISK_FREE_RATE is changed or overridden, and the
            # markout would re-price at a rate the entry never used.
            c.spot, s.put.iv, s.call.iv, c.risk_free_rate,
            c.put_mark, c.call_mark, c.entry_credit_theo,
            s.net_delta, s.theta, s.gamma, s.vega,
            c.score, c.weights_version, c.verdict, c.iv, c.hv20, c.hv60,
            c.iv_rv_edge, c.iv_rv_ratio, c.trend_20d_pct, c.range_score,
            c.dealer.label, c.dealer.net_gex, c.dealer.gex_flip,
            c.gates["delta_near_zero"], c.gates["iv_rich_vs_rv"],
            c.gates["dealer_support"], c.gates["theta_positive"],
            c.gates["gamma_controlled"], c.gates["range_bound"],
        )

    def set_ib_credit(
        self, ticker: str, as_of: date, *, credit: float, source: str
    ) -> None:
        sql = f"""
            UPDATE {self._schema}.theta_harvester_candidates
               SET credit_ib = %s, credit_source = %s, credit_quoted_at = now()
             WHERE ticker = %s AND as_of = %s
        """
        self._conn.execute(sql, (credit, source, ticker, as_of))
        self._conn.commit()

    # ------------------------------------------------------------------ reads

    def latest_as_of(self) -> date | None:
        sql = f"SELECT MAX(as_of) FROM {self._schema}.theta_harvester_candidates"
        row = self._conn.execute(sql).fetchone()
        return row[0] if row else None

    def read_candidates(
        self, as_of: date | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        target = as_of or self.latest_as_of()
        if target is None:
            return []
        sql = f"""
            SELECT * FROM {self._schema}.theta_harvester_candidates
             WHERE as_of = %s ORDER BY score DESC, ticker ASC LIMIT %s
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (target, limit)).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_theta_harvester_repository.py -v`
Expected: all 7 PASS (the 5 listed above plus the two identity-purge tests:
`test_identity_change_purges_stale_markouts` and
`test_identical_rescan_keeps_existing_markouts` — the purge is the whole
reason `upsert_candidates` is not a plain ON CONFLICT, so it needs a test).

On a MacBook the integration DB needs forced-local env — if it errors on connection, export `UW_SCAN_DB_HOST=127.0.0.1`, `UW_SCAN_DB_USER=$(whoami)`, `TEST_DB_NAME=option_wizard_test` in the shell first (shell env wins over `.env.local`).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/theta_harvester_repository.py tests/integration/test_theta_harvester_repository.py
git commit -m "feat(theta): warm-store loaders and candidate persistence"
```

---

### Task 6: Scan orchestration + worker job + scheduler

**Files:**
- Create: `src/uw_scan/worker/jobs/theta_harvester.py`
- Modify: `src/uw_scan/config.py` (add `theta_harvester_enabled`)
- Modify: `src/uw_scan/worker/scheduler.py` (import ~line 81, wrapper ~line 755, cron ~line 1372)
- Test: `tests/unit/scanners/test_theta_harvester.py` (orchestration test with a stub repo)

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces:
  - `scan_ticker(repo: ThetaHarvesterRepository, ticker: str, as_of: date) -> ThetaCandidate | None` — in `worker/jobs/theta_harvester.py`
  - `theta_harvester_scan(*, repo: Repository, settings: Settings, as_of: date | None = None, tickers: list[str] | None = None) -> dict[str, Any]` returning `{"as_of": str, "tickers_scanned": int, "candidates_written": int, "harvest_count": int}`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/scanners/test_theta_harvester.py`:

```python
from uw_scan.worker.jobs.theta_harvester import scan_ticker


class _StubRepo:
    """In-memory stand-in for ThetaHarvesterRepository — the frozen real IWM
    2026-07-24 capture from Task 3, no network, no DB.

    `closes` is the one deliberately synthetic input: it is a low-amplitude
    oscillation, not IWM's real path, chosen so HV20 stays small enough that
    the real IV (0.208) clears the IV-edge gate and this test exercises the
    happy path. It is a numeric stand-in for a vol level, not a price series
    presented as observed — the real 90-close IWM series lives in the Task 4
    fixtures as _HV20/_HV60.
    """

    def __init__(self, *, closes=None, chain=None, gex=None, iv=0.208, spot=291.44):
        self._closes = (
            closes
            if closes is not None
            else [288.0 + (i % 5) * 0.9 for i in range(90)]
        )
        # LONG-convention legs, as load_chain returns them. theta must be <= 0
        # here — the selector negates. See Task 3.
        self._chain = chain if chain is not None else [
            _PUT_16D,
            _CALL_16D,
        ]
        self._gex = gex if gex is not None else [
            {"strike": 272.0, "call_gex": 4.0e8, "put_gex": -1.0e8},
            {"strike": 306.0, "call_gex": 3.0e8, "put_gex": -1.0e8},
        ]
        self._iv, self._spot = iv, spot

    def load_closes(self, ticker, as_of, lookback=90): return self._closes
    def load_chain(self, ticker, as_of): return self._chain
    def load_gex_rows(self, ticker, as_of): return self._gex
    def load_iv(self, ticker, as_of): return self._iv
    def load_spot(self, ticker, as_of): return self._spot


def test_scan_ticker_produces_a_candidate_from_warm_store_rows():
    out = scan_ticker(_StubRepo(), "IWM", _AS_OF)
    assert out is not None
    assert out.ticker == "IWM"
    assert out.structure.put.strike == 272.0


def test_scan_ticker_returns_none_without_enough_price_history():
    # HV20 needs 21 closes; 10 is not enough and a partial window would
    # understate vol and loosen the IV-edge gate.
    assert scan_ticker(_StubRepo(closes=[291.17] * 10), "IWM", _AS_OF) is None


def test_scan_ticker_returns_none_when_the_chain_is_empty():
    assert scan_ticker(_StubRepo(chain=[]), "IWM", _AS_OF) is None


def test_scan_ticker_returns_none_without_an_iv_reading():
    assert scan_ticker(_StubRepo(iv=None), "IWM", _AS_OF) is None


def test_scan_ticker_still_scores_when_gex_is_missing():
    # No dealer data must not kill the row — it fails one gate and lands on
    # the watchlist, which is information, unlike a dropped ticker.
    out = scan_ticker(_StubRepo(gex=[]), "IWM", _AS_OF)
    assert out is not None
    assert out.dealer.label == "UNKNOWN"
    assert out.gates["dealer_support"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -k scan_ticker -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.worker.jobs.theta_harvester'`

- [ ] **Step 3: Write the implementation**

```python
# src/uw_scan/worker/jobs/theta_harvester.py
"""Theta Harvester scan job — zero-UW ranking over the warm store."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from uw_scan.config import Settings
from uw_scan.scanners.theta_harvester import (
    RISK_FREE_RATE,
    ThetaCandidate,
    build_candidate,
    dealer_support,
    range_metrics,
    realized_vol,
    select_short_strangle,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository

log = logging.getLogger(__name__)


def scan_ticker(repo: Any, ticker: str, as_of: date) -> ThetaCandidate | None:
    """One best strangle for one ticker-session, or None when inputs are thin.

    Returning None is deliberate for missing price history / chain / IV: a
    partial HV window or a chainless ticker would produce a candidate whose
    gates mean something different from every other row.
    """
    closes = repo.load_closes(ticker, as_of, lookback=90)
    hv20 = realized_vol(closes, 20)
    if hv20 is None or hv20 <= 0:
        return None
    hv60 = realized_vol(closes, 60)

    spot = repo.load_spot(ticker, as_of)
    if spot is None or spot <= 0:
        return None

    structure = select_short_strangle(repo.load_chain(ticker, as_of), spot, as_of)
    if structure is None:
        return None

    # ATM IV is read AFTER the structure is chosen, at that structure's own
    # expiry — so the IV and the traded legs always describe the same session
    # and the same tenor.
    iv = repo.load_atm_iv(ticker, as_of, structure.expiry)
    if iv is None or iv <= 0:
        return None

    ranged = range_metrics(closes, hv20)
    if ranged is None:
        return None  # <22 closes: "unknown", not "maximally trending"
    trend_pct, range_score = ranged
    return build_candidate(
        ticker=ticker,
        as_of=as_of,
        structure=structure,
        spot=spot,
        iv=iv,
        hv20=hv20,
        hv60=hv60,
        trend_20d_pct=trend_pct,
        range_score=range_score,
        dealer=dealer_support(repo.load_gex_rows(ticker, as_of), spot),
        r=RISK_FREE_RATE,
    )


def theta_harvester_scan(
    *,
    repo: Repository,
    settings: Settings,
    as_of: date | None = None,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Scan the watchlist (or an explicit subset) and persist candidates."""
    th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
    target = as_of or th.latest_surface_date()
    if target is None:
        log.warning("theta_harvester_scan: no surface capture yet, nothing to scan")
        return {"tickers_scanned": 0, "candidates_written": 0, "harvest_count": 0}
    universe = tickers or th.active_tickers()

    candidates: list[ThetaCandidate] = []
    for ticker in universe:
        try:
            found = scan_ticker(th, ticker, target)
        except Exception:  # one bad ticker must not abort the sweep
            log.exception("theta_harvester_scan: %s failed", ticker)
            continue
        if found is not None:
            candidates.append(found)

    written = th.upsert_candidates(candidates)
    harvest = sum(1 for c in candidates if c.verdict == "THETA_HARVEST")
    log.info(
        "theta_harvester_scan: as_of=%s scanned=%d written=%d harvest=%d",
        target, len(universe), written, harvest,
    )
    return {
        "as_of": str(target),
        "tickers_scanned": len(universe),
        "candidates_written": written,
        "harvest_count": harvest,
    }
```

- [ ] **Step 4: Confirm `latest_surface_date` resolves**

`latest_surface_date` is already defined in Task 5's repository module — do NOT
add a second copy here. This step only verifies the anchor works, because the
scan silently writes nothing if it does not:

```bash
uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c:
    print('anchor:', ThetaHarvesterRepository(c, s.db_schema).latest_surface_date())
"
```
Expected: a recent weekday, NOT `None` and not today's date on a weekend. The
scan anchors here rather than on `date.today()` so a holiday or a missed
capture re-scans the last real session instead of writing zero rows for a date
with no data — which would read as "no signal" rather than "no data".

Confirm the `target` line in `theta_harvester_scan` reads:

```python
    target = as_of or th.latest_surface_date()
    if target is None:
        log.warning("theta_harvester_scan: no surface capture yet, nothing to scan")
        return {"tickers_scanned": 0, "candidates_written": 0, "harvest_count": 0}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/scanners/test_theta_harvester.py -v`
Expected: all 28 PASS.

- [ ] **Step 6: Add the config flag**

In `src/uw_scan/config.py`, next to the other `*_enabled` scanner flags:

```python
    theta_harvester_enabled: bool = True
```

Wire it into `from_env` the same way the neighbouring flags read `UW_SCAN_THETA_HARVESTER_ENABLED`. Follow the surrounding pattern exactly.

- [ ] **Step 7: Register the scheduled job**

In `src/uw_scan/worker/scheduler.py`:

Import, near line 81:
```python
from uw_scan.worker.jobs.theta_harvester import theta_harvester_scan
```

Wrapper, near line 755 alongside `_vrp_markout_refresh`:
```python
    def _theta_harvester_scan() -> None:
        with _repo(settings) as repo:
            theta_harvester_scan(repo=repo, settings=settings)
```

Cron, near line 1372:
```python
            # Theta Harvester at 19:45 ET — after option_surface_capture (19:00)
            # and its IV canary (19:30) have landed the session's grid. Pure
            # warm-store compute: zero UW budget, so massive-0 is the right home.
            if settings.theta_harvester_enabled:
                sched.add_job(
                    _theta_harvester_scan,
                    CronTrigger.from_crontab("45 19 * * 0-4", timezone=settings.rth_tz),
                    id="theta_harvester_scan",
                    name="Theta Harvester short-strangle scan",
                    max_instances=1,
                    coalesce=True,
                )
```

Place it inside the same worker-role branch that hosts `_vrp_markout_refresh` (massive-0). Read the surrounding `if` condition and match it.

- [ ] **Step 8: Verify the scheduler still imports**

Run: `uv run python -c "import uw_scan.worker.scheduler; print('ok')"`
Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/worker/jobs/theta_harvester.py src/uw_scan/worker/scheduler.py \
        src/uw_scan/config.py src/uw_scan/storage/theta_harvester_repository.py \
        tests/unit/scanners/test_theta_harvester.py
git commit -m "feat(theta): scan orchestration, worker job and 19:45 ET cron"
```

---

### Task 7: Markout compute + job

**Files:**
- Create: `src/uw_scan/reports/theta_harvester_markout.py`
- Modify: `src/uw_scan/storage/theta_harvester_repository.py` (markout loaders/writers)
- Modify: `src/uw_scan/worker/jobs/theta_harvester.py` (second job wrapper)
- Modify: `src/uw_scan/worker/scheduler.py` (second cron)
- Test: `tests/unit/reports/test_theta_harvester_markout.py`

**Interfaces:**
- Consumes: Task 5's repository; `bs_price`.
- Produces:
  - `HORIZONS: tuple[int, ...] = (5, 10, 20, 30)`
  - `TERMINAL_HORIZON: int = -1` — sentinel for the at-expiry settlement mark
  - `MAX_SNAP_DAYS: int = 7` — bound on snapping a horizon forward to a live session
  - `mark_position(*, spot: float, put_strike: float, call_strike: float, put_iv: float, call_iv: float, dte_remaining: int, r: float) -> tuple[float, float, float]` → `(put_mark, call_mark, position_value)`
  - `run_theta_markout(*, repo: ThetaHarvesterRepository) -> dict[str, Any]` returning `{"candidates_scored": int, "marks_written": int}`
  - Repository additions: `load_candidates_needing_marks(horizons) -> list[dict]`, `load_marks_for(ticker, expiry, put_strike, call_strike, mark_date, *, max_snap_days=7) -> dict | None` (returns the earliest session that already satisfies both strikes + both IVs, including its resolved `market_date`), `load_settlement_close(ticker, expiry) -> tuple[date, float] | None` (resolves **backward** to the last session at or before expiry), `has_session_after(ticker, on) -> bool`, `upsert_markouts(rows) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/reports/test_theta_harvester_markout.py
"""Forward re-marking of Theta Harvester strangles. Pure compute, no DB."""

import pytest

from uw_scan.reports.theta_harvester_markout import (
    HORIZONS,
    MAX_SNAP_DAYS,
    TERMINAL_HORIZON,
    mark_position,
)


def test_horizons_cover_the_designed_taper():
    assert HORIZONS == (5, 10, 20, 30)


def test_terminal_horizon_is_a_distinct_sentinel():
    # A short strangle's loss distribution lives at expiry. Without a terminal
    # row every intermediate horizon still carries time value and the P&L
    # series is truncated above — it structurally cannot show the loss.
    assert TERMINAL_HORIZON == -1
    assert TERMINAL_HORIZON not in HORIZONS
    assert MAX_SNAP_DAYS == 7


def test_position_value_is_the_sum_of_both_leg_marks():
    put, call, value = mark_position(
        spot=291.44, put_strike=272.0, call_strike=306.0,
        put_iv=0.251489543772415, call_iv=0.172509740706994, dte_remaining=18, r=0.045,
    )
    assert value == pytest.approx(put + call)
    assert put > 0 and call > 0


def test_decay_shrinks_the_position_value_all_else_equal():
    # Short strangle held to fewer remaining days at an unchanged spot and vol
    # is worth less to buy back — that is the theta the strategy harvests.
    _, _, far = mark_position(
        spot=291.44, put_strike=272.0, call_strike=306.0,
        put_iv=0.251489543772415, call_iv=0.172509740706994, dte_remaining=28, r=0.045,
    )
    _, _, near = mark_position(
        spot=291.44, put_strike=272.0, call_strike=306.0,
        put_iv=0.251489543772415, call_iv=0.172509740706994, dte_remaining=5, r=0.045,
    )
    assert near < far


def test_at_expiry_the_position_is_worth_pure_intrinsic():
    # Spot 316 is 10 above the 306 call strike: intrinsic is exactly 10, and
    # the 272 put expires worthless.
    put, call, value = mark_position(
        spot=316.0, put_strike=272.0, call_strike=306.0,
        put_iv=0.251489543772415, call_iv=0.172509740706994, dte_remaining=0, r=0.045,
    )
    assert put == pytest.approx(0.0)
    assert call == pytest.approx(10.0)
    assert value == pytest.approx(10.0)


def test_vol_expansion_raises_the_cost_to_close():
    _, _, calm = mark_position(
        spot=291.44, put_strike=272.0, call_strike=306.0,
        put_iv=0.251489543772415, call_iv=0.172509740706994, dte_remaining=18, r=0.045,
    )
    _, _, panic = mark_position(
        spot=291.44, put_strike=272.0, call_strike=306.0,
        put_iv=0.503, call_iv=0.345, dte_remaining=18, r=0.045,
    )
    assert panic > calm
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_theta_harvester_markout.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.reports.theta_harvester_markout'`

- [ ] **Step 3: Write the compute module**

```python
# src/uw_scan/reports/theta_harvester_markout.py
"""Forward markout for Theta Harvester strangles.

Re-prices the exact contracts a candidate row recorded, using
option_surface_grid_daily IV on a later session. Entry and marks therefore
share one pricing basis; mixing an IB NBBO entry with grid-IV marks would bake
a constant bid-ask bias into every P&L and read as alpha.

Sign convention: the position is SHORT the strangle, so
pnl = entry_credit_theo - position_value. Positive means the credit was kept.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from uw_scan.reports.vrp_structure import bs_price

log = logging.getLogger(__name__)

HORIZONS: tuple[int, ...] = (5, 10, 20, 30)

# The terminal (at-expiry) mark, stored under a sentinel horizon so it shares
# the markouts table. A short strangle's entire loss distribution lives at and
# near expiry: the intermediate horizons above all still carry time value and
# will read positive in almost every window. WITHOUT this row the markout
# cannot observe the loss the strategy exists to be paid for, and the series is
# structurally truncated above.
TERMINAL_HORIZON = -1

# Snapping a horizon forward past a weekend or a missed capture is correct;
# snapping it three weeks forward because the ticker fell out of the surface is
# not — it would mark a T+5 against a completely different market. Beyond this
# many calendar days the horizon is left unscored instead.
MAX_SNAP_DAYS = 7


def mark_position(
    *,
    spot: float,
    put_strike: float,
    call_strike: float,
    put_iv: float,
    call_iv: float,
    dte_remaining: int,
    r: float,
) -> tuple[float, float, float]:
    """(put_mark, call_mark, position_value) — cost to buy the strangle back."""
    t_years = max(dte_remaining, 0) / 365.0
    put = bs_price(spot, put_strike, t_years, r, put_iv, is_call=False)
    call = bs_price(spot, call_strike, t_years, r, call_iv, is_call=True)
    return put, call, put + call


def run_theta_markout(*, repo: Any) -> dict[str, Any]:
    """Score every candidate whose horizons have come due and are unscored."""
    pending = repo.load_candidates_needing_marks(HORIZONS)
    rows: list[dict[str, Any]] = []

    for cand in pending:
        as_of: date = cand["as_of"]
        expiry: date = cand["expiry"]
        entry_credit = float(cand["entry_credit_theo"])
        put_strike = float(cand["put_strike"])
        call_strike = float(cand["call_strike"])

        for horizon in HORIZONS:
            requested = as_of + timedelta(days=horizon)
            if requested >= expiry:
                # Past expiry there is no grid row to read — the contract is
                # gone from the chain. The terminal mark below covers it.
                continue
            grid = repo.load_marks_for(
                cand["ticker"],
                expiry,
                put_strike,
                call_strike,
                requested,
                max_snap_days=MAX_SNAP_DAYS,
            )
            if grid is None:
                continue  # session not reached, or no surface capture in range

            # The ACTUAL session the grid resolved to, not the requested date.
            # Using `requested` here would date the row to a Saturday and price
            # it with the wrong dte_remaining.
            mark_date = grid["market_date"]
            expired = False
            dte_remaining = max((expiry - mark_date).days, 0)
            spot = float(grid["spot"])
            put_iv = float(grid["put_iv"])
            call_iv = float(grid["call_iv"])
            put_mark, call_mark, value = mark_position(
                spot=spot,
                put_strike=put_strike,
                call_strike=call_strike,
                put_iv=put_iv,
                call_iv=call_iv,
                dte_remaining=dte_remaining,
                r=float(cand["risk_free_rate"]),
            )
            pnl = entry_credit - value
            rows.append(
                {
                    "ticker": cand["ticker"],
                    "as_of": as_of,
                    "horizon_days": horizon,
                    "mark_date": mark_date,
                    "spot": spot,
                    "put_iv": put_iv,
                    "call_iv": call_iv,
                    "put_mark": put_mark,
                    "call_mark": call_mark,
                    "position_value": value,
                    "pnl": pnl,
                    "pnl_pct_of_credit": (
                        pnl / entry_credit * 100.0 if entry_credit > 0 else None
                    ),
                    "breached": spot <= put_strike or spot >= call_strike,
                    "expired": expired,
                }
            )

        # ------------------------------------------------------------ terminal
        # Settlement is the only observation that sees the strategy's real risk.
        # Priced as intrinsic off the underlying close on expiry (daily_ohlc,
        # not the grid — the contract has left the chain by then).
        # ponytail: European-style settlement on American options. Early
        # assignment (dividends, deep-ITM puts) would have closed the short leg
        # sooner and usually WORSE than this row shows, so the terminal P&L is
        # an optimistic bound on the loss, not a neutral one. Model assignment
        # only if the loss distribution turns out to matter at the margin.
        settle = (
            repo.load_settlement_close(cand["ticker"], expiry)
            if repo.has_session_after(cand["ticker"], expiry)
            else None
        )
        if settle is not None:
            settle_date, spot = settle
            put_mark = max(0.0, put_strike - spot)
            call_mark = max(0.0, spot - call_strike)
            value = put_mark + call_mark
            pnl = entry_credit - value
            rows.append(
                {
                    "ticker": cand["ticker"],
                    "as_of": as_of,
                    "horizon_days": TERMINAL_HORIZON,
                    # The session actually used, which is the last bar at or
                    # BEFORE expiry — never the nominal expiry when that day
                    # had no bar.
                    "mark_date": settle_date,
                    "spot": spot,
                    "put_iv": None,
                    "call_iv": None,
                    "put_mark": put_mark,
                    "call_mark": call_mark,
                    "position_value": value,
                    "pnl": pnl,
                    "pnl_pct_of_credit": (
                        pnl / entry_credit * 100.0 if entry_credit > 0 else None
                    ),
                    "breached": spot <= put_strike or spot >= call_strike,
                    "expired": True,
                }
            )

    written = repo.upsert_markouts(rows)
    log.info(
        "theta_harvester_markout: %d candidates -> %d marks",
        len(pending), written,
    )
    return {"candidates_scored": len(pending), "marks_written": written}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/reports/test_theta_harvester_markout.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Add the markout repository methods**

Append to `src/uw_scan/storage/theta_harvester_repository.py`:

```python
    _MARKOUT_COLUMNS: tuple[str, ...] = (
        "ticker", "as_of", "horizon_days", "mark_date", "spot",
        "put_iv", "call_iv", "put_mark", "call_mark",
        "position_value", "pnl", "pnl_pct_of_credit", "breached", "expired",
    )

    def load_candidates_needing_marks(
        self, horizons: Sequence[int]
    ) -> list[dict[str, Any]]:
        """Candidates whose first horizon has come due and which are not yet
        settled. Re-scoring a partially-marked row is wasted work but not wrong
        — the upsert is idempotent.

        Completion is defined by the presence of the TERMINAL (horizon -1) row,
        NOT by a count of horizons. A 7-DTE candidate can never collect all
        four intermediate horizons — three of them fall past expiry, where no
        grid row exists — so a count-based predicate would re-scan it every
        night forever and the pending set would grow without bound.

        ponytail: unbounded SELECT that re-marks rows already written. A
        candidate stays pending until its expiry passes, so steady state is
        roughly (max DTE 45) x (watchlist size) rows re-queried nightly and
        upserted to identical values. Idempotent, and a few minutes of work.
        Add a LIMIT and a resume cursor only if the job overruns the 10-minute
        gap before the next cron.
        """
        sql = f"""
            SELECT c.ticker, c.as_of, c.expiry, c.put_strike, c.call_strike,
                   c.entry_credit_theo, c.risk_free_rate
              FROM {self._schema}.theta_harvester_candidates c
             WHERE c.as_of + %s <= CURRENT_DATE
               AND NOT EXISTS (
                   SELECT 1 FROM {self._schema}.theta_harvester_markouts m
                    WHERE m.ticker = c.ticker
                      AND m.as_of = c.as_of
                      AND m.horizon_days = -1
               )
             ORDER BY c.as_of DESC
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (min(horizons),)).fetchall()

    def load_marks_for(
        self,
        ticker: str,
        expiry: date,
        put_strike: float,
        call_strike: float,
        mark_date: date,
        *,
        max_snap_days: int = 7,
    ) -> dict[str, Any] | None:
        """Grid IV for both strikes on the first session at or after mark_date.

        Snapping forward covers weekends and missed captures: a T+5 landing on
        a Saturday marks at the next session that has data. The snap is bounded
        by `max_snap_days` — an unbounded snap would silently mark a T+5
        against a session weeks later if the ticker dropped out of the surface,
        which is a different market, not a late mark.

        Returns the resolved `market_date` so the caller dates the row and
        computes dte_remaining from the session actually priced, never from the
        requested calendar date.
        """
        # Pick the earliest session in the window that ALREADY SATISFIES every
        # requirement (both strikes present, both IVs non-null, still before
        # expiry) — not merely the earliest session where the ticker has any
        # row at all. Filtering after choosing the date returns None whenever
        # the first session happens to be missing one strike, even though a
        # later session inside the cap has both. That is avoidable, non-random
        # censoring, and it correlates with exactly the illiquid names whose
        # marks matter most.
        sql = f"""
            SELECT
                g.market_date,
                MAX(g.underlying_spot) AS spot,
                MAX(g.put_iv)  FILTER (WHERE g.strike = %s) AS put_iv,
                MAX(g.call_iv) FILTER (WHERE g.strike = %s) AS call_iv
              FROM {self._schema}.option_surface_grid_daily g
             WHERE g.ticker = %s
               AND g.expiry = %s
               AND g.strike IN (%s, %s)
               AND g.market_date >= %s
               AND g.market_date <= %s
               AND g.market_date < %s
             GROUP BY g.market_date
            HAVING MAX(g.put_iv)  FILTER (WHERE g.strike = %s) IS NOT NULL
               AND MAX(g.call_iv) FILTER (WHERE g.strike = %s) IS NOT NULL
               AND MAX(g.underlying_spot) IS NOT NULL
             ORDER BY g.market_date ASC
             LIMIT 1
        """
        horizon_cap = mark_date + timedelta(days=max_snap_days)
        with self._conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                sql,
                (put_strike, call_strike,
                 ticker, expiry, put_strike, call_strike,
                 mark_date, horizon_cap, expiry,
                 put_strike, call_strike),
            ).fetchone()
        if not row or row["spot"] is None:
            return None
        if row["put_iv"] is None or row["call_iv"] is None:
            return None
        return row

    def load_settlement_close(
        self, ticker: str, expiry: date
    ) -> tuple[date, float] | None:
        """(settlement_date, close) — the last session at or BEFORE expiry.

        Used for the terminal at-expiry mark: by expiry the contract has left
        option_surface_grid_daily, so settlement intrinsic must come from
        daily_ohlc.

        Resolves BACKWARD, never forward. Snapping forward would settle a
        Friday option at Monday's close whenever expiry falls on a holiday or
        the bar is missing — information that did not exist at expiry, and a
        direct lookahead into the tail the terminal row exists to measure.
        Returns the resolved date so the row records the session actually
        used rather than the nominal expiry.

        Returns None when expiry has not been reached (no bar at or before it
        within the lookback), which correctly leaves the candidate pending.
        """
        sql = f"""
            SELECT date, close FROM {self._schema}.daily_ohlc
             WHERE ticker = %s AND date <= %s AND date >= %s
               AND close IS NOT NULL
             ORDER BY date DESC LIMIT 1
        """
        row = self._conn.execute(
            sql, (ticker, expiry, expiry - timedelta(days=7))
        ).fetchone()
        if not row or row[1] is None:
            return None
        return row[0], float(row[1])

    def has_session_after(self, ticker: str, on: date) -> bool:
        """Is there OHLC strictly after `on`? Guards the terminal mark.

        load_settlement_close resolves backward, so on a date that has simply
        not been reached it would happily return the most recent bar and settle
        the option early. Requiring a later session proves expiry is genuinely
        in the past before settling.
        """
        sql = f"""
            SELECT 1 FROM {self._schema}.daily_ohlc
             WHERE ticker = %s AND date > %s LIMIT 1
        """
        return self._conn.execute(sql, (ticker, on)).fetchone() is not None

    def upsert_markouts(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        cols = ", ".join(self._MARKOUT_COLUMNS)
        placeholders = ", ".join(["%s"] * len(self._MARKOUT_COLUMNS))
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in self._MARKOUT_COLUMNS
            if c not in ("ticker", "as_of", "horizon_days")
        )
        sql = f"""
            INSERT INTO {self._schema}.theta_harvester_markouts ({cols})
            VALUES ({placeholders})
            ON CONFLICT (ticker, as_of, horizon_days) DO UPDATE SET {updates}
        """
        params = [tuple(r[c] for c in self._MARKOUT_COLUMNS) for r in rows]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(rows)
```

- [ ] **Step 6: Add the markout job wrapper**

Append to `src/uw_scan/worker/jobs/theta_harvester.py`:

```python
def theta_harvester_markout(*, repo: Repository, settings: Settings) -> dict[str, Any]:
    """Re-mark existing candidates. Pure compute over the warm store; idempotent.

    This job only SCORES rows that already exist — it never creates candidates.
    After a wipe, or on first deploy, run
    scripts/backfill/theta_harvester_backfill.py or reads stay empty for weeks.
    """
    from uw_scan.reports.theta_harvester_markout import run_theta_markout

    th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
    return run_theta_markout(repo=th)
```

- [ ] **Step 7: Register the second cron**

In `src/uw_scan/worker/scheduler.py`, alongside the Task 6 registration:

```python
    def _theta_harvester_markout() -> None:
        with _repo(settings) as repo:
            theta_harvester_markout(repo=repo, settings=settings)
```

```python
            # Theta markout at 19:55 ET — 10 min after the scan, so the same
            # session's grid is available for any horizon coming due today.
            if settings.theta_harvester_enabled:
                sched.add_job(
                    _theta_harvester_markout,
                    CronTrigger.from_crontab("55 19 * * 0-4", timezone=settings.rth_tz),
                    id="theta_harvester_markout",
                    name="Theta Harvester forward markout",
                    max_instances=1,
                    coalesce=True,
                )
```

Update the import line to `from uw_scan.worker.jobs.theta_harvester import theta_harvester_markout, theta_harvester_scan`.

- [ ] **Step 8: Verify imports and run the full Python suite**

Run: `uv run python -c "import uw_scan.worker.scheduler; print('ok')" && uv run pytest tests/unit -q`
Expected: `ok`, then all unit tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/reports/theta_harvester_markout.py \
        src/uw_scan/storage/theta_harvester_repository.py \
        src/uw_scan/worker/jobs/theta_harvester.py \
        src/uw_scan/worker/scheduler.py \
        tests/unit/reports/test_theta_harvester_markout.py
git commit -m "feat(theta): forward markout compute, repository and 19:55 ET cron"
```

---

### Task 8: Historical backfill script

**Files:**
- Create: `scripts/backfill/theta_harvester_backfill.py`

**Interfaces:**
- Consumes: Tasks 5–7.
- Produces: a CLI — `uv run python scripts/backfill/theta_harvester_backfill.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--ticker SYM] [--dry-run]`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python
"""Replay Theta Harvester candidates over history, then score their markouts.

MANDATORY after first deploy or any wipe. The nightly markout job only SCORES
existing candidate rows — without this backfill the markout table stays empty
for weeks and every read looks like "no signal" rather than "no data". The
skew engine shipped with exactly this gap; do not repeat it.

Coverage floor is the intersection of option_surface_grid_daily and
exposures_by_expiry_strike. As of 2026-07-28 that is 2026-05-11 (the GEX
table), NOT the IV grid's 2026-01-02 — the dealer-support gate binds.

Reproduce:
    uv run python scripts/backfill/theta_harvester_backfill.py \
        --start 2026-05-11 --end 2026-07-24
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.theta_harvester_markout import run_theta_markout
from uw_scan.storage.repository import Repository
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository
from uw_scan.worker.jobs.theta_harvester import theta_harvester_scan

log = logging.getLogger("theta_backfill")


def _eligible_pairs(
    conn: psycopg.Connection, schema: str, start: date, end: date
) -> dict[date, list[str]]:
    """(session -> tickers) where BOTH surface and GEX exist FOR THAT TICKER.

    Per-ticker, not per-date. A date-level EXISTS check qualifies the whole
    session because one ticker happened to have GEX, and every other ticker
    then silently scores dealer_support='UNKNOWN' with a permanently failed
    gate — indistinguishable in the output from a real NO_SUPPORT reading.

    SURVIVORSHIP CAVEAT, stated because it cannot be fixed here: the universe
    is intersected against today's `watchlist WHERE removed_at IS NULL`. Names
    removed from the watchlist during the replay window are absent, and names
    added recently are replayed over sessions when they were not being tracked.
    argon does not store watchlist membership history, so this is a bias the
    backfill carries, not one it can correct. It runs in the optimistic
    direction: a name removed after a drawdown is exactly the kind of row whose
    losses are missing. Record the resolved universe in the run log so the
    measurement can be re-read later against a frozen list.
    """
    sql = f"""
        SELECT g.market_date, g.ticker
          FROM (
              SELECT DISTINCT market_date, ticker
                FROM {schema}.option_surface_grid_daily
               WHERE market_date BETWEEN %s AND %s
          ) g
          JOIN (
              SELECT DISTINCT market_date, ticker
                FROM {schema}.exposures_by_expiry_strike
               WHERE market_date BETWEEN %s AND %s
          ) e ON e.market_date = g.market_date AND e.ticker = g.ticker
          JOIN {schema}.watchlist w
            ON w.ticker = g.ticker AND w.removed_at IS NULL
         ORDER BY 1, 2
    """
    out: dict[date, list[str]] = {}
    for d, tk in conn.execute(sql, (start, end, start, end)).fetchall():
        out.setdefault(d, []).append(tk)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 5, 11))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--ticker", action="append", dest="tickers")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        th = ThetaHarvesterRepository(conn, schema=settings.db_schema)
        pairs = _eligible_pairs(conn, settings.db_schema, args.start, args.end)
        sessions = sorted(pairs)
        if not sessions:
            log.error(
                "no (ticker, session) pairs with BOTH surface + GEX coverage in %s..%s",
                args.start, args.end,
            )
            return 1
        log.info(
            "%d covered sessions: %s .. %s (%d ticker-sessions)",
            len(sessions), sessions[0], sessions[-1],
            sum(len(v) for v in pairs.values()),
        )
        if args.dry_run:
            for d in sessions[:3] + sessions[-3:]:
                log.info("  %s -> %d eligible tickers", d, len(pairs[d]))
            return 0

        total = 0
        for session in sessions:
            eligible = pairs[session]
            if args.tickers:
                eligible = [t for t in eligible if t in set(args.tickers)]
                if not eligible:
                    continue
            out = theta_harvester_scan(
                repo=repo, settings=settings, as_of=session, tickers=eligible
            )
            total += out["candidates_written"]
            log.info(
                "%s scanned=%d written=%d harvest=%d",
                session, out["tickers_scanned"],
                out["candidates_written"], out["harvest_count"],
            )

        marks = run_theta_markout(repo=th)
        log.info("backfill complete: %d candidates, %s", total, marks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

This mirrors `scripts/backfill/greek_exposure_daily_refresh_backfill.py:51` — `Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)`. There is no `Repository.connect` classmethod.

- [ ] **Step 2: Dry-run to confirm coverage detection**

Run: `uv run python scripts/backfill/theta_harvester_backfill.py --dry-run`
Expected: logs a session count with a first date at or after 2026-05-11. If it logs 0, stop — the coverage query or the local DB is wrong, and running the real backfill would write nothing.

- [ ] **Step 3: Backfill a single ticker as a smoke test**

Run: `uv run python scripts/backfill/theta_harvester_backfill.py --ticker AAPL --start 2026-06-01 --end 2026-07-24`
Expected: per-session log lines with `written=1` on most sessions, then a markout summary with `marks_written` > 0.

- [ ] **Step 4: Verify rows landed and P&L is not degenerate**

Run:
```bash
uv run python -c "
from uw_scan.config import Settings
import psycopg
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c:
    print('candidates', c.execute('select count(*), min(as_of), max(as_of) from uw_scan.theta_harvester_candidates').fetchone())
    print('markouts  ', c.execute('select horizon_days, count(*), round(avg(pnl_pct_of_credit),2) from uw_scan.theta_harvester_markouts group by 1 order by 1').fetchall())
    print('verdicts  ', c.execute('select verdict, count(*) from uw_scan.theta_harvester_candidates group by 1').fetchall())
"
```
Expected: non-zero candidate count; markout rows across several horizons with a mean `pnl_pct_of_credit` that is neither exactly 0 nor exactly 100 (either would mean the marks are not moving and the join is wrong).

Three assertions this step must actually check, not eyeball:
- **`WATCHLIST` and `DIRECTIONAL_DISGUISE` rows are present.** If they are absent, the scan is filtering before upsert and the comparison group is gone. **Do NOT assert that `THETA_HARVEST` rows exist** — zero harvest rows is a legitimate market outcome over a 55-session window, not proof of a regression. The greek-sign regression is guarded by the frozen unit test in Task 3, which is where a data-independent invariant belongs; asserting it against live market data would make the suite fail for reasons that have nothing to do with the code.
- **`horizon_days = -1` rows exist** for candidates whose expiry has passed. No terminal rows means settlement is never observed and the markout is truncated above.
- **`mark_date` is a weekday** on every row — `select count(*) from uw_scan.theta_harvester_markouts where extract(dow from mark_date) in (0,6)` must return 0. A non-zero count means the snap-forward is not being used and rows are dated to calendar offsets.

- [ ] **Step 4b: Read the signal against its control, not against zero**

Run:
```bash
uv run python -c "
from uw_scan.config import Settings
import psycopg
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c:
    print(c.execute('''
      select k.verdict, m.horizon_days, count(*) n,
             round(avg(m.pnl_pct_of_credit),2) mean_pnl,
             round(percentile_cont(0.05) within group (order by m.pnl_pct_of_credit)::numeric,2) p05,
             round(min(m.pnl_pct_of_credit),2) worst
        from uw_scan.theta_harvester_markouts m
        join uw_scan.theta_harvester_candidates k
          on k.ticker=m.ticker and k.as_of=m.as_of
       group by 1,2 order by 2,1
    ''').fetchall())
"
```
Expected: a table you can read as "does `THETA_HARVEST` beat the other verdicts at the same horizon". Record the output in the PR description. **A positive mean on the harvest rows alone is not evidence** — short vol is positive-expectancy in most windows. Report `p05` and `worst` alongside every mean: a strategy whose worst trade is −8× the median credit is a different animal from one whose worst is −1.5×, at the same mean. With ~55 sessions and 30-day horizons the effective N is roughly two non-overlapping windows, so treat every number here as directional only.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill/theta_harvester_backfill.py
git commit -m "feat(theta): historical candidate + markout backfill script"
```

---

### Task 9: API endpoints

**Files:**
- Create: `src/uw_scan/api/models/theta_harvester.py`
- Modify: `src/uw_scan/api/routers/scanner.py`
- Test: `tests/integration/test_theta_harvester_api.py`

**Interfaces:**
- Consumes: Tasks 5 and 7.
- Produces three endpoints:
  - `GET /api/scanner/theta-harvester?as_of=&limit=` → `ThetaHarvesterResponse`
  - `POST /api/scanner/theta-harvester/rescan` → `ThetaHarvesterScanResult`
  - `POST /api/scanner/theta-harvester/quote` → `ThetaHarvesterQuoteResult`
- Response models: `ThetaHarvesterCandidate`, `ThetaHarvesterResponse{as_of, generated_at, candidates}`, `ThetaHarvesterScanResult{as_of, tickers_scanned, candidates_written, harvest_count}`, `ThetaHarvesterQuoteResult{quoted, failed}`

- [ ] **Step 1: Write the response models**

```python
# src/uw_scan/api/models/theta_harvester.py
"""Theta Harvester API contract models."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ThetaHarvesterCandidate(BaseModel):
    ticker: str
    as_of: date
    expiry: date
    dte: int
    put_strike: float
    call_strike: float
    underlying_spot: float
    entry_credit_theo: float
    credit_ib: float | None = None
    credit_quoted_at: datetime | None = None
    credit_source: str | None = None
    net_delta: float
    theta: float
    gamma: float
    vega: float
    score: float
    verdict: str
    iv: float | None = None
    hv20: float | None = None
    hv60: float | None = None
    iv_rv_edge: float | None = None
    iv_rv_ratio: float | None = None
    trend_20d_pct: float | None = None
    range_score: float | None = None
    dealer_support: str | None = None
    net_gex: float | None = None
    gex_flip: float | None = None
    gate_delta_near_zero: bool
    gate_iv_rich_vs_rv: bool
    gate_dealer_support: bool
    gate_theta_positive: bool
    gate_gamma_controlled: bool
    gate_range_bound: bool


class ThetaHarvesterResponse(BaseModel):
    as_of: date | None
    generated_at: datetime
    candidates: list[ThetaHarvesterCandidate]


class ThetaHarvesterScanResult(BaseModel):
    as_of: str | None
    tickers_scanned: int
    candidates_written: int
    harvest_count: int


class ThetaHarvesterQuoteResult(BaseModel):
    quoted: int
    failed: int
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_theta_harvester_api.py
"""Theta Harvester API contract."""

from datetime import date


def test_get_returns_empty_payload_before_any_scan(api_client):
    r = api_client.get("/api/scanner/theta-harvester")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == []
    assert body["as_of"] is None


def test_get_returns_persisted_candidates_scored_high_first(api_client, seeded_candidates):
    r = api_client.get("/api/scanner/theta-harvester")
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == str(date(2026, 7, 24))
    scores = [c["score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)
    assert body["candidates"][0]["credit_ib"] is None


def test_get_honours_the_limit_parameter(api_client, seeded_candidates):
    r = api_client.get("/api/scanner/theta-harvester?limit=1")
    assert len(r.json()["candidates"]) == 1


def test_quote_refuses_to_exceed_the_ib_line_budget(api_client, seeded_candidates):
    # The IB cap is shared with the spot feed; an unbounded quote loop would
    # starve it. Over-large requests are rejected, not silently truncated.
    r = api_client.post("/api/scanner/theta-harvester/quote", json={"limit": 50})
    assert r.status_code == 400
    assert "8" in r.json()["detail"]
```

Use the project's existing API test-client fixture — check `tests/integration/conftest.py` for its name and adapt. Add a `seeded_candidates` fixture there that inserts two rows via `ThetaHarvesterRepository.upsert_candidates` using the `_candidate()` builder from Task 5's test.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_theta_harvester_api.py -v`
Expected: FAIL — 404 on every route.

- [ ] **Step 4: Write the endpoints**

Append to `src/uw_scan/api/routers/scanner.py` (add the model imports plus `from pydantic import BaseModel`, `from datetime import date as _date`, and `from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository`):

```python
# Advisory-lock keys. Arbitrary but must not collide with the existing keys in
# routers/volatility.py or routers/stock.py — grep before changing.
_THETA_SCAN_LOCK = "hashtext('theta_harvester_scan')"
_THETA_QUOTE_LOCK = "hashtext('theta_harvester_quote')"

# Per-leg IB timeout. 8 candidates x 2 legs = 16 SERIAL calls, so the default
# 8.0s would put the worst case at ~128s — past most proxy/browser timeouts.
# 4.0s bounds it at ~64s. If this still feels slow in practice, move the quote
# to /jobs with polling rather than raising the cap or parallelising: the IB
# ~100-line market-data budget is shared with xenon and is the real constraint.
_QUOTE_TIMEOUT_S = 4.0

_QUOTE_MAX = 8  # hard ceiling: 8 candidates x 2 legs = 16 serial IB subprocess
                # calls against a ~100-line cap shared with the spot WS feed.


class ThetaQuoteRequest(BaseModel):
    limit: int = _QUOTE_MAX
    as_of: _date | None = None


@router.get("/theta-harvester", response_model=ThetaHarvesterResponse)
def theta_harvester(
    as_of: _date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ThetaHarvesterResponse:
    """Read the persisted candidates. Pure warm-store read; no UW, no IB."""
    th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
    target = as_of or th.latest_as_of()
    rows = th.read_candidates(as_of=target, limit=limit) if target else []
    return ThetaHarvesterResponse(
        as_of=target,
        generated_at=_now_utc(),
        candidates=[ThetaHarvesterCandidate(**dict(r)) for r in rows],
    )


@router.post("/theta-harvester/rescan", response_model=ThetaHarvesterScanResult)
def theta_harvester_rescan(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ThetaHarvesterScanResult:
    """Recompute candidates synchronously.

    A deliberate write on the otherwise read-only scanner router — the same
    exception already made for POST /stock/{ticker}/technicals/refresh. It is
    safe to run inline because the ranking path is pure warm-store SQL with no
    network call, so it finishes in well under a request timeout.

    `src/uw_scan/api/CLAUDE.md` requires mutations to take
    `pg_try_advisory_lock` for single-flight; this mirrors
    routers/stock.py::technicals_refresh exactly. Without it, two clicks race
    two full watchlist sweeps writing the same (ticker, as_of) rows.
    """
    from uw_scan.worker.jobs.theta_harvester import theta_harvester_scan

    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT pg_try_advisory_lock({_THETA_SCAN_LOCK})")
        acquired = bool(cur.fetchone()[0])
    if not acquired:
        raise HTTPException(status_code=409, detail="a theta scan is already running")
    try:
        return ThetaHarvesterScanResult(
            **theta_harvester_scan(repo=repo, settings=settings)
        )
    finally:
        with repo.conn.cursor() as cur:
            cur.execute(f"SELECT pg_advisory_unlock({_THETA_SCAN_LOCK})")


@router.post("/theta-harvester/quote", response_model=ThetaHarvesterQuoteResult)
def theta_harvester_quote(
    payload: ThetaQuoteRequest | None = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ThetaHarvesterQuoteResult:
    """Fetch live IB NBBO for the top-N candidates' legs, serially.

    Bounded at 8 candidates on purpose: each leg spawns an IB snapshot
    subprocess (~2-5 s) and consumes one of the shared ~100-line market-data
    lines. This is never called from a scheduled job.
    """
    from uw_scan.sources.xenon_query import fetch_ib_option_quote

    req = payload or ThetaQuoteRequest()
    if req.limit > _QUOTE_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"limit exceeds the IB line budget; max {_QUOTE_MAX} candidates",
        )

    # Single-flight per api/CLAUDE.md. Doubly important here: concurrent
    # requests would multiply draws on the shared ~100-line IB market-data cap,
    # which xenon also depends on.
    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT pg_try_advisory_lock({_THETA_QUOTE_LOCK})")
        if not bool(cur.fetchone()[0]):
            raise HTTPException(
                status_code=409, detail="a theta quote request is already running"
            )

    th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
    target = req.as_of or th.latest_as_of()
    if target is None:
        return ThetaHarvesterQuoteResult(quoted=0, failed=0)

    quoted = failed = 0
    for row in th.read_candidates(as_of=target, limit=req.limit):
        expiry = row["expiry"].strftime("%Y%m%d")
        legs = []
        for strike, right in (
            (float(row["put_strike"]), "P"),
            (float(row["call_strike"]), "C"),
        ):
            legs.append(
                fetch_ib_option_quote(
                    base_url=settings.xenon_query_api_url,
                    api_key=(
                        settings.xenon_query_api_key.get_secret_value()
                        if settings.xenon_query_api_key is not None
                        else None
                    ),
                    symbol=row["ticker"],
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    timeout_s=_QUOTE_TIMEOUT_S,
                )
            )
        mids = []
        for leg in legs:
            if not leg or leg.get("bid") is None or leg.get("ask") is None:
                mids = []
                break
            mids.append((float(leg["bid"]) + float(leg["ask"])) / 2.0)
        if len(mids) == 2:
            th.set_ib_credit(
                row["ticker"], target, credit=sum(mids), source="xenon_ib"
            )
            quoted += 1
        else:
            failed += 1

    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT pg_advisory_unlock({_THETA_QUOTE_LOCK})")
    return ThetaHarvesterQuoteResult(quoted=quoted, failed=failed)
```

Wrap the body after the lock acquisition in `try: ... finally:` so the unlock
runs even if a leg raises — `fetch_ib_option_quote` is never-raise, but
`set_ib_credit` can fail on a DB error and a leaked session-level advisory lock
would block every later quote until the connection is recycled.

Add `HTTPException` to the `fastapi` import line.

Verified 2026-07-28 — these are correct as written, no grepping needed:
- `settings.xenon_query_api_url` — `str`, default `http://127.0.0.1:8321` (`config.py:425`)
- `settings.xenon_query_api_key` — `SecretStr | None` (`config.py:426`), so the
  `.get_secret_value()` unwrap with a `None` guard above is required; passing the
  `SecretStr` itself sends the literal `SecretStr('**********')` as the header and
  every quote 401s silently into `failed`.
- `fetch_ib_option_quote` is keyword-only with exactly `base_url, api_key, symbol,
  expiry, strike, right` (`sources/xenon_query.py:68`), and `expiry` is the
  `YYYYMMDD` string the `strftime` above produces.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_theta_harvester_api.py -v`
Expected: all 4 PASS.

- [ ] **Step 6: Regenerate types surgically**

Run: `cd web && npm run gen:types`
Then `git diff web/lib/types.ts` — the diff must contain ONLY the new `ThetaHarvester*` schemas and the three new paths. If unrelated lines moved, revert and hand-add the new entries in alphabetical position instead.

- [ ] **Step 7: Run the OpenAPI snapshot check**

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`

The snapshot test lives at `tests/integration/api/test_openapi_snapshot.py`
(verified 2026-07-28) — **not** under `tests/unit`, so `-k openapi` there
silently selects zero tests and passes. Three new endpoints change the
contract, so `tests/integration/api/openapi.snapshot.json` must be updated
**surgically** (insert only the new paths/components in their existing
alphabetical positions) and added to this task's `git add` list. Do not
regenerate the whole snapshot; it is 668 KB and a full regen buries the real
diff. The same applies to `web/lib/types.ts`.
Expected: PASS. If it fails on an intentional addition, update the snapshot surgically.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/api/models/theta_harvester.py src/uw_scan/api/routers/scanner.py \
        tests/integration/test_theta_harvester_api.py web/lib/types.ts
git commit -m "feat(theta): scanner API read, rescan and bounded IB quote endpoints"
```

---

### Task 10: Web sub-tab shell

**Files:**
- Create: `web/app/scanner/[[...tab]]/page.tsx`
- Create: `web/components/scanner/ScannerPanel.tsx`
- Create: `web/components/scanner/FlowSubTab.tsx`
- Delete: `web/app/scanner/page.tsx`
- **Leave alone: `web/app/scanner/loading.tsx`** — see note below
- Modify: `web/lib/api.ts`

**Route-shape note (verified 2026-07-28):** `web/app/regime/` contains *only*
`[[...tab]]/page.tsx` with no sibling `page.tsx` — an optional catch-all already
matches the bare `/regime` path, so keeping both would be a Next.js route conflict.
Mirror that exactly: `web/app/scanner/page.tsx` is **deleted**, not kept alongside.

`web/app/scanner/loading.tsx` exists (regime has no equivalent). Do **not** delete or
move it: a `loading.tsx` at a segment wraps that segment *and its nested routes*, so
it keeps working as the Suspense boundary once the page moves into `[[...tab]]/`.
Moving a copy into `[[...tab]]/` would double-wrap.

**Interfaces:**
- Consumes: Task 9's endpoints.
- Produces: `ScannerPanel({ initialTab }: { initialTab?: string })` with tabs `"flow" | "theta"`; `api.thetaHarvester(qs?)`, `api.thetaHarvesterRescan()`, `api.thetaHarvesterQuote(limit)`.

- [ ] **Step 1: Move the existing scanner body into a sub-tab**

Move the entire default export body of `web/app/scanner/page.tsx` into a new server component `web/components/scanner/FlowSubTab.tsx` exporting `export default async function FlowSubTab({ params }: { params: Record<string, string | string[] | undefined> })`. Keep all existing logic — `groupByBias`, `groupDiscoveredByBias`, the filters, the discover section — byte-for-byte. The only change is the function name, the props shape, and dropping the outer `<h1>SCANNER</h1>` header (the shell owns it now).

- [ ] **Step 2: Write the route**

```tsx
// web/app/scanner/[[...tab]]/page.tsx
import ScannerPanel from "@/components/scanner/ScannerPanel";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Scanner — Unusual Whales",
  description: "Flow scanner and Theta Harvester short-strangle candidates",
};

const VALID_TABS = new Set(["flow", "theta"]);

export default async function ScannerPage({
  params,
  searchParams,
}: {
  params: Promise<{ tab?: string[] }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { tab } = await params;
  const query = await searchParams;
  const first = tab?.[0];
  const initialTab = first && VALID_TABS.has(first) ? first : "flow";
  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <header style={{ marginBottom: 16 }}>
        <h1
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 24,
            letterSpacing: 1,
          }}
        >
          SCANNER
        </h1>
      </header>
      <ScannerPanel initialTab={initialTab} searchParams={query} />
    </div>
  );
}
```

- [ ] **Step 3: Write the tab strip**

```tsx
// web/components/scanner/ScannerPanel.tsx
"use client";

import { useEffect, useState } from "react";
import ThetaSubTab from "./theta/ThetaSubTab";

type ScannerTab = "flow" | "theta";

const TABS: { id: ScannerTab; label: string }[] = [
  { id: "flow", label: "Flow" },
  { id: "theta", label: "Theta Harvester" },
];

const VALID = new Set<ScannerTab>(TABS.map((t) => t.id));

function coerce(tab: string | undefined): ScannerTab {
  return tab && VALID.has(tab as ScannerTab) ? (tab as ScannerTab) : "flow";
}

export default function ScannerPanel({
  initialTab,
  flowContent,
}: {
  initialTab?: string;
  flowContent?: React.ReactNode;
}) {
  // Mirrors RegimePanel: local state renders instantly, the URL is kept in
  // sync via pushState + a popstate listener so deep-links and back/forward
  // both work without an RSC round-trip per tab click.
  const [activeTab, setActiveTab] = useState<ScannerTab>(coerce(initialTab));
  const [seenInitial, setSeenInitial] = useState(initialTab);
  if (initialTab !== seenInitial) {
    setSeenInitial(initialTab);
    setActiveTab(coerce(initialTab));
  }

  useEffect(() => {
    function onPop() {
      setActiveTab(coerce(window.location.pathname.split("/")[2]));
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function selectTab(id: ScannerTab) {
    setActiveTab(id);
    if (typeof window !== "undefined") {
      window.history.pushState(null, "", `/scanner/${id}`);
    }
  }

  return (
    <div data-testid="scanner-panel">
      <div
        className="ticker-tabs"
        style={{ marginBottom: 16, flexWrap: "wrap" }}
        data-testid="scanner-tabs"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={activeTab === t.id ? "active" : ""}
            onClick={() => selectTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {activeTab === "flow" ? flowContent : <ThetaSubTab />}
    </div>
  );
}
```

Because `FlowSubTab` is an async server component, the route must render it and pass it down as the `flowContent` slot rather than importing it inside the client component. Update the route's `<ScannerPanel>` usage to:

```tsx
      <ScannerPanel
        initialTab={initialTab}
        flowContent={<FlowSubTab params={query} />}
      />
```

and add `import FlowSubTab from "@/components/scanner/FlowSubTab";` to the route.

- [ ] **Step 4: Add the API client methods**

In `web/lib/api.ts`, following the existing method style:

Verified 2026-07-28: `web/lib/api.ts` has **no** `get`/`post` helpers. The only
helper is `_fetch<T>(path, init?, options?)` at `web/lib/api.ts:101`, and POSTs
pass `{ method, body: JSON.stringify(...) }` through `init`. Use exactly this:

```ts
  thetaHarvester: (
    params: URLSearchParams = new URLSearchParams(),
  ): Promise<ThetaHarvesterResponse> => {
    const q = params.toString();
    return _fetch<ThetaHarvesterResponse>(
      `/api/scanner/theta-harvester${q ? `?${q}` : ""}`,
    );
  },
  thetaHarvesterRescan: (): Promise<ThetaHarvesterScanResult> =>
    _fetch<ThetaHarvesterScanResult>("/api/scanner/theta-harvester/rescan", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  thetaHarvesterQuote: (limit: number): Promise<ThetaHarvesterQuoteResult> =>
    _fetch<ThetaHarvesterQuoteResult>("/api/scanner/theta-harvester/quote", {
      method: "POST",
      body: JSON.stringify({ limit }),
    }),
```

Add the three response aliases beside the existing `type ... = Json<...>` block
(`web/lib/api.ts:95-99`), following that exact form:

```ts
type ThetaHarvesterResponse = Json<"/api/scanner/theta-harvester", "get">;
type ThetaHarvesterScanResult = Json<"/api/scanner/theta-harvester/rescan", "post">;
type ThetaHarvesterQuoteResult = Json<"/api/scanner/theta-harvester/quote", "post">;
```

- [ ] **Step 5: Verify the existing scanner still renders**

Run: `cd web && npm run build`
Expected: build succeeds. Then start the stack and load `http://localhost:3001/scanner` — the Flow tab must render exactly as before the move.

- [ ] **Step 6: Commit**

```bash
git add web/app/scanner web/components/scanner/ScannerPanel.tsx \
        web/components/scanner/FlowSubTab.tsx web/lib/api.ts
git rm web/app/scanner/page.tsx
git commit -m "feat(scanner): sub-tab shell, existing scanner becomes the Flow tab"
```

---

### Task 11: Theta sub-tab UI

**Files:**
- Create: `web/components/scanner/theta/ThetaSubTab.tsx`
- Test: `web/tests/unit/thetaSubTab.test.tsx`

**Interfaces:**
- Consumes: Task 10's `api.thetaHarvester*`; Task 9's response shapes.
- Produces: `ThetaSubTab()` default export, plus named `formatCredit`, `verdictLabel` for unit testing.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/thetaSubTab.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ThetaSubTab, {
  formatCredit,
  verdictLabel,
} from "@/components/scanner/theta/ThetaSubTab";

// ThetaSubTab fetches on mount. Stub the client so the render test exercises
// the warning banner, not the network — vitest runs with no API available.
vi.mock("@/lib/api", () => ({
  api: {
    thetaHarvester: () => Promise.resolve({ as_of: null, candidates: [] }),
    thetaHarvesterRescan: () => Promise.resolve({}),
    thetaHarvesterQuote: () => Promise.resolve({}),
  },
}));

describe("verdictLabel", () => {
  it("shortens the three radon verdicts for a dense table", () => {
    expect(verdictLabel("THETA_HARVEST")).toBe("TRUE THETA");
    expect(verdictLabel("DIRECTIONAL_DISGUISE")).toBe("DIRECTIONAL");
    expect(verdictLabel("WATCHLIST")).toBe("WATCH");
  });

  it("passes an unknown verdict through rather than blanking the cell", () => {
    expect(verdictLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });
});

describe("research-only warning", () => {
  it("is rendered — the DB table COMMENT is invisible to the operator", () => {
    render(<ThetaSubTab />);
    const warn = screen.getByTestId("theta-research-warning");
    expect(warn.textContent).toMatch(/undefined risk/i);
    expect(warn.textContent).toMatch(/not an argon trade proposal/i);
  });
});

describe("formatCredit", () => {
  it("marks a theoretical credit so it is never mistaken for a fill", () => {
    expect(formatCredit(4.15, null)).toBe("$4.15 theo");
  });

  it("prefers the live IB quote when one exists", () => {
    expect(formatCredit(4.15, 3.9)).toBe("$3.90 IB");
  });

  it("renders an em dash when there is no mark at all", () => {
    expect(formatCredit(null, null)).toBe("—");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- thetaSubTab`
Expected: FAIL — cannot resolve the module.

- [ ] **Step 3: Write the component**

```tsx
// web/components/scanner/theta/ThetaSubTab.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

type Candidate = components["schemas"]["ThetaHarvesterCandidate"];

const QUOTE_LIMIT = 8; // matches the API's IB line budget; see routers/scanner.py

export function verdictLabel(verdict: string): string {
  if (verdict === "THETA_HARVEST") return "TRUE THETA";
  if (verdict === "DIRECTIONAL_DISGUISE") return "DIRECTIONAL";
  if (verdict === "WATCHLIST") return "WATCH";
  return verdict;
}

export function formatCredit(
  theo: number | null,
  ib: number | null | undefined,
): string {
  // The theo/IB suffix is load-bearing: the theoretical mark is the markout
  // basis and the IB quote is a live NBBO. Showing a bare number would let a
  // reader treat a model price as a fill.
  if (ib != null) return `$${ib.toFixed(2)} IB`;
  if (theo != null) return `$${theo.toFixed(2)} theo`;
  return "—";
}

const GATE_KEYS: { key: keyof Candidate; label: string }[] = [
  { key: "gate_delta_near_zero", label: "DELTA" },
  { key: "gate_iv_rich_vs_rv", label: "IV RICH" },
  { key: "gate_dealer_support", label: "DEALER" },
  { key: "gate_theta_positive", label: "THETA" },
];

export default function ThetaSubTab() {
  const [rows, setRows] = useState<Candidate[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "scan" | "quote">("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.thetaHarvester();
      setRows(data.candidates);
      setAsOf(data.as_of);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function rescan() {
    setBusy("scan");
    try {
      await api.thetaHarvesterRescan();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "rescan failed");
    } finally {
      setBusy("");
    }
  }

  async function quote() {
    setBusy("quote");
    try {
      await api.thetaHarvesterQuote(QUOTE_LIMIT);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "quote failed");
    } finally {
      setBusy("");
    }
  }

  return (
    <div data-testid="theta-subtab">
      {/* Required by the plan's Global Constraints. The table COMMENT saying
          "research artifact, not a trade proposal" is invisible to whoever is
          looking at this screen, and a row labelled TRUE THETA next to a live
          IB credit reads as a recommendation. A short strangle is undefined
          risk on both sides and violates argon's no-naked-shorts rule. */}
      <div
        data-testid="theta-research-warning"
        style={{
          border: "1px solid var(--warn, #a86)",
          background: "var(--warn-bg, rgba(170,136,102,0.08))",
          padding: "8px 12px",
          marginBottom: 12,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        RESEARCH MEASUREMENT ONLY — naked short strangle, undefined risk on both
        sides. Not an Argon trade proposal, not sized, not executable. Credits
        shown are model marks or IB midpoints, not fills.
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
          {asOf ? `AS OF ${asOf}` : "NO DATA"} · {rows.length} candidates
        </span>
        <button type="button" onClick={rescan} disabled={busy !== ""}>
          {busy === "scan" ? "Scanning…" : "Rescan"}
        </button>
        <button type="button" onClick={quote} disabled={busy !== "" || !rows.length}>
          {busy === "quote" ? "Quoting…" : `Quote top ${QUOTE_LIMIT} (IB)`}
        </button>
      </div>

      {error ? <p style={{ color: "var(--negative)" }}>{error}</p> : null}

      <table style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 13 }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--text-muted)" }}>
            <th>Ticker</th>
            <th>Structure</th>
            <th>Score</th>
            <th>Theta $/day</th>
            <th>Net Δ</th>
            <th>IV/RV</th>
            <th>Dealer</th>
            <th>Range</th>
            <th>DTE</th>
            <th>Credit</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={`${c.ticker}-${c.as_of}`}>
              <td>{c.ticker}</td>
              <td>
                {`SHORT ${c.put_strike}P / ${c.call_strike}C`}
                <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                  {GATE_KEYS.map((g) => (
                    <span
                      key={g.label}
                      style={{
                        fontSize: 10,
                        color: c[g.key]
                          ? "var(--positive)"
                          : "var(--text-muted)",
                      }}
                    >
                      {g.label}
                    </span>
                  ))}
                </div>
              </td>
              <td>{c.score.toFixed(0)}</td>
              <td>{(c.theta * 100).toFixed(2)}</td>
              <td>{c.net_delta.toFixed(3)}</td>
              <td>
                {c.iv_rv_edge != null ? `${c.iv_rv_edge.toFixed(1)}pt` : "—"}
              </td>
              <td>{c.dealer_support ?? "—"}</td>
              <td>
                {c.range_score != null ? c.range_score.toFixed(2) : "—"}
              </td>
              <td>{c.dte}</td>
              <td>{formatCredit(c.entry_credit_theo, c.credit_ib)}</td>
              <td>{verdictLabel(c.verdict)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- thetaSubTab`
Expected: all 6 PASS.

- [ ] **Step 5: Full web checks**

Run: `cd web && npm run test && npm run build`
Expected: all tests pass, build succeeds.

- [ ] **Step 6: Verify in the real app**

Start the stack (`bash scripts/dev.sh`), load `http://localhost:3001/scanner/theta`, and confirm:
- the table renders backfilled candidates with an AS OF date
- clicking Rescan updates the row count without an error
- clicking Quote populates at least one Credit cell with an `IB` suffix (requires `XENON_QUERY_API_KEY` set and xenon reachable; if it is not, the cells stay `theo` and the response reports `failed` — that is correct behaviour, not a bug)

Screenshots, if taken, go under `output/playwright/`.

- [ ] **Step 7: Commit**

```bash
git add web/components/scanner/theta/ThetaSubTab.tsx web/tests/unit/thetaSubTab.test.tsx
git commit -m "feat(theta): Theta Harvester sub-tab table with rescan and IB quote"
```

---

### Task 12: Weight sweep + control arm (the "does the score do anything" test)

**Files:**
- Create: `scripts/research/theta_harvester_weight_sweep.py`
- Test: `tests/unit/test_theta_harvester_sweep.py`

**Interfaces:**
- Consumes: `score_from_components`, `ScoreWeights`, `DEFAULT_WEIGHTS`, `RADON_WEIGHTS` (Task 4); `theta_harvester_candidates` + `theta_harvester_markouts` populated by Task 8's backfill; `uw_scan.backtest.{run_sweep, monthly_summary, walkforward_gate, quarter_gate}`; `storage/backtest_repository.BacktestRepository`
- Produces: rows in `backtest_sweep_runs` / `backtest_sweep_results` under `strategy='theta_harvester_weights'`

**Why this task exists.** Tasks 1--11 build a scanner whose weights are asserted.
This task is the only thing in the plan that can tell you whether the score
carries information. It is cheap because the score is a pure function of three
persisted columns: **every config is a re-scoring pass over rows already in
Postgres. No rescan, no UW call, no IB call.**

It also supplies the control arm whose absence is called out in the
Interpretation constraints. Three named configs are always in the grid:

| Config | What it answers |
|---|---|
| `unconditional` | Take EVERY candidate row regardless of verdict. This is the null: short vol pays in most windows. |
| `radon` | `RADON_WEIGHTS` -- radon's shipped weights and its critical dealer gate. |
| `default` | `DEFAULT_WEIGHTS` -- the reweight this plan proposes. |

**If `default` does not beat `unconditional` out-of-sample, the score adds
nothing and that is the finding.** Write it in the notes and leave the feature
as a diagnostic. Do not re-sweep until the finding is disliked less.

**Return definition.** Per candidate, the terminal (`horizon_days = -1`) markout
`pnl` divided by the candidate's `underlying_spot`. Dividing by
`entry_credit_theo` instead would report a leverage artifact -- a 5-cent credit
that loses 5 cents is -100%, which swamps every aggregate. Spot-normalised P&L
is dimensionless and comparable across names. It is **not** a strategy return:
same-close entry and no bid-ask, per the Interpretation constraints.

- [ ] **Step 1: Write the failing test**

```python
"""tests/unit/test_theta_harvester_sweep.py -- pure, no DB."""
from datetime import date

import pytest

from uw_scan.scanners.theta_harvester import DEFAULT_WEIGHTS, RADON_WEIGHTS
from scripts.research.theta_harvester_weight_sweep import (
    Row,
    build_grid,
    evaluate_config,
    selected_rows,
)


def _row(edge: float, nd: float, rs: float, ret: float, *, dealer: str = "SUPPORT",
         as_of: date = date(2026, 3, 2)) -> Row:
    return Row(
        ticker="IWM", as_of=as_of, iv_rv_edge=edge, iv_rv_ratio=1.5,
        net_delta=nd, range_score=rs, dealer_support=dealer,
        theta_positive=True, ret=ret,
    )


def test_unconditional_takes_every_row():
    rows = [_row(0.0, 0.5, 0.0, -0.01), _row(30.0, 0.0, 1.0, 0.02)]
    assert len(selected_rows(rows, config={"kind": "unconditional"})) == 2


def test_weighted_config_filters_on_score_and_gates():
    rows = [
        _row(30.0, 0.0, 1.0, 0.02),   # max score, clears everything
        _row(0.0, 0.5, 0.0, -0.01),   # fails the iv gate AND the delta gate
    ]
    kept = selected_rows(rows, config={"kind": "weights", **DEFAULT_WEIGHTS.__dict__})
    assert [r.ret for r in kept] == [0.02]


def test_dealer_gate_only_bites_when_critical():
    rows = [_row(30.0, 0.0, 1.0, 0.02, dealer="NO_SUPPORT")]
    assert selected_rows(rows, config={"kind": "weights", **DEFAULT_WEIGHTS.__dict__})
    assert not selected_rows(rows, config={"kind": "weights", **RADON_WEIGHTS.__dict__})


def test_evaluate_reports_effective_n_not_row_count():
    # 40 rows but only two distinct entry months -> effective N is months, and
    # the naive row count must never be what a Sharpe is computed over.
    rows = [_row(30.0, 0.0, 1.0, 0.01, as_of=date(2026, 3, d))
            for d in range(2, 22)]
    rows += [_row(30.0, 0.0, 1.0, 0.01, as_of=date(2026, 4, d))
             for d in range(2, 22)]
    out = evaluate_config(rows, config={"kind": "unconditional"})
    assert out["n_trades"] == 40
    assert out["metrics"]["effective_n_months"] == 2


def test_empty_selection_returns_metrics_not_an_exception():
    out = evaluate_config([], config={"kind": "unconditional"})
    assert out["n_trades"] == 0
    assert out["metrics"]["sharpe"] is None


def test_grid_always_contains_the_three_named_configs():
    kinds = {c.get("name") for c in build_grid()}
    assert {"unconditional", "radon", "default"} <= kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_theta_harvester_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: scripts.research.theta_harvester_weight_sweep`

- [ ] **Step 3: Write the sweep script**

```python
"""scripts/research/theta_harvester_weight_sweep.py

Re-score every persisted theta-harvester candidate under a grid of
ScoreWeights and measure the terminal markout of the rows each config would
have selected. Pure re-scoring: no rescan, no UW, no IB.

Reproduce:
    uv run python scripts/research/theta_harvester_weight_sweep.py

Reads:  uw_scan.theta_harvester_candidates JOIN theta_harvester_markouts
        (horizon_days = -1, the at-expiry settlement mark)
Writes: uw_scan.backtest_sweep_runs / _results, strategy='theta_harvester_weights'

READ THE INTERPRETATION CONSTRAINTS in
docs/superpowers/plans/2026-07-28-theta-harvester-scanner.md before quoting a
number from this. In particular: entry is same-close (a lookahead), the P&L
carries no bid-ask, and effective N is months, not rows.
"""

from __future__ import annotations

import itertools
import logging
import subprocess
from dataclasses import dataclass
from datetime import date

import psycopg

from uw_scan.backtest import monthly_summary, run_sweep, walkforward_gate
from uw_scan.config import Settings
from uw_scan.scanners.theta_harvester import (
    DEFAULT_WEIGHTS,
    NEAR_ZERO_DELTA,
    RADON_WEIGHTS,
    ScoreWeights,
    score_from_components,
)
from uw_scan.storage.backtest_repository import BacktestRepository

log = logging.getLogger(__name__)

STRATEGY = "theta_harvester_weights"
REPRODUCE = "uv run python scripts/research/theta_harvester_weight_sweep.py"

_SQL = """
    SELECT c.ticker, c.as_of, c.iv_rv_edge, c.iv_rv_ratio, c.net_delta,
           c.range_score, c.dealer_support, c.gate_theta_positive,
           m.pnl / NULLIF(c.underlying_spot, 0) AS ret
      FROM uw_scan.theta_harvester_candidates c
      JOIN uw_scan.theta_harvester_markouts m
        ON m.ticker = c.ticker AND m.as_of = c.as_of AND m.horizon_days = -1
     WHERE c.iv_rv_edge IS NOT NULL
       AND c.range_score IS NOT NULL
       AND m.pnl IS NOT NULL
       AND c.underlying_spot > 0
     ORDER BY c.as_of, c.ticker
"""


@dataclass(frozen=True)
class Row:
    ticker: str
    as_of: date
    iv_rv_edge: float
    iv_rv_ratio: float
    net_delta: float
    range_score: float
    dealer_support: str
    theta_positive: bool
    ret: float


def load_rows(conn: psycopg.Connection) -> list[Row]:
    return [
        Row(
            ticker=r[0], as_of=r[1], iv_rv_edge=float(r[2]),
            iv_rv_ratio=float(r[3]), net_delta=float(r[4]),
            range_score=float(r[5]), dealer_support=r[6],
            theta_positive=bool(r[7]), ret=float(r[8]),
        )
        for r in conn.execute(_SQL).fetchall()
    ]


def build_grid() -> list[dict]:
    """Predeclared and coarse -- ~5 independent windows cannot support a fine
    grid. The three named configs come first so they are never lost in a crash."""
    grid: list[dict] = [
        {"kind": "unconditional", "name": "unconditional"},
        {"kind": "weights", "name": "radon", **RADON_WEIGHTS.__dict__},
        {"kind": "weights", "name": "default", **DEFAULT_WEIGHTS.__dict__},
    ]
    axes = itertools.product(
        (25.0, 40.0, 55.0, 70.0),   # vol_edge
        (15.0, 25.0),               # delta_neutrality
        (10.0, 20.0),               # range_bound
        (10.0, 15.0, 20.0),         # edge_saturation_pts
        (50.0, 60.0, 70.0),         # threshold
        (False, True),              # dealer_gate_critical
    )
    for vol, dn, rb, sat, thr, dealer in axes:
        grid.append({
            "kind": "weights", "name": None,
            **ScoreWeights(
                vol_edge=vol, delta_neutrality=dn, range_bound=rb,
                edge_saturation_pts=sat, threshold=thr,
                dealer_gate_critical=dealer,
            ).__dict__,
        })
    return grid


def selected_rows(rows: list[Row], *, config: dict) -> list[Row]:
    if config["kind"] == "unconditional":
        return list(rows)
    w = ScoreWeights(**{k: config[k] for k in ScoreWeights.__dataclass_fields__})
    out: list[Row] = []
    for r in rows:
        if abs(r.net_delta) > NEAR_ZERO_DELTA:
            continue
        if not (r.iv_rv_edge >= 5.0 or r.iv_rv_ratio >= 1.10):
            continue
        if not r.theta_positive:
            continue
        if w.dealer_gate_critical and r.dealer_support != "SUPPORT":
            continue
        score = score_from_components(
            iv_rv_edge=r.iv_rv_edge, net_delta=r.net_delta,
            range_score=r.range_score, weights=w,
        )
        if score >= w.threshold:
            out.append(r)
    return out


def evaluate_config(rows: list[Row], *, config: dict) -> dict:
    kept = selected_rows(rows, config=config)
    if not kept:
        return {
            "n_trades": 0,
            "metrics": {"sharpe": None, "effective_n_months": 0, "mean_ret": None},
            "gates": None,
        }

    monthly: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for r in kept:
        key = (r.as_of.year, r.as_of.month)
        monthly[key] = monthly.get(key, 0.0) + r.ret
        counts[key] = counts.get(key, 0) + 1
    # Equal-weight the month, not the row: 60 candidates in one month is one
    # observation of one market, not 60 independent bets.
    monthly = {k: v / counts[k] for k, v in monthly.items()}

    summary = monthly_summary(monthly)
    ordered = [monthly[k] for k in sorted(monthly)]
    obs = [{"ret": v} for v in ordered]
    return {
        "n_trades": len(kept),
        "metrics": {
            **summary,
            "sharpe": summary.get("sharpe"),
            "effective_n_months": len(monthly),
            "mean_ret": sum(ordered) / len(ordered),
            "n_tickers": len({r.ticker for r in kept}),
        },
        # Holdout on the month series. Thresholds are 0.0 -- the bar is only
        # "is the mean still positive out of sample", because with ~6 months
        # anything stricter is theatre. Below min_n the helper returns
        # survives_* False with descriptive means, which is what we want
        # reported rather than suppressed.
        "gates": walkforward_gate(
            obs,
            value_key="ret",
            min_n=4,
            threshold=0.0,
            holdout_threshold=0.0,
            holdout_frac=0.3,
        ),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip() or None

    with psycopg.connect(settings.db_dsn()) as conn:
        rows = load_rows(conn)
        if not rows:
            raise SystemExit(
                "No candidate/terminal-markout pairs. Run Task 8's backfill first."
            )
        log.info(
            "loaded %d rows, %s..%s, %d tickers",
            len(rows), rows[0].as_of, rows[-1].as_of,
            len({r.ticker for r in rows}),
        )
        out = run_sweep(
            build_grid(),
            lambda cfg: evaluate_config(rows, config=cfg),
            repo=BacktestRepository(conn),
            strategy=STRATEGY,
            reproduce_cmd=REPRODUCE,
            git_sha=sha,
            data_start=rows[0].as_of,
            data_end=rows[-1].as_of,
            notes=(
                "Same-close entry (lookahead). Spot-normalised model P&L, no "
                "bid-ask. Monthly equal-weight. Compare every config against "
                "the 'unconditional' control before claiming the score works."
            ),
        )

    named = {
        r["config"].get("name"): r
        for r in out["results"]
        if r["config"].get("name")
    }
    for key in ("unconditional", "radon", "default"):
        r = named.get(key)
        if r:
            m = r["metrics"]
            log.info(
                "%-14s sharpe=%s mean=%s months=%s trades=%s",
                key, m.get("sharpe"), m.get("mean_ret"),
                m.get("effective_n_months"), r.get("n_trades"),
            )
    log.info("run_id=%s ok=%s error=%s", out["run_id"], out["n_ok"], out["n_error"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_theta_harvester_sweep.py -v`
Expected: all 6 PASS.

- [ ] **Step 5: Run the sweep for real**

Run: `uv run python scripts/research/theta_harvester_weight_sweep.py`

Expected: it logs the loaded row count and window, then one line each for
`unconditional`, `radon`, `default`, then a `run_id`. Confirm persistence:

```sql
SELECT config->>'name', n_trades, metrics->>'sharpe', metrics->>'effective_n_months'
  FROM uw_scan.backtest_sweep_results
 WHERE run_id = <run_id> AND config->>'name' IS NOT NULL;
```

**Do not skip this step and do not paraphrase the result.** Write the three
headline numbers, the effective N, and the honest verdict into
`docs/research/2026-07-28-theta-harvester-weight-sweep.md`, including the case
where `default` loses to `unconditional`. A sweep whose result is not written
down did not happen.

- [ ] **Step 6: Commit**

```bash
git add scripts/research/theta_harvester_weight_sweep.py \
        tests/unit/test_theta_harvester_sweep.py \
        docs/research/2026-07-28-theta-harvester-weight-sweep.md
git commit -m "feat(theta-harvester): weight sweep with unconditional control arm"
```

---

### Task 13: Changelog, docs and final verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/research/2026-07-28-radon-scanner-port-backlog.md` (mark Theta done)
- Modify: `CLAUDE.md` ("Where to look first" table)

- [ ] **Step 1: Add the changelog entry**

Under `## [Unreleased]` → `### Added` in `CHANGELOG.md`:

```markdown
- **Theta Harvester scanner** (`/scanner/theta`) — short-strangle candidate finder
  ported from radon. Ranks one best 7–45 DTE, ~16Δ strangle per watchlist ticker
  per session from the warm store (`option_surface_grid_daily` +
  `exposures_by_expiry_strike` + `daily_ohlc` + `iv_rank_history`) at zero UW
  cost, gated on delta neutrality, IV-vs-RV edge, dealer gamma support and
  positive theta. Persists per-candidate rows with a Black-Scholes entry mark
  plus forward markouts at T+5/10/20/30, so the signal is evaluable rather than
  write-only. Live xenon/IB NBBO is fetched for the top 8 candidates on request
  only. Nightly at 19:45/19:55 ET; `/scanner` gains a sub-tab shell with the
  existing flow scanner as the Flow tab. Migration `109`.
```

- [ ] **Step 2: Update the backlog doc**

In `docs/research/2026-07-28-radon-scanner-port-backlog.md`, change the Theta Harvester heading from `IN PROGRESS` to `SHIPPED` and add a line under it pointing at this plan and the two table names.

- [ ] **Step 3: Add the CLAUDE.md pointer**

In the "Where to look first" table, after the scanner row:

```markdown
| Theta Harvester (short-strangle scanner) | `src/uw_scan/scanners/theta_harvester.py` (pure compute) + `storage/theta_harvester_repository.py` + `reports/theta_harvester_markout.py` + `worker/jobs/theta_harvester.py` (19:45/19:55 ET, massive-0, gated `theta_harvester_enabled`) + `api/routers/scanner.py` (`/scanner/theta-harvester{,/rescan,/quote}`) + `web/components/scanner/theta/` + migration `109`; backfill `scripts/backfill/theta_harvester_backfill.py` (**mandatory after any wipe** — the markout job only scores existing rows); recon `docs/research/2026-07-28-radon-scanner-port-backlog.md` |
```

- [ ] **Step 4: Run the full local CI equivalent**

Run:
```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
cd web && npm run lint && npm run test && npm run build
```
Expected: all green. Reproduce the FULL lint+unit job locally — it runs more than ruff and pytest.

- [ ] **Step 5: Run the no-Yahoo gate**

Run: `uv run python scripts/check_no_yahoo.py`
Expected: exits 0. Radon's LEAP and GARCH scanners fall back to Yahoo; nothing in this port may.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md CLAUDE.md docs/research/2026-07-28-radon-scanner-port-backlog.md
git commit -m "docs(theta): changelog, backlog status and CLAUDE.md pointer"
```

---

## Self-Review Notes

**Spec coverage:** warm-store ranking (T2–T6) · verbatim gates (T4) · two markout-shaped tables (T1) · always-populated BS entry mark (T4, T5) · bounded IB quoting (T9, T11) · nightly job (T6, T7) · on-demand rescan (T9, T11) · mandatory backfill (T8) · sub-tab shell with Flow preserved (T10) · dataset registry + policy doc (T1) · CHANGELOG (T12). All covered.

**Deferred deliberately:** `src/uw_scan/backtest/` gate/holdout integration. The design called for it, but there is nothing to gate until markout rows exist over enough sessions — with the GEX floor at 2026-05-11 that is ~55 trading days, below any reasonable holdout split. Wire it in a follow-up commit **on this branch** once the backfill has run and the markout distribution is visible; do not open a second PR.

**Review cycle (2026-07-28).** This plan went through a literature sweep, an
independent methodology verification, and a six-pass review including a Codex
tribunal. Blockers found and fixed, each verified against `option_wizard_local`
or by executing the algorithm:

- **Greek sign convention** — the grid stores long-contract greeks
  (`call_theta ∈ [-9.22, 0]`, `gamma ≥ 0`); radon's gates assume short-position
  signs. `THETA_HARVEST` was unreachable in production while the tests passed,
  because Task 3 and Task 4 fixtures used *contradictory* conventions. Negation
  now happens at one boundary with a dedicated regression test.
- **No terminal mark** — the grid holds **0 rows** where `expiry < market_date`,
  so settlement was not merely hard to observe, it was absent from the data. A
  short strangle's loss distribution lives at expiry, so the markout could not
  show the loss the strategy exists to be paid for. Terminal horizon added,
  resolving **backward** from `daily_ohlc` (forward-snapping was a lookahead).
- **Non-random markout censoring** — the snap CTE picked the earliest session
  with *any* row, then filtered strikes, returning `None` even when a later
  in-window session had both legs. Now selects the earliest session that
  already satisfies every requirement.
- **Mutable candidate identity** — a rescan could change expiry/strikes while
  leaving the old structure's markouts attached, producing P&L that looks valid
  and is not. Identity change now purges dependent marks in the same
  transaction, and leg selection has a deterministic tie-break.
- **Fabricated fixtures** — the original fixtures put AAPL at 232 with 210/250
  strikes. Real AAPL that session was **333.02**, and those strikes were
  0.99/0.98-delta calls. Replaced with the frozen real IWM capture.
- Router mutations now take `pg_try_advisory_lock` per `api/CLAUDE.md`; the
  registry mode moved to `research_artifact` (`strict_ticker_date` would report
  permanent unhealable gaps); backfill eligibility is per-ticker, not per-date.

**Unresolved by design, carried into implementation:**

- **Same-close entry is a lookahead** (see Interpretation constraints). The v1
  output is a diagnostic P&L, not a strategy return. Separating `signal_as_of`
  from `entry_date` is the clean fix and is deferred to a follow-up commit on
  this branch.
- **The comparison group is not a true control.** Verdict groups differ exactly
  on the variables that drive option returns, so harvest-vs-non-harvest shows
  association, not incremental value. A predeclared unconditional 16Δ baseline
  over the same eligible universe is the stronger design; the verdict split is
  what is affordable now.
- **Survivorship** — the replay uses today's watchlist because argon stores no
  membership history. The bias runs optimistic.

**Known risks:**
- `exposures_by_expiry_strike` is `run_id`-FK'd with `ON DELETE CASCADE`. Historical dealer-support inputs vanish if `scan_runs` is pruned. Mitigated by persisting `net_gex`/`gex_flip` as values on the candidate row (T1), so existing rows survive; only *re-running* the backfill over pruned dates would degrade.
- Radon's gates are unvalidated. The first markout read may show no edge. That is a finding, not a bug — the point of T7/T8 is to make it visible rather than assume it away.
- `iv_rank_history.volatility` scaling (decimal vs percent) is handled by a >3.0 heuristic in `load_iv`. **Verified 2026-07-28 against `option_wizard_local`: the column is consistently decimal, range 0.0925–1.5483, so the heuristic never fires.** It is kept as a cheap guard against a future ingest changing units, not because the data is currently mixed. If T8's smoke test shows any value above 3.0, that is an ingest regression, not a scaling case — investigate rather than rely on the rescale.
- **The grid never retains expired contracts.** Verified 2026-07-28: `option_surface_grid_daily` has **0 rows** where `expiry < market_date` (and 103,692 where `expiry = market_date`). This is why the terminal mark reads `daily_ohlc` rather than the grid, and it is the empirical basis for the whole terminal-horizon design — without that row, settlement is not merely hard to observe, it is *absent from the data*. Any future change that makes the intermediate horizons "cover" expiry is wrong.
