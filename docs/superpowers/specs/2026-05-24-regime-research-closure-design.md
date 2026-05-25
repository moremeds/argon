# Regime Research Closure — CRI + VCG Full Parity

**Date:** 2026-05-24
**Status:** Design draft — awaiting user review
**Related research:** [`docs/research/regime/cri-methodology.md`](../../research/regime/cri-methodology.md), [`docs/research/regime/cri-validation.ipynb`](../../research/regime/cri-validation.ipynb), [`docs/research/goyal-saretto-ipca-options/13-backtest-design.md`](../../research/goyal-saretto-ipca-options/13-backtest-design.md) §1.5 (informs schema shape)
**Related memories:** [[feedback_persist_results_to_db]], [[feedback_repository_split_threshold]], [[feedback_extend_pending_pr_branch]]

---

## 1. Problem

The regime research workspace under `docs/research/regime/` is half-closed:

- **CRI** has gone through v1 → v2 → v3 calibration. It has `cri-methodology.md` (15K of math + design decisions), `cri-validation.ipynb` (20-year walk-forward OOS validation; v1 baseline ROC AUC = 0.620 / 0.647 for `label_dd5` / `label_dd10`, current v3 AUC = 0.6343 / 0.6329 per `oos-summary.json`), and a `tests/integration/regime/test_cri_oos_gate.py` gating change to threshold constants.
- **VCG** has been shipped once (commit `d3cbc08`, port from xenon) and never iterated. No `vcg-methodology.md`, no `vcg-validation.ipynb`, no OOS gate, no `composite_version` tracking, no academic citations beyond a private xenon reference (`xenon docs/VCG_institutional_research_note.md` — not in this repo).

Additionally, the CRI backtest violates the standing rule [persist analytical results to Postgres](../../../). `scripts/backtest_cri.py` writes outputs only to disk (`cri-backtest.{md,csv}`, `oos-summary.json`). The `/api/regime/validation` endpoint reads those files via `_safe_doc_path()` — there is no DB row of record. Compared to e.g. `cri_snapshots` (live runtime persistence ✅), the *historical* analytical record for both CRI and VCG is missing from Postgres entirely.

**Why now:** the standing rule violation is documented in memory but unaddressed; VCG's research debt has not been quantified; and re-opening the regime work without a persistence-of-record foundation will compound both problems.

## 2. Goal

Take the regime research from "half-shipped" to "stable platform for continued research." Concretely:

1. **Backtest results live in Postgres**, append-only, multi-run per indicator, so calibration A/B tests are SQL queries
2. **VCG reaches CRI parity** on research scaffolding: methodology doc, academic foundations, version tracking, backtest evidence
3. **The chapter is closeable** with a memo that doubles as a launchpad: what's done, how to query it, what's deferred, what research questions are now cheap

The implicit question this closure answers: **does the regime research lift its own weight?** Before: requires running a Python script. After: a SQL query, with both indicators evaluated on identical 20-year history.

## 3. Non-goals

- Not building the generic backtest infrastructure spec'd in `docs/research/goyal-saretto-ipca-options/13-backtest-design.md` §1.5 (`backtest_runs` / `*_portfolios` / `*_summary` / `*_trades`). That schema is for the IPCA replication and trade-level backtests. The schema here is the simpler regime-specific shape.
- Not modifying the regime UI. The frontend continues to consume `/api/regime/validation` with an unchanged response shape — only the underlying data source moves from disk to DB.
- Not introducing new regime indicators (GEX-as-regime, vol-term-structure-as-regime, etc.). Strictly CRI + VCG.
- Not re-tuning CRI calibration. CRI v3 stays as-is.
- Not building bare-mode/API-key configuration for any new scripts — they read the same `Settings.from_env()` plumbing the existing backtest uses.

## 4. Academic foundations

This section grounds both indicators in primary academic literature. Citations here are verified (DOI / journal volume / page numbers retrieved 2026-05-24) and will be cited from the implementation docs (`vcg-methodology.md`, updated `cri-methodology.md` §5).

### 4.1 CRI — augmenting the existing practitioner-heavy bibliography

The current `cri-methodology.md` §5 ("Web research summary") leans on practitioner sources (CBOE VVIX whitepaper, Convex, MenthorQ, SpotGamma, Schwab, TradingView). It cites one academic working paper (AUT ACFR on decomposed VVIX). Academic equivalents for each component:

| CRI component | Academic foundation |
|---|---|
| **VIX** (level) | Bollerslev, Tauchen, Zhou (2009), "Expected Stock Returns and Variance Risk Premia." *Review of Financial Studies* 22(11), 4463-4492 — establishes the variance risk premium (≈ VRP-style component) as a return predictor. |
| **VVIX** (level, ratio, RoC) | Park, Y.-H. (2015), "Volatility-of-volatility and tail risk hedging returns." *Journal of Financial Markets* — VVIX as a leading indicator of S&P 500 put and VIX call option prices; predicts subsequent returns over 3-4 weeks. Reinforces the v3 RoC sub-score's pre-stress signaling logic. |
| **VVIX** (cross-sectional implications) | Baltussen, van Bekkum, van der Grient (2018), "Unknown Unknowns: Uncertainty About Risk and Stock Returns." *Journal of Financial and Quantitative Analysis* 53(4), 1615-1651 — vol-of-vol as a robust pricing factor distinct from 20+ other predictors. |
| **COR1M** (implied correlation) | Driessen, Maenhout, Vilkov (2009), "The Price of Correlation Risk: Evidence from Equity Options." *Journal of Finance* 64(3), 1377-1406 — establishes correlation risk as priced; index-implied correlation systematically exceeds realized; supports COR1M as a stress signal rather than a coincident indicator. |

### 4.2 VCG — establishing the academic foundation from scratch

VCG's mechanism (rolling 21-day OLS of `Δlog(credit) ~ α + β₁·Δlog(VVIX) + β₂·Δlog(VIX)`, then z-score the residual) is a *residual-based regime indicator*. The academic literature supports each of the three structural choices:

| VCG choice | Academic foundation |
|---|---|
| **Linear regression of credit-on-equity-vol** | Campbell, J. Y., & Taksler, G. B. (2003), "Equity Volatility and Corporate Bond Yields." *Journal of Finance* 58(6), 2321-2350. DOI: [10.1046/j.1540-6261.2003.00607.x](https://onlinelibrary.wiley.com/doi/10.1046/j.1540-6261.2003.00607.x). Establishes that idiosyncratic firm-level equity volatility explains as much cross-sectional variation in bond yields as credit ratings — empirically validates the right-hand-side of VCG's regression. |
| **Residual (not fitted value) as the signal** | Collin-Dufresne, P., Goldstein, R. S., & Martin, J. S. (2001), "The Determinants of Credit Spread Changes." *Journal of Finance* 56(6), 2177-2207. DOI: [10.1111/0022-1082.00402](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00402). Variables that should *in theory* determine credit spread changes (Treasury rates, equity volatility, leverage) have only limited explanatory power; the unexplained variance is large and economically meaningful. **This is exactly the motivation for VCG: the residual carries information the inputs do not.** |
| **Residual-as-dislocation methodology** | Pasquariello, P. (2014), "Financial Market Dislocations." *Review of Financial Studies* 27(6), 1868-1914 — RFS Best Paper Runner-Up. Constructs a model-free measure of cross-market dislocations from arbitrage-parity violations and shows they price expected returns. VCG's z-scored residual is a one-pair instance of this broader methodology. |
| **VVIX as the second covariate (not VIX alone)** | Park (2015), as above — VVIX is a leading rather than coincident vol signal; including both VIX and VVIX in the right-hand-side lets the residual orthogonalize against both "current vol" and "expected change in vol." |
| **Regime framing for an aggregate financial-conditions signal** | Adrian, T., Boyarchenko, N., & Giannone, D. (2019), "Vulnerable Growth." *American Economic Review* 109(4), 1263-1289. DOI: [10.1257/aer.20161923](https://www.aeaweb.org/articles?id=10.1257%2Faer.20161923). Deteriorating financial conditions move the lower (tail) quantiles of GDP growth, not the median. VCG as a *regime* indicator (PANIC / TRANSITION / DIVERGENCE; RISK_OFF / EDR / WATCH / BOUNCE / NORMAL) is consistent with this asymmetric tail-risk framing. |

### 4.3 Honest reading of what these citations do and don't justify

**They justify:**
- Including VVIX, VIX, and a credit proxy as the three core VCG inputs (Campbell-Taksler + Park + Driessen-Maenhout-Vilkov).
- The residual-z-score construction (Collin-Dufresne et al. + Pasquariello).
- The regime taxonomy with asymmetric tail behavior (Adrian et al.).

**They do NOT justify:**
- The specific thresholds (`VCG_TRIGGER=2.0`, `VCG_RO_TRIGGER=2.5`, `BOUNCE_TRIGGER=-3.5`, `VIX_FLOOR=28`, `VIX_PANIC_LOW=40`, etc.). These were inherited from xenon without documented calibration; treating them as defensible requires the diagnostic in §9 step 4.
- The choice of HYG as default credit proxy over JNK / LQD. Phase 1's diagnostic must check whether the proxy choice changes the historical signal, and `vcg-methodology.md` §3 must document the choice.
- The panic-adjustment `π = clamp((VIX-40)/8, 0, 1)`. Not in the literature; a xenon-era construct. Must be documented in `vcg-methodology.md` with explicit "no academic ground for this; here is the empirical motivation" honesty.

This honest distinction is itself a closure deliverable: the difference between "well-founded" inputs/methodology and "calibration-by-tradition" constants is explicit, so future research knows where to push.

## 5. Architecture overview

```
                  ┌────────────────────────────────────┐
                  │  uw_scan.vol_index_daily           │
                  │  (parquet lake → DB, ~20y deep)    │
                  └─────┬──────────────────────────────┘
                        │
              ┌─────────┴─────────┐
              │                   │
   ┌──────────▼─────┐   ┌─────────▼──────┐
   │ backtest_cri.py│   │ backtest_vcg.py│  (NEW)
   │ (modified)     │   │                │
   └──────┬─────────┘   └────────┬───────┘
          │                      │
          └──────────┬───────────┘
                     │
                     ▼
       ┌────────────────────────────────┐
       │ uw_scan.regime_backtest_runs   │  (NEW migration 057)
       │ uw_scan.regime_backtest_daily  │
       └──────┬─────────────────────────┘
              │
              ▼
   ┌──────────────────────────────────┐
   │ regime_backtest_repository.py    │  (NEW)
   └──────┬───────────────────────────┘
          │
          ▼
   ┌────────────────────────────────────┐
   │ api/routers/regime_validation.py   │  (modified — reads DB, not files)
   └────────────────────────────────────┘
```

`uw_scan.vol_index_daily` already holds the inputs both backtests consume (VIX, VVIX, COR1M, SPX, HYG/JNK/LQD; 18.5–20+ years of history depending on series).

## 6. Schema (migration 057)

Migration slots 053–056 are taken (`053_rates_policy_sources.sql`, `053_trade_insights_ai_provider_column.sql`, `054_trade_insight_outcomes.sql`, `055_rates_supply_sources.sql`, `055_trade_insight_priors_view.sql`, `056_trade_insight_ai_raw_outcome.sql`). Next free slot is **057**. Re-verify at PR-open time in case parallel branches land more.

```sql
-- 057_regime_backtest_results.sql
-- Idempotent for clean re-application: re-running this file against a DB that
-- already has both tables (created by THIS migration) is a no-op.
--
-- NOT idempotent for partial-table repair: if a parallel/abandoned branch
-- created a partial version of either table without the constraints below,
-- this migration may fail (FK / NOT NULL / CHECK additions will reject if data
-- already violates them). Recovery procedure for that case is documented in
-- the §15 risk register and the migration's runbook: drop the partial table
-- and re-apply. We deliberately do NOT attempt constraint surgery via DO
-- blocks — it adds 50+ lines of pg_catalog dancing for a scenario the repo's
-- single-trunk workflow makes vanishingly rare.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.regime_backtest_runs (
  id                BIGSERIAL PRIMARY KEY,
  indicator         TEXT NOT NULL CHECK (indicator IN ('cri','vcg')),
  composite_version TEXT NOT NULL,
  start_date        DATE NOT NULL,
  end_date          DATE NOT NULL,
  window_days       INT  NOT NULL,  -- rolling lookback in trading days; `window` is a PG reserved keyword, hence the suffix
  n_days            INT  NOT NULL,
  params            JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary           JSONB NOT NULL DEFAULT '{}'::jsonb,
  note              TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at      TIMESTAMPTZ,   -- NULL until bulk_insert_daily finishes; set as final step. find_latest_run filters on this.
  CONSTRAINT regime_backtest_runs_date_range  CHECK (start_date <= end_date),
  CONSTRAINT regime_backtest_runs_n_days_nonneg CHECK (n_days >= 0),
  CONSTRAINT regime_backtest_runs_window_pos    CHECK (window_days > 0)
);

CREATE INDEX IF NOT EXISTS idx_regime_backtest_runs_completed
  ON uw_scan.regime_backtest_runs (indicator, completed_at DESC) WHERE completed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_regime_backtest_runs_lookup
  ON uw_scan.regime_backtest_runs (indicator, composite_version, created_at DESC);

CREATE TABLE IF NOT EXISTS uw_scan.regime_backtest_daily (
  run_id     BIGINT NOT NULL REFERENCES uw_scan.regime_backtest_runs(id) ON DELETE CASCADE,
  trade_date DATE   NOT NULL,
  score      NUMERIC NOT NULL,
  level      TEXT,
  payload    JSONB  NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (run_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_regime_backtest_daily_date
  ON uw_scan.regime_backtest_daily (trade_date, run_id);

COMMIT;
```

**`level` column values** (deliberately not CHECK-constrained because the value set is indicator-specific and the validator lives in code, not SQL):
- CRI: `LOW` / `ELEVATED` / `HIGH` / `CRITICAL` (per `src/uw_scan/cards/cri_scorers.py:181-188`)
- VCG: `NORMAL` / `WATCH` / `EDR` / `RISK_OFF` / `BOUNCE` / `PANIC` / `SUPPRESSED` / `INSUFFICIENT_DATA` (per `evaluate_signal` in `src/uw_scan/cards/vcg_scoring.py:279-295`)

**Three deliberate choices for "research further":**
- `composite_version` is `NOT NULL` — forces the script to declare its calibration so comparison queries always work. CRI's runtime `COMPOSITE_VERSION = 3` integer is rendered as the string `'3'` (or `'v3'` — pick one convention and apply across CRI + VCG; see §8.1 for the provenance rule).
- `note` is a free-text human label for the experiment context.
- Append-only with no canonical/`is_current` pointer. Comparing v3 against a candidate v4 is `WHERE composite_version IN ('3','4-candidate')`. Latest is `ORDER BY indicator, created_at DESC LIMIT 1`.

**`summary` JSONB shape — split into API-facing and research-facing keys:**

The router calls `OosSummary.model_validate(run["summary"]["oos"])`, so `summary.oos` MUST satisfy the existing `OosSummary` Pydantic model (`src/uw_scan/api/models/regime_validation.py:22-29`): `as_of`, `notebook`, `method`, `labels[]`, `scores[]`, `interpretation`. Pydantic v2 default `extra="ignore"` lets `summary.oos` carry **API-ignored sidecar fields** that downstream tests still need — `versions[]` is the canonical example. The `test_cri_oos_gate.py` lookup reads `summary.oos.versions[*]` directly from the dict (bypassing the Pydantic model), and the API silently drops it. **Diagnostic-only data** (named_crash_hits, level_distribution, interpretation_distribution, fired_count) lives under `summary.extras` because no test relies on its keys.

CRI run:
```json
{
  "oos": {
    "as_of": "2026-05-25",
    "notebook": "scripts/backtest_cri.py",
    "method": "Forward-drawdown labels: dd5 = SPX -5% within 20 sessions; dd10 = SPX -10% within 60 sessions. AUC via Mann-Whitney rank-sum on the full backtest.",
    "labels": [
      {"name": "label_dd5",  "definition": "SPX -5% drawdown within 20 trading days"},
      {"name": "label_dd10", "definition": "SPX -10% drawdown within 60 trading days"}
    ],
    "scores": [
      {"model": "CRI v1 (frozen baseline)", "auc_dd5": 0.62,   "auc_vix30": null, "auc_dd10": 0.647},
      {"model": "CRI v3 (this run)",        "auc_dd5": 0.6343, "auc_vix30": null, "auc_dd10": 0.6329}
    ],
    "versions": [
      {"label": "CRI v1", "version": 1, "auc_dd5": 0.62,   "auc_dd10": 0.647,  "n_observations": 4873, "notes": "Frozen baseline from cri-validation.ipynb §9 (pre-PR-58)."},
      {"label": "CRI v3", "version": 3, "auc_dd5": 0.6343, "auc_dd10": 0.6329, "n_observations": 4873, "notes": "v3: VIX floor 13, RoC denom 40, VVIX floor 80, tactical pullback sub-score (saturates at -4% from 20d high)."}
    ],
    "interpretation": "Current version AUC must be within BASELINE_TOLERANCE (0.02) of v1 baseline. Enforced by tests/integration/regime/test_cri_oos_gate.py."
  },
  "extras": {
    "named_crash_hits": {
      "2008-09-15": {"score": 78, "level": "CRITICAL", "fired": true},
      "2020-03-16": {"score": 97, "level": "CRITICAL", "fired": true}
    },
    "level_distribution": {"LOW": 3210, "ELEVATED": 1450, "HIGH": 420, "CRITICAL": 120},
    "fired_count": 47,
    "v1_baseline_auc_dd5":  0.62,
    "v1_baseline_auc_dd10": 0.647
  }
}
```

VCG run (no OOS gate — `summary.oos` is `null` because no defensible Y-label exists; see §11.2):
```json
{
  "oos": null,
  "extras": {
    "credit_proxy": "HYG",
    "named_crash_window": {
      "2008-09-15": [
        {"offset_d": -5, "vcg": 1.40, "vcg_adj": 1.40, "interpretation": "WATCH", "sign_ok": true},
        {"offset_d":  0, "vcg": 3.12, "vcg_adj": 0.00, "interpretation": "PANIC", "sign_ok": true},
        {"offset_d": +5, "vcg": 2.05, "vcg_adj": 0.00, "interpretation": "PANIC", "sign_ok": true}
      ]
    },
    "interpretation_distribution": {"NORMAL": 3500, "WATCH": 510, "EDR": 180, "RISK_OFF": 95, "BOUNCE": 40, "PANIC": 25, "SUPPRESSED": 50, "INSUFFICIENT_DATA": 94},
    "ro_count": 95, "edr_count": 180, "bounce_count": 40
  }
}
```

The `named_crash_window` shape (±5 sessions × raw `vcg` × `vcg_adj` × `sign_ok`) is deliberate — see §8.3 for why raw-VCG matters more than the `PANIC`-label collapse.

## 7. Repository

New file: `src/uw_scan/storage/regime_backtest_repository.py`. Per the [no-extend-repository.py rule](../../../) — new persistence domain gets its own module.

```python
class RegimeBacktestRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None: ...

    def insert_run(
        self,
        *,
        indicator: Literal["cri", "vcg"],
        composite_version: str,
        start_date: date,
        end_date: date,
        window_days: int,
        n_days: int,
        params: dict,
        summary: dict,
        note: str | None = None,
    ) -> int: ...

    def bulk_insert_daily(self, run_id: int, rows: list[dict]) -> None:
        """Chunked psycopg.executemany. Each row: {trade_date, score, level, payload}."""

    def mark_run_completed(self, run_id: int) -> None:
        """Sets completed_at = NOW(). Must be the LAST call in the backtest
        workflow — defines the atomic boundary that find_latest_run filters on."""

    def find_latest_run(
        self,
        indicator: Literal["cri", "vcg"],
        composite_version: str | None = None,
    ) -> dict | None:
        """Returns the latest COMPLETED regime_backtest_runs row dict or None.

        Filters:
        - WHERE completed_at IS NOT NULL — interrupted backtests can't poison the API.
        - WHERE composite_version = <arg or current code constant> — when called
          from the API with composite_version=None, defaults to the indicator's
          current code constant (cri_scorers.COMPOSITE_VERSION / vcg_scoring.COMPOSITE_VERSION).
          This means experimental runs (different composite_version) are query-only
          via SQL and DO NOT leak into /api/regime/validation. Closes codex P2 on
          "candidate calibrations would surface to users."

        Pass an explicit composite_version to opt out of the production filter for
        research queries.
        """

    def fetch_daily_for_run(self, run_id: int) -> list[dict]: ...

    def list_runs(
        self,
        indicator: Literal["cri", "vcg"],
        limit: int = 20,
        completed_only: bool = True,
    ) -> list[dict]: ...
```

Tests: `tests/unit/storage/test_regime_backtest_repository.py` (insert + read round-trip on `pytest-postgresql`).

## 8. Scripts

### 8.1 `scripts/backtest_cri.py` (modify)

Changes:
- Remove flags: `--out-csv`, `--out-md`, `--write-oos-summary`
- Add flags: `--note` (optional). `--composite-version` is **NOT** a CLI flag — see provenance rule below.
- Remove functions: `write_csv`, `write_report`, `write_oos_summary` — replaced by repository writes + `reports/regime_backtest_report.py` renderer for on-demand markdown
- `main()` becomes:
  1. Read `from uw_scan.cards.cri_scorers import COMPOSITE_VERSION` (currently `3`); render as string `str(COMPOSITE_VERSION)`
  2. Pull aligned series from `vol_index_daily`
  3. Run `rolling_compute` (unchanged math)
  4. Compute OOS AUC + named-crash hits + level distribution; assemble `summary` dict with `oos` (matching `OosSummary` Pydantic shape exactly) and `extras` subkeys
  5. `repo.insert_run(..., composite_version=str(COMPOSITE_VERSION), ...)` → run_id (`completed_at` left NULL)
  6. `repo.bulk_insert_daily(run_id, rows)` — each row's `level` populated from `cri_scorers.crash_level()` (`LOW`/`ELEVATED`/`HIGH`/`CRITICAL`); `payload` carries the full per-day component breakdown
  7. `repo.mark_run_completed(run_id)` — sets `completed_at = NOW()`; the API only serves runs past this line
  8. Log run_id + summary; exit

**Provenance rule (closes codex P2 finding):** the script does NOT accept `--composite-version` as a user-overridable flag. The value is derived from `cri_scorers.COMPOSITE_VERSION` at import time, so the persisted `composite_version` column always matches the code that produced the daily rows. Bumping the constant in code is the ONLY way to bump the persisted version. Same rule for VCG below — but VCG currently has no `COMPOSITE_VERSION` constant, which is itself a deliverable (§11.1.3).

### 8.2 `scripts/backtest_vcg.py` (new — mirror CRI's shape)

```
Usage:
  uv run python scripts/backtest_vcg.py
  uv run python scripts/backtest_vcg.py --proxy LQD --note "LQD proxy A/B"
  uv run python scripts/backtest_vcg.py --start 2007-01-01 --end 2026-05-15
```

`--composite-version` is not exposed; the script reads `COMPOSITE_VERSION = 1` from `src/uw_scan/cards/vcg_scoring.py` (added as part of this closure — see §11.1.3).

Implementation:
1. Read `from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION` (`1` for the as-ported v1)
2. Pull `VIX`, `VVIX`, `<proxy>` (default `HYG`) from `vol_index_daily`. **Use `COALESCE(adj_close, close)` for the credit proxy** (HYG/JNK/LQD distribute monthly; raw close would surface every ex-dividend drop as a log-return spike that the OLS reads as credit stress — see `scanners/vcg.py:38-46`). Use raw `close` for VIX/VVIX (no distributions)
3. Align on shared dates
4. Run `vcg_scoring.compute_vcg` (unchanged math, pure function — produces per-day arrays for the full series)
5. For each day from `OLS_WINDOW + Z_WINDOW + 10 = 94` onward, build a daily row using a **new** `_interpretation_for_index(model, idx, *, vix_floor, vcg_trigger) -> dict` helper extracted from `evaluate_signal` (`src/uw_scan/cards/vcg_scoring.py:223-325`). This is a small, reviewable refactor: the helper returns `{score, vcg_adj, residual, beta1, beta2, alpha, vix, vvix, credit, pi_panic, regime, interpretation, sign_ok, ro, edr, tier, bounce}` for an arbitrary index. `evaluate_signal` becomes a thin wrapper that calls `_interpretation_for_index(model, idx=-1, ...)` and adds the `attribution` block + 5d-return + history list. This closes codex's P1 finding that `_history_row` alone cannot reconstruct `interpretation`.
6. Compute summary: `named_crash_window` (±5 sessions around each named crash, with raw `vcg` + `vcg_adj` + `sign_ok`), `interpretation_distribution`, ro/edr/bounce counts. `summary.oos` is `null` (no defensible Y-label in V1; see §11.2)
7. Persist via repository with `indicator='vcg'`, `composite_version=str(COMPOSITE_VERSION)`, `params={"proxy": proxy}`

History depth (per DB query 2026-05-24):
- HYG: 2007-04-11 → today (≈18.5 years)
- JNK: 2007-12-04 → today (≈18 years)
- LQD: 2002-07-26 → today, but VVIX-bound → effective 2006-03-06 → today (≈20 years)
- VIX-VVIX intersection: 2006-03-06 onwards

### 8.3 Diagnostic at end of each run

**CRI** — named-crash sanity check (this is unambiguous; CRI level + fired flag are produced by the same scoring code we trust):

```
=== CRI named-crash sanity check ===
2008-09-15 Lehman bankruptcy           CRI=78 CRITICAL fired=true
2008-10-10 GFC bottom area             CRI=91 CRITICAL fired=true
2010-05-06 Flash crash                 CRI=64 HIGH     fired=false
2018-02-05 Volmageddon                 CRI=82 CRITICAL fired=true
2020-03-16 COVID circuit breaker       CRI=97 CRITICAL fired=true
2024-08-05 Yen-carry unwind            CRI=71 HIGH     fired=false
```

**VCG** — descriptive evidence table, *not* a PASS/FAIL gate (closes codex's P1 finding that the eyeball gate is undefensible):

The fundamental problem with a binary VCG gate: when `VIX >= 48`, the panic-π adjustment forces `vcg_adj → 0`, so `interpretation` collapses to `PANIC` regardless of whether the *residual* component said anything. A crash that registers `PANIC` could be VIX-driven with the model contributing zero — the gate would mark it PASS without evidence the model worked. Similarly, `sign_ok=false` (`β₁` or `β₂` flipped positive) silently suppresses the signal to `SUPPRESSED` independent of residual magnitude.

So VCG's diagnostic reports the **±5 trading session window** around each named crash, exposing the residual model directly:

```
=== VCG ±5d named-crash window (proxy=HYG) ===
2008-09-15 Lehman bankruptcy
  offset_d  vcg     vcg_adj  beta1   beta2   sign_ok  interp
  -5        +1.40   +1.40    -0.31   -0.18   true     WATCH
  -3        +1.80   +1.80    -0.29   -0.20   true     WATCH
  -1        +2.15   +2.15    -0.28   -0.22   true     EDR
   0        +3.12   +0.00    -0.30   -0.25   true     PANIC   (vcg_adj suppressed by π=1)
  +1        +2.70   +0.00    -0.31   -0.24   true     PANIC
  +5        +2.05   +0.00    -0.28   -0.21   true     PANIC

2020-03-16 COVID circuit breaker
  -5        +0.30   +0.30    -0.34   -0.15   true     NORMAL
  -3        +1.10   +1.10    -0.32   -0.18   true     NORMAL
  -1        +2.50   +2.50    -0.30   -0.22   true     EDR
   0        +4.80   +0.00    -0.28   -0.24   true     PANIC
   ...
```

**Reading the table:**
- Raw `vcg` rising above ~2.0 in the days *before* a named crash, with `sign_ok=true`, is positive evidence the residual model is doing real work.
- Raw `vcg` flat through the crash window means the residual model was inert; the `PANIC` label is then VIX-driven, not VCG-driven.
- `sign_ok=false` anywhere in the window means the regression's economic priors broke; the day's signal should be discounted.

This evidence goes into `summary.extras.named_crash_window` for SQL inspection and informs (but does not auto-decide) the v1-vs-v2 calibration call in §11.3.

## 9. API surface

### 9.1 `api/routers/regime_validation.py` (modify)

Currently (lines 247-256):
```python
@router.get("/validation", response_model=ValidationResponse)
def get_validation() -> ValidationResponse:
    # _safe_doc_path raises 404 with a precise reason (not-found vs symlink
    # vs not-regular-file) — let it propagate.
    md_path = _safe_doc_path("cri-backtest.md")
    return ValidationResponse(
        backtest_md=md_path.read_text(),
        backtest_csv_rows=_count_csv_rows("cri-backtest.csv"),
        oos=_read_oos_summary(),
    )
```

After (DB-first with file fallback during transition — see §10.4 for why files survive until the first DB run is verified in prod). Use the **existing** `Depends(get_repo)` pattern (`src/uw_scan/api/routers/regime_validation.py:227`, `src/uw_scan/api/deps.py:21`) rather than introducing new module-level globals — the router currently has no `get_conn` or `settings` symbols:

```python
from typing import Annotated
from fastapi import Depends
from uw_scan.api.deps import get_repo
from uw_scan.storage.repository import Repository  # existing
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository  # NEW
from uw_scan.reports.regime_backtest_report import render_backtest_markdown  # NEW

@router.get("/validation", response_model=ValidationResponse)
def get_validation(
    repo: Annotated[Repository, Depends(get_repo)],
) -> ValidationResponse:
    # RegimeBacktestRepository takes the same psycopg connection the existing
    # Repository holds; it does not need its own deps entry. Use `_schema`
    # (private attribute) to match the pattern in get_guidance — Repository
    # does not expose a public `schema` property.
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    # No composite_version arg → repository defaults to the CRI code constant
    # (str(cri_scorers.COMPOSITE_VERSION)). Experimental runs at other versions
    # are query-only via SQL and DO NOT surface to /regime users.
    run = rb.find_latest_run("cri")
    if run is not None:
        daily = rb.fetch_daily_for_run(run["id"])
        oos_payload = (run.get("summary") or {}).get("oos")
        return ValidationResponse(
            backtest_md=render_backtest_markdown(run, daily),
            backtest_csv_rows=len(daily),
            oos=OosSummary.model_validate(oos_payload) if oos_payload else None,
        )
    # Transitional fallback: read the on-disk artifacts (unchanged from before
    # this PR). Removed in the follow-up PR once §18 manual-gate criterion
    # "first prod CRI DB run" is verified. Eliminates the P0 deploy-order
    # outage where migrate.sh applies SQL but doesn't seed runs.
    md_path = _safe_doc_path("cri-backtest.md")
    return ValidationResponse(
        backtest_md=md_path.read_text(),
        backtest_csv_rows=_count_csv_rows("cri-backtest.csv"),
        oos=_read_oos_summary(),
    )
```

Response shape **unchanged** — frontend untouched. `ValidationResponse` is the existing Pydantic model at `src/uw_scan/api/models/regime_validation.py:31-39`; do not rename. The OosSummary contract (`as_of`, `notebook`, `method`, `labels[]`, `scores[]`, `interpretation` per `models/regime_validation.py:22-29`) is preserved by routing through `run["summary"]["oos"]` — see schema §6.

### 9.2 New module: `src/uw_scan/reports/regime_backtest_report.py`

Pure renderer extracted from the existing `write_report` in `backtest_cri.py:358`. Takes a `run` dict + `daily` list, returns markdown matching the existing `cri-backtest.md` byte-for-byte.

**Critical detail (closes codex P2 finding on renderer drift):** the report's visible "Backtest window" start is `daily[0].trade_date`, **not** `run.start_date`. The current report begins at `2007-01-03` because `rolling_compute` defaults to a 150-day lookback and only emits rows from index 150 onward (`scripts/backtest_cri.py:128, 137`). The renderer must compute its visible window from the daily-rows list, not from the run row's date columns — otherwise the snapshot test fails byte-for-byte even with identical math.

Snapshot test: `tests/unit/reports/test_regime_backtest_report.py` compares the renderer output against the *current* checked-in `docs/research/regime/cri-backtest.md` byte-for-byte. The fixture is the existing file, so any drift is caught at PR time, before the file is deleted (§10.3). Drift is acceptable only if the diff is documented in the test and the response-shape contract still holds.

### 9.3 New endpoint (deferred, NOT in this closure)

`/api/regime/backtest/{indicator}/runs` for listing recent runs — useful for the "research further" workflow but not required by current UI. **Deferred** until a UI consumer exists; trivially addable later.

## 10. File and git changes

### 10.1 Files removed from git — DEFERRED to follow-up PR

The three on-disk artifacts (`cri-backtest.md`, `cri-backtest.csv`, `oos-summary.json`) **remain in the working tree throughout the primary PR**. They are the data source the router fallback (§9.1) consumes when no DB run yet exists. They are deleted in the follow-up PR only after §10.4's manual prod gate is satisfied.

### 10.2 Files added
- `src/uw_scan/storage/migrations/057_regime_backtest_results.sql`
- `src/uw_scan/storage/regime_backtest_repository.py`
- `src/uw_scan/reports/regime_backtest_report.py`
- `scripts/backtest_vcg.py`
- `docs/research/regime/vcg-methodology.md` (NEW — §11.1)
- `docs/research/regime/closure-2026-05-24.md` (NEW — §13)
- `tests/unit/storage/test_regime_backtest_repository.py`
- `tests/unit/reports/test_regime_backtest_report.py`

### 10.3 Files modified
- `scripts/backtest_cri.py` (DB writes; remove file outputs)
- `src/uw_scan/api/routers/regime_validation.py` (read DB, fall back to file during transition — see §10.4)
- `src/uw_scan/cards/vcg_scoring.py` (add `COMPOSITE_VERSION = 1`; extract `_interpretation_for_index`)
- `tests/integration/regime/test_cri_oos_gate.py` (read OOS data from DB run summary instead of `oos-summary.json`; closes codex P1 finding that file removal disables CI gate)
- `docs/research/regime/CLAUDE.md` (update rules for VCG; remove file-based update guidance)
- `docs/research/regime/cri-methodology.md` (augment §5 with academic citations from §4.1)

### 10.4 File-removal sequencing (closes codex P0 deploy-order finding)

The router supports BOTH paths during transition (§9.1 fallback). Removal happens in a **follow-up PR**, not this one:

1. **This PR ships:** schema, repository, script changes (`backtest_cri.py` writes DB + still produces no files), router fallback, VCG backtest, methodology docs. Files at `docs/research/regime/{cri-backtest.md,cri-backtest.csv,oos-summary.json}` remain in git for the fallback path.
2. **Manual gate before file-removal PR:** verify in prod that `SELECT COUNT(*) FROM uw_scan.regime_backtest_runs WHERE indicator='cri' AND completed_at IS NOT NULL` returns ≥1. The `completed_at IS NOT NULL` clause is non-optional — without it the gate passes on an interrupted run that has no daily rows, recreating the deploy-order outage.
3. **Follow-up PR:** remove the three files + remove the fallback block from `regime_validation.py`. This PR is mechanical (no design changes) and trivially revertable.

This eliminates the "API/web deploy before first backtest run → /regime serves 503" outage path.

## 11. VCG research trail (full parity)

### 11.1 `docs/research/regime/vcg-methodology.md` (NEW)

Mirror `cri-methodology.md`'s structure. Required sections:

1. **What VCG is** — Volatility-Credit Gap; residual-based regime indicator; what it does and does not measure
2. **Mathematical specification** — the 21d rolling OLS, the 63d residual standardization, the panic-π adjustment
3. **Calibration constants and `COMPOSITE_VERSION = 1`** — `VCG_TRIGGER=2.0`, `VCG_RO_TRIGGER=2.5`, `BOUNCE_TRIGGER=-3.5`, `VIX_FLOOR=28`, `VIX_EDR=25`, `VIX_PANIC_LOW=40`, `VIX_PANIC_HIGH=48`, `VVIX_ELEVATED=100`, `VVIX_EXTREME=120`. Each constant: stated, rationale (xenon-inherited; specific empirical motivation NOT yet re-derived), and the empirical band it targets in the 20y backtest. **This closure also adds `COMPOSITE_VERSION = 1` to `src/uw_scan/cards/vcg_scoring.py`** so the backtest script can derive provenance the same way CRI does — bumping any constant in §3 requires bumping `COMPOSITE_VERSION` in the same commit
4. **Design decisions** — why HYG default credit proxy; why adj_close for credit ETFs (distribution drops); why VVIX-then-VIX in the regression order; why sign discipline (`β₁, β₂ ≤ 0`) gates the signal
5. **Academic foundations** — verbatim from §4.2 of this spec, with the honest "does not justify" distinction from §4.3
6. **Known limitations** — single credit proxy at a time; signed-residual is one-tailed asymmetric (positive = stress, negative = capitulation); 21-day OLS sensitive to weekend/holiday alignment; HYG has dividend-noise that adj_close mitigates but doesn't eliminate; **the panic-π adjustment collapses `vcg_adj → 0` when `VIX ≥ 48`, so during severe crashes the displayed `interpretation` becomes VIX-driven rather than residual-driven — VCG users should always inspect raw `vcg` alongside `interpretation` for high-VIX regimes**
7. **Version history** — v1 = as-ported from xenon (commit `d3cbc08`, 2026-04 era); v2 = (conditional, see §11.3)

### 11.2 `docs/research/regime/vcg-validation.ipynb` (CONDITIONAL — defer to follow-on)

VCG does not predict crash drawdowns the way CRI does. The candidate Y-labels (forward 5d/20d realized vol regime, intraday-range expansion, regime-state transition probability) are unresolved.

**Decision (this closure):** explicitly document in `vcg-methodology.md` §6 that VCG is a *descriptive* regime indicator without a crash-AUC analog in V1. The backtest's named-crash sanity check (§8.3) is the eyeball evidence; an OOS AUC awaits a defensible label definition. Validation notebook is deferred; tracked as an open question in the closure memo (§13).

### 11.3 v2 calibration decision (descriptive, not binary)

The §8.3 ±5d named-crash window table is the input. There is **no** automatic PASS/FAIL gate (codex correctly flagged that "fires reasonably" is undefinable when `vcg_adj → 0` during high-VIX regimes). The decision is qualitative judgment from the evidence:

- If the raw `vcg` distribution shows clear elevation in the pre-crash days (offsets `-5` through `-1`) for most named events, with `sign_ok=true`, the residual model is doing real work → **v1 is documented as defensible-as-ported**, v2 listed as an open research question (not in this closure)
- If raw `vcg` is flat or noisy across the pre-crash windows, or `sign_ok` flips during most events, the residual model is not earning its keep → **document the failure honestly** in `vcg-methodology.md` §6 (known limitations). Do NOT ship a v2 calibration inside this closure — open a separate `docs/superpowers/specs/YYYY-MM-DD-vcg-v2-calibration-design.md` spec for the recalibration work

Either way, this closure ships v1 with the descriptive evidence persisted to `summary.extras.named_crash_window` so future research can re-evaluate without re-running the script.

### 11.4 `tests/integration/regime/test_vcg_oos_gate.py` (DEFERRED)

Until §11.2 has a defensible Y-label, an OOS gate test is premature. Defer with the validation notebook.

## 12. CLAUDE.md updates

### 12.1 `docs/research/regime/CLAUDE.md`

Current rules only mention CRI. Add:

- "Before changing any threshold in `vcg_scoring.py`, update the relevant section of `vcg-methodology.md` with the new threshold and rationale."
- "After running a backtest (either indicator), inspect via `SELECT * FROM uw_scan.regime_backtest_runs ORDER BY created_at DESC LIMIT 10`. Do not commit CSV/MD output files — the DB is the source of truth."
- "VCG's v1 calibration is as-ported from xenon. Recalibration to v2 requires a separate spec under `docs/superpowers/specs/`."

### 12.2 `docs/research/regime/cri-methodology.md` §5

Add a subsection "Academic primary sources" with the four CRI citations from §4.1, cross-referenced from each component's discussion in §2.

## 13. Closure memo — `docs/research/regime/closure-2026-05-24.md`

Structure (~3-4 pages):

1. **What's done** — both indicators have DB-of-record backtests; methodology docs; academic foundations; CLAUDE.md update rules
2. **What's queryable** — SQL cookbook (latest run per indicator, level distribution per calendar year, comparing two `composite_version`s, named-crash hits for any indicator/version, etc.)
3. **What this enables** — research questions now cheap to ask:
   - "Does VCG fire during regime X?" → SQL
   - "What does CRI v3 say about every Fed meeting day?" → SQL
   - "How would a candidate v4 calibration change CRI's 20y AUC?" → bump `COMPOSITE_VERSION` in `cri_scorers.py` on an experiment branch, re-run `scripts/backtest_cri.py --note "v4 candidate: VVIX floor 75 / VIX RoC sub-score"`, compare runs side-by-side via SQL (cookbook query below)
4. **What's deferred (with rationale)** — VCG v2 calibration (separate spec if owed); VCG OOS validation notebook (need Y-label); per-ticker GEX-as-regime (out of scope); Goyal-Saretto §1.5 generic schema (IPCA-specific)
5. **Open research questions** — pulled from `cri-methodology.md` §7 "What we deliberately did not change," plus any surfaced by the VCG diagnostic
6. **How to extend** — for a future contributor: how to run a new calibration, where the math lives, what the version conventions are

## 14. Order of operations

1. Migration 057 (BEGIN/COMMIT-wrapped; partial-table preexistence handled by drop-and-reapply runbook per §15 risk 3, NOT in-migration constraint surgery) + `RegimeBacktestRepository` (insert_run → bulk_insert_daily → mark_run_completed contract) + repository tests
2. Refactor `vcg_scoring.py`: add `COMPOSITE_VERSION = 1`; extract `_interpretation_for_index` from `evaluate_signal`; existing tests still pass
3. CRI lift-and-shift: modify `backtest_cri.py` to write DB (derive `composite_version` from `cri_scorers.COMPOSITE_VERSION`); extract renderer into `reports/regime_backtest_report.py` (using `daily[0].trade_date` for window start); snapshot test against existing `cri-backtest.md`
4. Modify `regime_validation.py`: DB-first with file fallback (router code from §9.1)
5. Update `tests/integration/regime/test_cri_oos_gate.py`: read `summary.oos` from the latest DB run instead of `oos-summary.json` (closes codex P1 — file removal must not silently disable the gate)
6. `scripts/backtest_vcg.py` (new) — first 20-year VCG v1 run; populate `summary.extras.named_crash_window`
7. `vcg-methodology.md` (with `COMPOSITE_VERSION` documented + v2-decision §11.3)
8. `cri-methodology.md` §5 augmentation with academic citations
9. CLAUDE.md update + closure memo
10. **Single PR for steps 1-9.** Files remain in git (router fallback active).
11. **Follow-up PR (after manual prod gate)**: verify `SELECT COUNT(*) FROM uw_scan.regime_backtest_runs WHERE indicator='cri' AND completed_at IS NOT NULL  -- expect ≥ 1`, then delete `cri-backtest.{md,csv}`, `oos-summary.json`, and the fallback block in `regime_validation.py`

Steps 1-9 are atomically reviewable in one PR. Step 11 is mechanical and revertable. Splitting prevents the deploy-order outage codex flagged.

## 15. Risks

1. **`reports/regime_backtest_report.py` byte-drift from current `cri-backtest.md`** — renderer must use `daily[0].trade_date` for window start (not `run.start_date`) because `rolling_compute` skips the first 150 sessions (`scripts/backtest_cri.py:128`). *Mitigation:* snapshot-test against the existing checked-in `cri-backtest.md` byte-for-byte; intentional drift documented in the test fixture.
2. **VCG v1 diagnostic is descriptive, not binary** — pre-codex revisions of this spec had a PASS/FAIL eyeball gate that collapses to "is VIX high?" because `vcg_adj → 0` at `VIX ≥ 48`. *Mitigation:* §8.3 ±5d named-crash window exposes raw `vcg` + `sign_ok`; §11.3 names the qualitative call honestly.
3. **Migration 057 conflict with a parallel branch** — two failure modes:
   - **Slot collision**: another branch grabs `057_*.sql` before this lands. *Mitigation:* re-check `src/uw_scan/storage/migrations/` for collisions at PR-open time and renumber to the next free slot if needed.
   - **Partial table from another branch**: an abandoned/reverted branch left `regime_backtest_runs` in the DB without the constraints in §6. This migration's `CREATE TABLE IF NOT EXISTS` will skip table creation but the existing definition won't match this spec — subsequent inserts may then fail at the application layer (e.g., script tries to write `window_days=150` into a non-existent column). *Mitigation:* runbook step — if `057` fails or downstream inserts reject, the recovery is `DROP TABLE IF EXISTS uw_scan.regime_backtest_daily; DROP TABLE IF EXISTS uw_scan.regime_backtest_runs; \i src/uw_scan/storage/migrations/057_regime_backtest_results.sql`. The BEGIN/COMMIT wrap means a failed migration cannot leave half-built objects.
4. **Academic citation drift** — papers can change DOI / be retracted. *Mitigation:* all citations verified 2026-05-24 with journal-volume-page details captured in §4; the spec is dated and re-verifiable.
5. **Deploy-order outage** — addressed by the §9.1 router fallback and §10.4 phased file-removal. Without the fallback, an API deploy ahead of the first prod backtest run would serve 503 to `/regime`.
6. **OosSummary contract drift** — `summary.oos` MUST exactly match the existing Pydantic model (`as_of`, `notebook`, `method`, `labels[]`, `scores[]`, `interpretation`). *Mitigation:* schema §6 sample JSON shows the exact shape; backtest_cri.py constructs the dict from a typed `OosSummary` instance before persisting (round-trip validation), so a drift between code and DB cannot ship.

## 16. Open questions for user review

Three decisions I'd like confirmed before invoking writing-plans:

### Q1. Endpoint `/api/regime/backtest/{indicator}/runs` — defer or include?

Listed recent runs would support the "research further" workflow but no UI consumer exists today.

**Recommendation:** **defer** — trivial to add when a UI surface needs it, no architectural lock-in.

### Q2. After reviewing the §8.3 ±5d named-crash window evidence, do we ship v1 with the descriptive verdict, or hold the closure until v2 calibration?

**Recommendation:** **ship v1** with whatever verdict the evidence supports (defensible / not defensible / needs more work — documented in `vcg-methodology.md` §6 either way). v2 is a separate spec if owed. The closure's value is parity-on-scaffolding; calibration iteration is what *uses* the scaffolding.

### Q3. Single PR or phased PRs?

Phase 1 (persistence + CRI lift-and-shift) is independently shippable. Phase 2 (VCG backtest + methodology doc) depends on Phase 1's repository.

**Recommendation:** **single PR**. The work is small enough (~1.5 days) and Phase 2 cites Phase 1's outputs (VCG methodology doc references the backtest run row). Splitting creates a "half-closed" mid-state we already have.

## 17. Out-of-scope items, tracked for future research

These belong to the regime workspace but are not in this closure:

- VCG v2 calibration (if owed by the diagnostic)
- VCG OOS validation notebook + Y-label definition
- The `/api/regime/backtest/{indicator}/runs` endpoint
- Per-ticker GEX-as-regime
- Migrating both backtests onto the Goyal-Saretto §1.5 generic schema (would only make sense if IPCA work also lands here, currently separate)
- VIX term-structure (contango/backwardation flip) as a CRI component — flagged in `cri-methodology.md` §5 as a follow-up spec

## 18. Acceptance criteria

This closure is "done" when all of the following hold:

### Primary PR (steps 1-9 of §14)
- [ ] Migration `057` applied cleanly via `bash scripts/migrate.sh`; `regime_backtest_runs` and `regime_backtest_daily` exist with the §6 constraints
- [ ] Re-applying migration `057` against a DB that already has the tables is a no-op (idempotency)
- [ ] `src/uw_scan/cards/vcg_scoring.py` exports `COMPOSITE_VERSION = 1` and the new `_interpretation_for_index` helper; existing VCG tests still pass
- [ ] `scripts/backtest_cri.py` runs cleanly against 2006-03-06 → today; persists ≥4,900 daily rows; `composite_version` matches `cri_scorers.COMPOSITE_VERSION` automatically; logs the run_id
- [ ] `scripts/backtest_vcg.py` runs cleanly against 2007-04-11 → today (HYG-bound); persists ≥4,500 daily rows; `summary.extras.named_crash_window` populated for all dates in `NAMED_CRASH_DATES`
- [ ] `summary.oos` for the CRI run validates against `OosSummary` Pydantic model with no errors; `summary.oos` for VCG runs is `null`
- [ ] CRI `regime_backtest_daily.level` values are exactly `LOW`/`ELEVATED`/`HIGH`/`CRITICAL`; VCG values are from the documented enum
- [ ] `GET /api/regime/validation` returns 200 with response shape byte-equivalent to pre-PR behavior, **whether** a DB run exists (DB path) **or not** (file fallback path)
- [ ] `tests/integration/regime/test_cri_oos_gate.py` updated to read **`summary.oos.versions`** (NOT `summary.oos.scores`) from the latest DB CRI run, preserving the existing `versions[].version` lookup pattern. Tolerance semantics unchanged: `current_version_auc >= v1_baseline_auc - BASELINE_TOLERANCE (0.02)`. Pydantic v2 default `extra="ignore"` on `OosSummary.model_validate` means `versions` can sit inside `summary.oos` without breaking the model; the test bypasses the API model and reads the dict directly. **CI test database needs a seeded run** — either a pytest fixture that inserts a representative `regime_backtest_runs` row + daily rows before the gate test, OR a CI step that runs `backtest_cri.py` against a fixture DB. The skip path on missing `oos-summary.json` is removed only after the seed mechanism is in place; otherwise CI would silently skip and disable the regression gate (closes codex P2 finding on the gate-seed contract)
- [ ] `vcg-methodology.md` exists with all 7 required sections (§11.1) including the `vcg_adj → 0 at VIX≥48` limitation
- [ ] `closure-2026-05-24.md` exists with the SQL cookbook including a "compare two composite_version runs side-by-side" query
- [ ] `tests/unit/storage/test_regime_backtest_repository.py` passes
- [ ] `tests/unit/reports/test_regime_backtest_report.py` snapshot matches existing `cri-backtest.md` byte-for-byte (using `daily[0].trade_date` for window start)
- [ ] All existing tests in `tests/integration/regime/` and `tests/integration/api/test_regime_validation_endpoint.py` still pass

### Follow-up PR (step 11 of §14)
- [ ] Production has `SELECT COUNT(*) FROM uw_scan.regime_backtest_runs WHERE indicator='cri' AND completed_at IS NOT NULL  -- expect ≥ 1` (manual gate)
- [ ] `docs/research/regime/cri-backtest.md`, `cri-backtest.csv`, `oos-summary.json` removed
- [ ] Fallback block in `regime_validation.py` (§9.1) removed
- [ ] `tests/integration/api/test_regime_validation_endpoint.py` updated to assert DB-only path; no regression on response shape

---

## Decision log (filled during execution)

- *To be populated*: actual v3 CRI 20y AUC vs notebook baseline (sanity check that DB-side rolling matches notebook-side)
- *To be populated*: VCG v1 diagnostic outcome (PASS / FAIL)
- *To be populated*: any adjusted thresholds or implementation surprises
