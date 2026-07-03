"""Backtest US short-dated swing strategy archetypes.

The goal is to translate Alpha191-style ideas into US-stock strategies for
1-3 week holding windows. This evaluates stock-return alpha only; option
selection still needs a chain/liquidity/IV/event layer.
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
    _cs_rank,
    _factor_library,
    _load_context,
    _load_ohlc,
    _markdown_table,
    _wide,
)


def _sharpe(series: pd.Series, hold_days: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < 20:
        return None
    std = float(values.std(ddof=1))
    if std <= 0:
        return None
    return float(values.mean() / std * math.sqrt(252.0 / hold_days))


def _max_drawdown(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    equity = (1.0 + values).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def _summary(series: pd.Series, hold_days: int) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return {
        "trades": int(values.count()),
        "mean_return": float(values.mean()) if not values.empty else np.nan,
        "median_return": float(values.median()) if not values.empty else np.nan,
        "hit_rate": float((values > 0).mean()) if not values.empty else np.nan,
        "sharpe_overlap_naive": _sharpe(values, hold_days),
        "max_drawdown_overlap_naive": _max_drawdown(values),
    }


def _rank_unit(frame: pd.DataFrame) -> pd.DataFrame:
    return (_cs_rank(frame) - 0.5) * 2.0


def _build_strategies(m: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    factors = _factor_library(m)
    close = m["close"]
    volume = m["volume"]
    ret1 = close.pct_change()
    dollar_volume = close * volume
    liquidity = _rank_unit(dollar_volume.rolling(20).mean())
    volume_shock = _rank_unit(volume / volume.rolling(20).mean())
    realized_vol = ret1.rolling(10).std()
    vol_filter = -_rank_unit(realized_vol)

    return {
        "momentum_continuation_2w": {
            "thesis": "When 10-day momentum is confirmed by trend slope and gap follow-through, short-dated calls or call spreads can capture continuation over 1-3 weeks.",
            "entry": "Rank high on 10d momentum, 12d slope, and gap-follow participation; prefer liquid names.",
            "avoid": "Avoid if IV/event risk makes calls too expensive or if the move is purely one-day volume without slope confirmation.",
            "option_expression": "Long calls or call debit spreads, 2-4 week expiry; use spreads when IV rank is elevated.",
            "score": (
                0.40 * _rank_unit(factors["mom_10"])
                + 0.30 * _rank_unit(factors["slope_12"])
                + 0.20 * _rank_unit(factors["gap_follow"])
                + 0.10 * liquidity
            ),
        },
        "trend_exhaustion_fade_1w": {
            "thesis": "Very sharp positive slope acceleration tends to mean-revert; short-dated puts or put spreads can express a 1-week fade.",
            "entry": "Rank low after orienting slope acceleration as a fade signal; strongest when the recent acceleration is extreme.",
            "avoid": "Avoid catalyst breakouts, earnings gaps, and high-short-interest squeeze conditions.",
            "option_expression": "Put debit spreads or small long puts, 1-3 week expiry; spreads preferred when IV is high.",
            "score": -_rank_unit(factors["slope_acceleration"]),
        },
        "gap_follow_through_1w": {
            "thesis": "Gaps with volume participation can keep moving for several sessions in US single names.",
            "entry": "Rank high on gap-follow score and volume shock, with adequate liquidity.",
            "avoid": "Avoid thin names, known news exhaustion, and gaps into major resistance after long prior runs.",
            "option_expression": "Directional calls/puts aligned with the gap, usually 1-2 week expiry; define risk with debit spreads.",
            "score": 0.65 * _rank_unit(factors["gap_follow"]) + 0.25 * volume_shock + 0.10 * liquidity,
        },
        "gap_snapback_fade_1w": {
            "thesis": "Overnight gaps away from typical price often snap back over the next week when not confirmed by follow-through.",
            "entry": "Rank high on gap-fade and open-vs-typical-price snapback signal.",
            "avoid": "Avoid fundamental repricing gaps, earnings days, and sector-wide repricing.",
            "option_expression": "Contrarian calls after down gaps or puts after up gaps; prefer spreads because timing decay is harsh.",
            "score": 0.55 * _rank_unit(factors["gap_fade"]) + 0.45 * _rank_unit(factors["open_vs_vwap_snapback"]),
        },
        "accumulation_breakout_3w": {
            "thesis": "Persistent close-near-high accumulation with volume and range pressure can precede 2-3 week breakouts.",
            "entry": "Rank high on accumulation pressure, range close pressure, and volume participation.",
            "avoid": "Avoid if the name is already extended and IV is pricing the full move.",
            "option_expression": "Call debit spreads, 3-5 week expiry, or defined-risk call calendars when IV term structure supports it.",
            "score": (
                0.45 * _rank_unit(factors["accumulation_pressure_6"])
                + 0.25 * _rank_unit(factors["close_location_pressure_3"])
                + 0.20 * volume_shock
                + 0.10 * vol_filter
            ),
        },
    }


def _evaluate_strategy(
    name: str,
    score: pd.DataFrame,
    close: pd.DataFrame,
    horizons: list[int],
    top_n: int,
    start: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dates = [dt for dt in close.index if dt >= start]
    rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for horizon in horizons:
        fwd = close.shift(-horizon) / close - 1.0
        leg_values = {"long": [], "short": [], "long_short": []}
        for dt in dates[:-horizon]:
            signal = pd.to_numeric(score.loc[dt], errors="coerce").dropna()
            returns = pd.to_numeric(fwd.loc[dt], errors="coerce").dropna()
            available = signal.index.intersection(returns.index)
            if len(available) < top_n * 4:
                continue
            signal = signal.reindex(available)
            returns = returns.reindex(available)
            longs = signal.nlargest(top_n).index.tolist()
            shorts = signal.nsmallest(top_n).index.tolist()
            long_ret = returns.reindex(longs).mean()
            short_ret = -returns.reindex(shorts).mean()
            long_short = np.nanmean([long_ret, short_ret])
            leg_values["long"].append(long_ret)
            leg_values["short"].append(short_ret)
            leg_values["long_short"].append(long_short)
            trade_rows.append(
                {
                    "strategy": name,
                    "date": dt,
                    "horizon_days": horizon,
                    "longs": ",".join(longs),
                    "shorts": ",".join(shorts),
                    "long_return": long_ret,
                    "short_return": short_ret,
                    "long_short_return": long_short,
                }
            )
        for leg, values in leg_values.items():
            summary = _summary(pd.Series(values), horizon)
            rows.append({"strategy": name, "leg": leg, "horizon_days": horizon, **summary})
    return rows, trade_rows


def run(args: argparse.Namespace) -> dict[str, Path]:
    settings = Settings.from_env()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    watchlist, _scanner = _load_context(settings)
    tickers = watchlist["ticker"].astype(str).str.upper().tolist()
    ohlc = _load_ohlc(settings, tickers, args)
    matrices = _wide(ohlc, args.min_obs)
    close = matrices["close"]
    strategies = _build_strategies(matrices)
    start = pd.to_datetime(args.backtest_start).date()

    summary_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    thesis_rows: list[dict[str, Any]] = []
    for name, spec in strategies.items():
        rows, trades = _evaluate_strategy(name, spec["score"], close, args.horizons, args.top_n, start)
        summary_rows.extend(rows)
        trade_rows.extend(trades)
        thesis_rows.append(
            {
                "strategy": name,
                "thesis": spec["thesis"],
                "entry": spec["entry"],
                "avoid": spec["avoid"],
                "option_expression": spec["option_expression"],
            }
        )

    summary = pd.DataFrame(summary_rows)
    trades = pd.DataFrame(trade_rows)
    thesis = pd.DataFrame(thesis_rows)
    shortlist = (
        summary[summary["leg"] == "long_short"]
        .sort_values(["sharpe_overlap_naive", "mean_return"], ascending=False)
        .merge(thesis, on="strategy", how="left")
    )

    paths = {
        "summary": output_dir / "us_short_swing_strategy_backtest_summary.csv",
        "trades": output_dir / "us_short_swing_strategy_backtest_trades.csv",
        "shortlist": output_dir / "us_short_swing_strategy_shortlist.csv",
        "report": output_dir / "us_short_swing_strategy_report.md",
    }
    summary.to_csv(paths["summary"], index=False)
    trades.to_csv(paths["trades"], index=False)
    shortlist.to_csv(paths["shortlist"], index=False)

    headline = shortlist.drop_duplicates("strategy").head(5)
    report = f"""# US Short-Dated Swing Strategy Shortlist

Checked at: `{datetime.now(UTC).isoformat()}`

## Scope

- Universe: active Argon watchlist, `{len(tickers)}` tickers.
- OHLCV source: Apex REST primary; DB fallback.
- Date range loaded: `{close.index.min()}` to `{close.index.max()}`.
- Backtest start: `{args.backtest_start}`.
- Holding horizons: `{", ".join(str(h) for h in args.horizons)}` trading days.
- Portfolio test: top `{args.top_n}` and bottom `{args.top_n}` names by strategy score, equal-weighted.

## Caveats

- This is a stock-return backtest of strategy archetypes, not an options PnL backtest.
- Returns overlap because the strategy forms a new portfolio each trading day.
- No option spread, liquidity, IV crush, earnings, commissions, or fill quality is modeled.
- Alpha191 is idea inspiration only; formulas here are US-stock-native.

## 5 Strategy Shortlist

{_markdown_table(headline[["strategy", "horizon_days", "mean_return", "hit_rate", "sharpe_overlap_naive", "max_drawdown_overlap_naive", "thesis", "option_expression"]])}

## Full Long-Short Summary

{_markdown_table(shortlist[["strategy", "horizon_days", "mean_return", "median_return", "hit_rate", "sharpe_overlap_naive", "max_drawdown_overlap_naive"]])}

## Output Files

- `{paths["summary"]}`
- `{paths["trades"]}`
- `{paths["shortlist"]}`
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
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--horizons", type=int, nargs="+", default=[5, 10, 15])
    parser.add_argument("--backtest-start", default="2025-07-01")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    paths = run(parse_args())
    print("wrote:")
    for path in paths.values():
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
