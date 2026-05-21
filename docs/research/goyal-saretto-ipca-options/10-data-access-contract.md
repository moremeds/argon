# 10 — Data access contract

**Purpose:** the **interface** for `src/uw_scan/research/data_access.py` — the read-side layer that backs both the notebook (doc 07) and the backtester (doc 13). Implementation comes later; this doc is the contract.

## Why this matters

The notebook and the backtester need the same panels, with the same look-ahead rules, the same universe filter, and the same sign convention. If those rules live in three places, they will drift. This module is the single point of truth for "what is the value of signal X for ticker T at month-end M, where I am only allowed to know things ≤ M."

## Module location

`src/uw_scan/research/data_access.py`

The `research/` sub-tree is for research code that is **read-only** against production tables. It does not extend `repository.py` and does not introduce mutations. It may compose existing storage mixins for queries.

## Return type convention

All "panel" functions return **`pandas.DataFrame`** keyed by `(ticker, month_end)`, with columns named for the characteristic. This matches notebook ergonomics and minimizes round-trips. Scalar getters return `Decimal` (or `None` for missing).

## Public surface

```python
# src/uw_scan/research/data_access.py
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Optional
import pandas as pd
import psycopg


# -----------------------------------------------------------------------------
# Universe & calendar
# -----------------------------------------------------------------------------

def get_universe(
    conn: psycopg.Connection,
    month_end: date,
    *,
    min_history_days: int = 126,
) -> list[str]:
    """Return tickers eligible at this month-end.

    Filters:
      - in watchlist
      - massive ticker_type == 'CS' (common stock; drops ETFs, indices, ADRs)
      - has ≥ min_history_days of vrp_daily history on or before month_end

    Drop list is *also* available via `get_universe_drop_log(month_end)` for
    audit / notes purposes.
    """


def get_universe_drop_log(
    conn: psycopg.Connection,
    month_end: date,
    *,
    min_history_days: int = 126,
) -> dict[str, str]:
    """Return {ticker -> reason} for tickers in watchlist but excluded by get_universe.

    Reason strings: 'not_common_stock', 'history_too_short', 'no_data'.
    """


def month_end_calendar(
    start: date,
    end: date,
) -> list[date]:
    """Return last trading days of each calendar month in [start, end], NYSE.

    Uses pandas_market_calendars or our own holiday list — TBD at implementation.
    """


def resolve_observation_date(
    conn: psycopg.Connection,
    ticker: str,
    month_end: date,
    *,
    fallback_window_trading_days: int = 3,
) -> Optional[date]:
    """Return the actual date used for ticker T at month-end M.

    If vrp_daily has a row on month_end, returns month_end. Otherwise walks
    backwards up to fallback_window_trading_days; returns None if nothing found
    in that window. Used to make 'ticker has data this month' explicit.
    """


# -----------------------------------------------------------------------------
# Core option-side panels (Phase 1 — read existing tables)
# -----------------------------------------------------------------------------

def get_rv_iv_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """Returns paper-signed RV − IV.

    Reads `v_rv_iv_paper_sign.rv_minus_iv` (the view created by migration 049).
    NEVER reads `vrp_daily.vrp` directly — that column historically held the
    opposite sign and is the source of past sign-bugs.

    Columns: ['ticker', 'month_end', 'rv', 'iv', 'rv_minus_iv'].
    Indexed by (ticker, month_end). NaN for unresolved (ticker, month) cells.
    """


def get_iv_skew_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """25Δ risk-reversal skew from `risk_reversal_skew_history`.

    Columns: ['ticker', 'month_end', 'rr_25d', 'rr_25d_zscore'].
    """


def get_stock_chars_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """Stock-level characteristics derived from `daily_ohlc`.

    Columns:
      - 'log_close'           : log of month-end close (paper: Stock price)
      - 'ret_1m'              : 1-month return
      - 'ret_11m_skip1'       : 11-month return skipping the most recent month (momentum, paper convention)
      - 'max10_3m'            : avg of top-10 daily returns over the prior 3 months
      - 'rv_12m'              : 12-month realized vol (paper: RV)
      - 'rskew_12m'           : 12-month realized skew
      - 'rkurt_12m'           : 12-month realized kurt
      - 'autocorr_6m'         : 6-month autocorrelation of daily returns
    """


def get_flow_chars_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """Per-ticker option-flow characteristics from `options_volume_daily`.

    Columns:
      - 'opt_dollar_vol_eom'      : month-end $ option volume (call + put premium)
      - 'net_premium_imbalance'   : net_call_premium - net_put_premium
      - 'aggressive_flow_ratio'   : (call_volume_ask_side + put_volume_bid_side) / total_volume
      - 'opt_vol_z_3m'            : 3-month z-score of total option volume
    """


def get_cri_components_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """CRI component snapshots if available; NaN-filled where missing.

    Currently `cri_snapshots` is market-level (SPX) only — this getter is a
    forward-looking interface that will populate once per-ticker CRI lands.
    """


# -----------------------------------------------------------------------------
# Flow / dealer-positioning panels (Phase 2 — gated by matrix-state backfill)
# -----------------------------------------------------------------------------

def get_vanna_charm_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """Vanna and charm proxies from `vanna_signals` and `charm_signals`.

    Columns:
      - 'dealer_net_vanna_proxy'
      - 'dealer_net_charm_proxy'
      - 'pin_distance_sigma'
      - 'gamma_regime'             : enum (categorical-coded)

    PRE-PHASE-2: returns mostly NaN — only 4 tickers × 5 days populated.
    POST-PHASE-2: should cover the full universe.
    """


def get_gex_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """Greek-exposure-daily panel from `greek_exposure_daily`.

    Columns:
      - 'net_gex'
      - 'gex_call_minus_put'
      - 'zero_gamma_distance'

    PRE-PHASE-2: only 2 tickers populated.
    """


# -----------------------------------------------------------------------------
# Firm-level characteristics (Phase 3 — gated by massive fundamentals fetcher)
# -----------------------------------------------------------------------------

def get_firm_chars_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    tickers: list[str],
) -> pd.DataFrame:
    """Compustat-style firm characteristics.

    Every column is aligned to the **most recently filed** quarter as of
    month_end (filing-date lag, not period-end lag — see doc 13 §look-ahead).

    Columns:
      - 'mcap'             : market_cap (paper: MarketCap)
      - 'assets'           : total assets (paper: Assets)
      - 'debt'             : total debt (paper: Debt)
      - 'leverage'         : debt / assets (paper: Leverage)
      - 'book_to_market'   : shareholders_equity / market_cap (paper: BM)
      - 'profitability'    : gross_profit / assets (paper: Profitability)
      - 'cash_to_asset'    : cash / assets (paper: Cash to asset)
      - 'roe'              : net_income / shareholders_equity (paper: ROE)
      - 'profit_margin'    : profit_margin (paper: Profit margin)
      - 'external_fin'     : (issuance_equity + issuance_debt) / assets (paper: ExternalFin)
      - 'newiss_1y'        : 1-year share issuance (paper: 1yr NewIss)
      - 'newiss_5y'        : 5-year share issuance (paper: 5yr NewIss)
      - 'z_score'          : Dichev 1998 composite (paper: Z-score)
      - 'cashflow_var_60m' : rolling 60-month variance of FCF/MktCap (paper: CashFlowVar)
                            NaN for tickers with < 60 months of FCF history
      - 'rsi'              : days-to-cover from /stocks/v1/short-interest (paper: RSI)
                            Forward-filled between biweekly settlement dates
      - 'available_from'   : earliest filing_date the row could have been built from
                            (used by callers to filter look-ahead)

    PRE-PHASE-3: raises NotImplementedError if called.
    """


# -----------------------------------------------------------------------------
# Composite-panel helper
# -----------------------------------------------------------------------------

def get_full_panel(
    conn: psycopg.Connection,
    month_ends: list[date],
    *,
    universe: Optional[list[str]] = None,  # None → all eligible tickers per month
    include_firm_chars: bool = False,      # True only if Phase 3 has shipped
    include_flow_chars: bool = False,      # True only if Phase 2 has shipped for these tickers
) -> pd.DataFrame:
    """Join all panels above for an L1 backtest run.

    Returns a DataFrame indexed by (ticker, month_end) with every characteristic
    we have, NaN for missing cells. Universe is *recomputed per month_end* if
    not provided — drops change over time as new tickers cross the
    min_history_days threshold.
    """
```

## Implementation notes for whoever builds this

### Reads, not writes

This module **only reads** from existing tables. It does not introduce mutations. It does not extend `repository.py`. If a query needs persistence, that persistence belongs in the appropriate `<domain>_repository.py` mixin — `data_access.py` calls the mixin's read method.

### Connection lifecycle

All public functions take an explicit `psycopg.Connection` as the first arg. The notebook and the backtester are responsible for opening / closing connections. `data_access.py` does not hold connection state.

### NaN handling

Every panel returns NaN (not `None`, not 0.0, not a sentinel) for missing (ticker, month_end) cells. Callers can drop NaN with `pd.dropna(subset=[col])` per their needs. **Never silently impute.**

### Performance

For a 12-month × 103-ticker run, each panel returns ~1,200 rows. The composite panel returns ~1,200 rows × ~25 columns. This is small enough that a single SELECT per panel is fine. No batching or caching.

For larger runs (e.g., expanding to 5-year history once `vrp_daily` accumulates) the per-panel pattern still works but consider adding a `_cache_key` parameter so the backtester can memoize.

### Testing

Per project convention, every public function in this module gets a unit test in `tests/research/test_data_access.py` using `pytest-postgresql`. Fixtures should:
- Insert minimal `vrp_daily` rows for 3 tickers × 6 months
- Verify universe filter drops the ETF in the fixture
- Verify sign-flip view returns `rv − iv`, not `iv − rv`
- Verify NaN propagation when a ticker is missing a month

## Dependency on other docs

- **Sign-flip view** — must be created in `migrations/049_v_rv_iv_paper_sign.sql` before `get_rv_iv_panel()` works. Step 0 in doc 13.
- **Universe filter** — depends on Phase 3's `ticker_type` column on `fundamentals_repository.tickers_metadata` (or equivalent) once we persist massive's `/v3/reference/tickers` response. **Until Phase 3 lands**, `get_universe()` falls back to a hard-coded list of known non-CS tickers (SPY, QQQ, IWM, SPX, DIA, …) defined inline in `universe.py`.
- **Firm-chars panel** — gated by Phase 3 (doc 09 + doc 14 endpoint list).
- **Flow-chars panel** — gated by Phase 2 backfill of vanna/charm/matrix-state for the full watchlist.

## Open questions before implementation

1. **Calendar source.** `pandas_market_calendars` adds a dependency; alternatively we maintain our own NYSE holiday list. The project already has trading-day math in some places — audit before choosing.
2. **Annual vs quarterly for firm chars.** Paper uses quarterly. The `/v2`/`/vX` endpoints provide both. We use quarterly (lower lag, finer resolution).
3. **Forward-fill RSI between biweekly settlements?** Paper does. So do we. Document the convention in the panel docstring.
4. **Watchlist version pinning.** `watchlist` changes over time. A run's `universe_spec` JSONB in `backtest_runs` (doc 13) must capture the *snapshot* of watchlist membership at run time, not a live ref. Implementation must snapshot.

## Status

- Interface designed: **this doc**
- Implementation: **not started**
- Migration 049 (sign-flip view): **not started**
- Will be built as Step 1 in doc 13's critical-path plan
