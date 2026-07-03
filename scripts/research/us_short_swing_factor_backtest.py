"""Rolling backtest for the US short-swing factor screen.

This is an alpha-layer sanity check, not an options PnL simulator. It tests
whether the factor selection method would have produced useful 3d/5d
cross-sectional long-short stock returns before option-chain constraints.
"""

from __future__ import annotations

import argparse
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from uw_scan.config import Settings

from us_short_swing_factor_scan import (
    DEFAULT_APEX_URL,
    DEFAULT_OUTPUT_DIR,
    IDEA_FAMILY,
    _factor_library,
    _ic_stats,
    _load_context,
    _load_ohlc,
    _markdown_table,
    _spearman_by_date,
    _wide,
    _zscore_rank,
)


def _annualized_sharpe(returns: pd.Series, hold_days: int) -> float | None:
    returns = pd.to_numeric(returns, errors="coerce").dropna()
    if len(returns) < 20:
        return None
    std = float(returns.std(ddof=1))
    if std <= 0:
        return None
    periods = 252.0 / float(hold_days)
    return float(returns.mean() / std * math.sqrt(periods))


def _max_drawdown(equity: pd.Series) -> float | None:
    equity = pd.to_numeric(equity, errors="coerce").dropna()
    if equity.empty:
        return None
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def _select_factors(
    factors: dict[str, pd.DataFrame],
    forward: pd.DataFrame,
    asof: Any,
    lookback: int,
    min_names: int,
    min_ic_dates: int,
    min_abs_ic: float,
    max_factors: int,
) -> pd.DataFrame:
    dates = forward.index[forward.index < asof]
    if len(dates) < lookback:
        return pd.DataFrame()
    window_dates = dates[-lookback:]
    rows: list[dict[str, Any]] = []
    for name, frame in factors.items():
        ic = _spearman_by_date(frame.loc[window_dates], forward.loc[window_dates], min_names)
        mean, t_stat, hit, n_dates = _ic_stats(ic)
        if mean is None or n_dates < min_ic_dates or abs(mean) < min_abs_ic:
            continue
        rows.append(
            {
                "factor": name,
                "idea_family": IDEA_FAMILY.get(name, "other"),
                "ic_mean": mean,
                "ic_t": t_stat,
                "ic_hit": hit,
                "dates": n_dates,
                "quality": abs(mean) * 100 + (abs(t_stat or 0) * 0.5),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["quality", "dates"], ascending=False).head(max_factors)


def _score_asof(
    selected: pd.DataFrame,
    factors: dict[str, pd.DataFrame],
    asof: Any,
    tickers: pd.Index,
) -> pd.Series:
    composite = pd.Series(0.0, index=tickers)
    total_weight = 0.0
    for _, row in selected.iterrows():
        factor = str(row["factor"])
        ic_mean = float(row["ic_mean"])
        orientation = 1.0 if ic_mean >= 0 else -1.0
        signal = _zscore_rank(factors[factor].loc[asof].reindex(tickers)) * orientation
        weight = abs(ic_mean)
        composite = composite.add(signal.fillna(0.0) * weight, fill_value=0.0)
        total_weight += weight
    if total_weight > 0:
        composite = composite / total_weight
    return composite


def _run_backtest(args: argparse.Namespace) -> dict[str, Path]:
    settings = Settings.from_env()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    watchlist, _scanner = _load_context(settings)
    tickers = watchlist["ticker"].astype(str).str.upper().tolist()
    ohlc = _load_ohlc(settings, tickers, args)
    matrices = _wide(ohlc, args.min_obs)
    close = matrices["close"]
    factors = _factor_library(matrices)
    forward = {
        horizon: close.shift(-horizon) / close - 1.0
        for horizon in args.horizons
    }

    start = pd.to_datetime(args.backtest_start).date()
    trade_dates = [
        dt
        for dt in close.index
        if dt >= start and all(dt in forward[h].index for h in args.horizons)
    ]
    trade_dates = trade_dates[:-max(args.horizons)]

    rows: list[dict[str, Any]] = []
    factor_use: list[dict[str, Any]] = []
    tickers_idx = pd.Index(close.columns)

    for dt in trade_dates:
        selected = _select_factors(
            factors,
            forward[args.primary_horizon],
            dt,
            args.ic_lookback,
            args.min_names,
            args.min_ic_dates,
            args.min_abs_ic,
            args.max_factors,
        )
        if selected.empty:
            continue
        score = _score_asof(selected, factors, dt, tickers_idx).dropna()
        if len(score) < max(args.top_n * 2, args.min_names):
            continue
        longs = score.nlargest(args.top_n).index.tolist()
        shorts = score.nsmallest(args.top_n).index.tolist()
        for _, row in selected.iterrows():
            factor_use.append({"date": dt, **row.to_dict()})
        rec: dict[str, Any] = {
            "date": dt,
            "factor_count": int(len(selected)),
            "longs": ",".join(longs),
            "shorts": ",".join(shorts),
        }
        for horizon in args.horizons:
            fwd = forward[horizon].loc[dt]
            long_ret = pd.to_numeric(fwd.reindex(longs), errors="coerce").dropna()
            short_raw = pd.to_numeric(fwd.reindex(shorts), errors="coerce").dropna()
            short_ret = -short_raw
            rec[f"long_{horizon}d"] = float(long_ret.mean()) if not long_ret.empty else np.nan
            rec[f"short_{horizon}d"] = float(short_ret.mean()) if not short_ret.empty else np.nan
            rec[f"long_short_{horizon}d"] = float(pd.concat([long_ret, short_ret]).mean()) if not long_ret.empty and not short_ret.empty else np.nan
        rows.append(rec)

    trades = pd.DataFrame(rows)
    factor_use_df = pd.DataFrame(factor_use)
    summary_rows: list[dict[str, Any]] = []
    for leg in ("long", "short", "long_short"):
        for horizon in args.horizons:
            col = f"{leg}_{horizon}d"
            series = pd.to_numeric(trades[col], errors="coerce").dropna() if col in trades else pd.Series(dtype=float)
            equity = (1.0 + series.fillna(0.0)).cumprod()
            summary_rows.append(
                {
                    "leg": leg,
                    "horizon_days": horizon,
                    "trades": int(series.count()),
                    "mean_return": float(series.mean()) if not series.empty else np.nan,
                    "median_return": float(series.median()) if not series.empty else np.nan,
                    "hit_rate": float((series > 0).mean()) if not series.empty else np.nan,
                    "sharpe_overlap_naive": _annualized_sharpe(series, horizon),
                    "max_drawdown_overlap_naive": _max_drawdown(equity),
                }
            )
    summary = pd.DataFrame(summary_rows)
    factor_counts = (
        factor_use_df.groupby(["factor", "idea_family"], as_index=False)
        .agg(uses=("date", "count"), avg_ic=("ic_mean", "mean"), avg_t=("ic_t", "mean"))
        .sort_values(["uses", "avg_ic"], ascending=[False, False])
        if not factor_use_df.empty
        else pd.DataFrame()
    )

    paths = {
        "trades": output_dir / "us_short_swing_backtest_trades.csv",
        "summary": output_dir / "us_short_swing_backtest_summary.csv",
        "factor_use": output_dir / "us_short_swing_backtest_factor_use.csv",
        "report": output_dir / "us_short_swing_backtest_report.md",
    }
    trades.to_csv(paths["trades"], index=False)
    summary.to_csv(paths["summary"], index=False)
    factor_use_df.to_csv(paths["factor_use"], index=False)

    report = f"""# US Short-Swing Factor Backtest

Checked at: `{datetime.now(UTC).isoformat()}`

## Scope

- Universe: active Argon watchlist, `{len(tickers)}` tickers.
- OHLCV source: Apex REST primary; DB fallback.
- Date range loaded: `{close.index.min()}` to `{close.index.max()}`.
- Backtest start: `{args.backtest_start}`.
- Rolling factor lookback: `{args.ic_lookback}` trading rows.
- Primary selection horizon: `{args.primary_horizon}`d forward close-to-close.
- Portfolio: top `{args.top_n}` long and top `{args.top_n}` short by alpha score, equal-weighted.

## Caveats

- This is stock-return alpha backtesting only. It does not model option Greeks, spread, IV crush, assignment, early exercise, commissions, or fill quality.
- Returns are overlapping because a new 3d/5d portfolio is formed each trading day; Sharpe and drawdown are therefore naive diagnostics, not production risk numbers.
- Current Argon scanner/setup context is not backfilled historically, so this backtest tests the alpha layer, not the final live ranking score.

## Summary

{_markdown_table(summary)}

## Most Used Factors

{_markdown_table(factor_counts.head(15))}

## Output Files

- `{paths["trades"]}`
- `{paths["summary"]}`
- `{paths["factor_use"]}`
"""
    paths["report"].write_text(report)
    return paths


def parse_args() -> argparse.Namespace:
    today = date.today().isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apex-url", default=DEFAULT_APEX_URL)
    parser.add_argument("--start-date", default="2023-01-01")
    parser.add_argument("--end-date", default=today)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--min-obs", type=int, default=180)
    parser.add_argument("--min-names", type=int, default=40)
    parser.add_argument("--ic-lookback", type=int, default=252)
    parser.add_argument("--min-ic-dates", type=int, default=120)
    parser.add_argument("--min-abs-ic", type=float, default=0.01)
    parser.add_argument("--max-factors", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--primary-horizon", type=int, default=3)
    parser.add_argument("--horizons", type=int, nargs="+", default=[3, 5])
    parser.add_argument("--backtest-start", default="2025-07-01")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    paths = _run_backtest(parse_args())
    print("wrote:")
    for path in paths.values():
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
