"""US short-swing factor scan inspired by Alpha191 idea families.

This does NOT copy Alpha191 formulas. It maps the useful ideas behind that
library (short-window price/volume interaction, range location, reversal,
breakout, volatility compression, and trend slope) into US-stock-native OHLCV
factors that work on Argon's watchlist and Apex's longer REST history.

Reproduce from the primary repo directory so local DB env files are available:

  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
    uv run python /Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/scripts/research/us_short_swing_factor_scan.py
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
import psycopg

from uw_scan.config import Settings

DEFAULT_APEX_URL = "http://100.66.147.98:8322"
DEFAULT_OUTPUT_DIR = Path("docs/research/alpha191-short-swing")


def _read_sql(conn: psycopg.Connection, query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(query, params)
        cols = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def _load_context(settings: Settings) -> tuple[pd.DataFrame, pd.DataFrame]:
    with psycopg.connect(settings.db_dsn()) as conn:
        watchlist = _read_sql(
            conn,
            """
            SELECT w.ticker,
                   w.sector,
                   c.setup_type,
                   c.setup_direction,
                   c.setup_score::float AS setup_score,
                   c.ret_1d::float AS ret_1d,
                   c.ret_1w::float AS ret_1w,
                   c.ret_30d::float AS ret_30d,
                   c.iv_rank::float AS iv_rank,
                   c.spot::float AS spot,
                   c.updated_at
              FROM uw_scan.watchlist w
              LEFT JOIN uw_scan.watchlist_card c USING (ticker)
             WHERE w.removed_at IS NULL
             ORDER BY w.sort_rank, w.ticker
            """,
        )
        scanner = _read_sql(
            conn,
            """
            SELECT DISTINCT ON (ticker)
                   ticker,
                   section,
                   bias,
                   direction,
                   score::float AS scanner_score,
                   scored_at
              FROM uw_scan.scanner_candidate_snapshots
             WHERE scored_at > now() - interval '7 days'
             ORDER BY ticker, scored_at DESC, score DESC NULLS LAST
            """,
        )
    return watchlist, scanner


def _fetch_apex_daily(apex_url: str, tickers: list[str], start: str, end: str, timeout: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with httpx.Client(base_url=apex_url.rstrip("/"), timeout=timeout) as client:
        for ticker in tickers:
            try:
                resp = client.get(
                    f"/bars/{ticker.upper()}",
                    params={"timeframe": "1d", "start": start, "end": end},
                )
                resp.raise_for_status()
                bars = resp.json().get("bars") or []
            except Exception as exc:  # noqa: BLE001 research robustness
                print(f"apex_fetch_failed ticker={ticker} err={type(exc).__name__}:{str(exc)[:120]}")
                continue
            for bar in bars:
                if bar.get("time") is None or bar.get("close") is None:
                    continue
                rows.append(
                    {
                        "ticker": ticker.upper(),
                        "date": datetime.fromisoformat(bar["time"]).date(),
                        "open": _float_or_nan(bar.get("open")),
                        "high": _float_or_nan(bar.get("high")),
                        "low": _float_or_nan(bar.get("low")),
                        "close": _float_or_nan(bar.get("close")),
                        "volume": _float_or_nan(bar.get("volume")),
                        "vwap": _float_or_nan(bar.get("vwap")),
                        "source": "apex",
                    }
                )
    return pd.DataFrame(rows)


def _float_or_nan(value: Any) -> float:
    try:
        if value is None:
            return float("nan")
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _load_db_ohlc(settings: Settings, tickers: list[str], start: str) -> pd.DataFrame:
    with psycopg.connect(settings.db_dsn()) as conn:
        return _read_sql(
            conn,
            """
            SELECT d.ticker,
                   d.date,
                   d.open::float AS open,
                   d.high::float AS high,
                   d.low::float AS low,
                   d.close::float AS close,
                   d.volume::float AS volume,
                   NULL::float AS vwap,
                   'daily_ohlc' AS source
              FROM uw_scan.daily_ohlc d
             WHERE d.ticker = ANY(%s)
               AND d.date >= %s::date
             ORDER BY d.date, d.ticker
            """,
            (tickers, start),
        )


def _load_ohlc(settings: Settings, tickers: list[str], args: argparse.Namespace) -> pd.DataFrame:
    apex = _fetch_apex_daily(args.apex_url, tickers, args.start_date, args.end_date, args.timeout)
    # Apex should be primary. DB fills any current/recent holes if Apex misses.
    db = _load_db_ohlc(settings, tickers, args.start_date)
    combined = pd.concat([apex, db], ignore_index=True)
    if combined.empty:
        return combined
    combined["date"] = pd.to_datetime(combined["date"]).dt.date
    combined["_source_rank"] = combined["source"].map({"apex": 0, "daily_ohlc": 1}).fillna(9)
    combined = (
        combined.sort_values(["ticker", "date", "_source_rank"])
        .drop_duplicates(["ticker", "date"], keep="first")
        .drop(columns=["_source_rank"])
    )
    return combined


def _wide(ohlc: pd.DataFrame, min_obs: int) -> dict[str, pd.DataFrame]:
    mats = {
        col: ohlc.pivot(index="date", columns="ticker", values=col).sort_index().astype(float)
        for col in ("open", "high", "low", "close", "volume", "vwap")
    }
    keep = mats["close"].columns[mats["close"].notna().sum() >= min_obs]
    mats = {k: v[keep].ffill(limit=3) for k, v in mats.items()}
    # Apex often has null vwap on daily bars. Use a typical-price proxy and keep
    # the caveat in the output report.
    proxy_vwap = (mats["open"] + mats["high"] + mats["low"] + mats["close"]) / 4.0
    mats["vwap"] = mats["vwap"].where(mats["vwap"].notna(), proxy_vwap)
    return mats


def _cs_rank(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rank(axis=1, pct=True)


def _ts_rank(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    return frame.rolling(window).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)


def _reg_slope(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    x = np.arange(window, dtype=float)
    x = (x - x.mean()) / (x.std() or 1.0)
    return frame.rolling(window).apply(lambda y: float(np.polyfit(x, y, 1)[0]), raw=True)


def _factor_library(m: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    open_ = m["open"]
    high = m["high"]
    low = m["low"]
    close = m["close"]
    volume = m["volume"]
    vwap = m["vwap"]
    ret1 = close.pct_change()
    log_volume = np.log(volume.replace(0, np.nan))
    hl_range = (high - low).replace(0, np.nan)
    clv = ((close - low) - (high - close)) / hl_range
    intraday_ret = close / open_ - 1.0
    overnight_gap = open_ / close.shift(1) - 1.0
    dollar_volume = close * volume
    rv5 = ret1.rolling(5).std()
    rv20 = ret1.rolling(20).std()

    factors = {
        # Alpha191 idea family: volume change vs intraday price behavior.
        "pv_corr_fade_6": -log_volume.diff().rolling(6).corr(intraday_ret),
        "pv_corr_follow_10": log_volume.diff().rolling(10).corr(ret1),
        "volume_shock_continuation": _cs_rank(volume / volume.rolling(20).mean()) * _cs_rank(ret1.rolling(3).sum()),
        # Range-location and close pressure.
        "close_location_pressure_3": clv.rolling(3).mean(),
        "accumulation_pressure_6": (clv * volume).rolling(6).sum() / volume.rolling(6).sum(),
        "range_expansion_close_high": (hl_range / close.shift(1)).rolling(3).mean() * clv,
        # Short-window momentum/reversal.
        "mom_3": close / close.shift(3) - 1.0,
        "mom_5": close / close.shift(5) - 1.0,
        "mom_10": close / close.shift(10) - 1.0,
        "reversal_3": -(close / close.shift(3) - 1.0),
        "gap_fade": -overnight_gap,
        "gap_follow": overnight_gap * (volume / volume.rolling(20).mean()),
        # VWAP/typical-price displacement.
        "vwap_reclaim": (close - vwap) / close,
        "vwap_stretch_fade": -((close - vwap) / close).abs() * np.sign(close - vwap),
        "open_vs_vwap_snapback": -(open_ - vwap.rolling(5).mean()) / close,
        # Volatility compression/expansion.
        "vol_compression_breakout": -(rv5 / rv20) * _cs_rank(volume / volume.rolling(20).mean()),
        "low_vol_momentum": -(rv5 / rv20) + _cs_rank(close / close.shift(5) - 1.0),
        "range_compression": -(hl_range / close).rolling(5).mean() / (hl_range / close).rolling(20).mean(),
        # Trend shape.
        "slope_6": _reg_slope(np.log(close), 6),
        "slope_12": _reg_slope(np.log(close), 12),
        "slope_acceleration": _reg_slope(np.log(close), 6) - _reg_slope(np.log(close), 20),
        "drawdown_rebound": (close / close.rolling(20).max() - 1.0) * -1.0 + _cs_rank(ret1),
        # Liquidity/capacity guards as soft alphas.
        "dollar_volume_rank": _cs_rank(dollar_volume.rolling(20).mean()),
        "liquidity_adjusted_momentum": _cs_rank(close / close.shift(5) - 1.0) * _cs_rank(dollar_volume.rolling(20).mean()),
    }
    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in factors.items()}


def _spearman_by_date(factor: pd.DataFrame, fwd_ret: pd.DataFrame, min_names: int) -> pd.Series:
    idx = factor.index.intersection(fwd_ret.index)
    values: list[tuple[Any, float]] = []
    for dt in idx:
        pair = pd.concat([factor.loc[dt], fwd_ret.loc[dt]], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
        if len(pair) >= min_names:
            values.append((dt, pair.iloc[:, 0].rank().corr(pair.iloc[:, 1].rank())))
    return pd.Series(dict(values), dtype=float).sort_index()


def _ic_stats(ic: pd.Series) -> tuple[float | None, float | None, float | None, int]:
    ic = pd.to_numeric(ic, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(ic) < 20:
        return None, None, None, int(len(ic))
    mean = float(ic.mean())
    std = float(ic.std(ddof=1))
    t_stat = mean / (std / math.sqrt(len(ic))) if std > 0 else None
    hit = float((ic > 0).mean())
    return mean, t_stat, hit, int(len(ic))


@dataclass(frozen=True)
class FactorEval:
    factor: str
    idea_family: str
    coverage_latest: int
    ic3_mean: float | None
    ic3_t: float | None
    ic3_hit: float | None
    dates3: int
    ic5_mean: float | None
    ic5_t: float | None
    ic5_hit: float | None
    dates5: int


IDEA_FAMILY = {
    "pv_corr_fade_6": "price_volume_interaction",
    "pv_corr_follow_10": "price_volume_interaction",
    "volume_shock_continuation": "price_volume_interaction",
    "close_location_pressure_3": "range_location",
    "accumulation_pressure_6": "range_location",
    "range_expansion_close_high": "range_location",
    "mom_3": "short_momentum",
    "mom_5": "short_momentum",
    "mom_10": "short_momentum",
    "reversal_3": "short_reversal",
    "gap_fade": "gap",
    "gap_follow": "gap",
    "vwap_reclaim": "typical_price_displacement",
    "vwap_stretch_fade": "typical_price_displacement",
    "open_vs_vwap_snapback": "typical_price_displacement",
    "vol_compression_breakout": "volatility_state",
    "low_vol_momentum": "volatility_state",
    "range_compression": "volatility_state",
    "slope_6": "trend_shape",
    "slope_12": "trend_shape",
    "slope_acceleration": "trend_shape",
    "drawdown_rebound": "short_reversal",
    "dollar_volume_rank": "liquidity",
    "liquidity_adjusted_momentum": "liquidity",
}


def _zscore_rank(series: pd.Series) -> pd.Series:
    ranked = pd.to_numeric(series, errors="coerce").rank(pct=True)
    return (ranked - 0.5) * 2.0


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else f"{float(x):.4f}")
        else:
            out[col] = out[col].map(lambda x: "" if pd.isna(x) else str(x))
    headers = list(out.columns)
    rows = out.values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Path]:
    settings = Settings.from_env()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    watchlist, scanner = _load_context(settings)
    tickers = watchlist["ticker"].astype(str).str.upper().tolist()
    ohlc = _load_ohlc(settings, tickers, args)
    matrices = _wide(ohlc, args.min_obs)
    close = matrices["close"]
    factors = _factor_library(matrices)

    forward = {
        3: close.shift(-3) / close - 1.0,
        5: close.shift(-5) / close - 1.0,
    }
    eval_start = close.index[max(0, len(close.index) - args.eval_days)]
    factor_rows: list[FactorEval] = []
    for name, frame in factors.items():
        latest = pd.to_numeric(frame.iloc[-1], errors="coerce").dropna()
        f_eval = frame.loc[frame.index >= eval_start]
        ic3 = _spearman_by_date(f_eval, forward[3], args.min_names)
        ic5 = _spearman_by_date(f_eval, forward[5], args.min_names)
        ic3_mean, ic3_t, ic3_hit, dates3 = _ic_stats(ic3)
        ic5_mean, ic5_t, ic5_hit, dates5 = _ic_stats(ic5)
        factor_rows.append(
            FactorEval(
                name,
                IDEA_FAMILY.get(name, "other"),
                int(latest.count()),
                ic3_mean,
                ic3_t,
                ic3_hit,
                dates3,
                ic5_mean,
                ic5_t,
                ic5_hit,
                dates5,
            )
        )
    eval_df = pd.DataFrame([r.__dict__ for r in factor_rows])
    eval_df["ic3_abs"] = eval_df["ic3_mean"].abs()
    eval_df["quality"] = (
        eval_df["ic3_abs"].fillna(0) * 100
        + eval_df["ic5_mean"].abs().fillna(0) * 50
        + (eval_df["ic3_hit"].fillna(0) - 0.5).clip(lower=0) * 10
    )
    selected = eval_df[
        (eval_df["coverage_latest"] >= args.min_names)
        & (eval_df["dates3"] >= args.min_ic_dates)
        & (eval_df["ic3_abs"] >= args.min_abs_ic)
    ].sort_values(["quality", "ic3_abs", "dates3"], ascending=False).head(args.max_factors)

    context = watchlist.merge(scanner, on="ticker", how="left").set_index("ticker")
    composite = pd.Series(0.0, index=context.index)
    details: dict[str, dict[str, float]] = {ticker: {} for ticker in context.index}
    total_weight = float(selected["ic3_abs"].sum()) if not selected.empty else 0.0
    for _, row in selected.iterrows():
        factor = str(row["factor"])
        orientation = 1.0 if float(row["ic3_mean"]) >= 0 else -1.0
        signal = _zscore_rank(factors[factor].iloc[-1].reindex(context.index)) * orientation
        weight = float(abs(row["ic3_mean"]))
        composite = composite.add(signal.fillna(0.0) * weight, fill_value=0.0)
        for ticker, value in signal.dropna().items():
            details.setdefault(ticker, {})[factor] = float(value)
    if total_weight > 0:
        composite = composite / total_weight

    scanner_dir = context["direction"].map({"long": 1.0, "short": -1.0}).fillna(0.0)
    setup_dir = context["setup_direction"].map({"bull": 1.0, "bear": -1.0}).fillna(0.0)
    alpha_dir_num = np.sign(composite)
    alpha_dir = pd.Series(alpha_dir_num, index=context.index)
    alignment = (
        (alpha_dir.replace(0, np.nan) == scanner_dir.replace(0, np.nan)).astype(float).fillna(0.0)
        + (alpha_dir.replace(0, np.nan) == setup_dir.replace(0, np.nan)).astype(float).fillna(0.0)
    )
    iv_rank = pd.to_numeric(context["iv_rank"], errors="coerce")
    spot = pd.to_numeric(context["spot"], errors="coerce")
    setup_score = pd.to_numeric(context["setup_score"], errors="coerce").fillna(0)
    scanner_score = pd.to_numeric(context["scanner_score"], errors="coerce").fillna(0)
    dollar_volume_latest = (matrices["close"].iloc[-20:] * matrices["volume"].iloc[-20:]).mean().reindex(context.index)
    liquidity_rank = dollar_volume_latest.rank(pct=True).fillna(0)
    option_iv_bonus = ((iv_rank.clip(15, 85) - 15) / 70).fillna(0).clip(0, 1)
    price_guard = (spot >= args.min_spot).astype(float).fillna(0.0)

    score = (
        composite.abs() * 70
        + alignment * 12
        + setup_score.clip(0, 8) * 1.5
        + scanner_score.clip(0, 20) * 0.5
        + option_iv_bonus * 4
        + liquidity_rank * 5
    ) * price_guard

    ranked = context.copy()
    ranked["alpha_composite"] = composite
    ranked["alpha_direction"] = np.where(composite > 0, "long", np.where(composite < 0, "short", "neutral"))
    ranked["alignment_count"] = alignment
    ranked["liquidity_rank"] = liquidity_rank
    ranked["option_iv_bonus"] = option_iv_bonus
    ranked["option_leverage_score"] = score
    ranked["top_factor_signals_json"] = [json.dumps(details.get(t, {}), sort_keys=True) for t in ranked.index]
    ranked = ranked.reset_index().sort_values("option_leverage_score", ascending=False)
    shortlist = ranked.head(args.shortlist_size)

    paths = {
        "factor_eval": output_dir / "us_short_swing_factor_eval.csv",
        "ranked": output_dir / "us_short_swing_ranked.csv",
        "shortlist": output_dir / "us_short_swing_shortlist.csv",
        "report": output_dir / "us_short_swing_report.md",
    }
    eval_df.sort_values("quality", ascending=False).to_csv(paths["factor_eval"], index=False)
    ranked.to_csv(paths["ranked"], index=False)
    shortlist.to_csv(paths["shortlist"], index=False)

    report = f"""# US Short-Swing Factor Scan

Checked at: `{datetime.now(UTC).isoformat()}`

Reproduce:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
  uv run python {Path(__file__).resolve()} --start-date {args.start_date} --end-date {args.end_date}
```

## Scope

- Universe: active Argon watchlist, `{len(tickers)}` tickers.
- OHLCV source: Apex REST `/bars/{{ticker}}?timeframe=1d` primary; `daily_ohlc` fallback for holes.
- OHLCV matrix: `{close.shape[1]}` tickers x `{close.shape[0]}` daily rows.
- Date range loaded: `{close.index.min()}` to `{close.index.max()}`.
- Evaluation window: last `{args.eval_days}` rows from `{eval_start}`.
- Forward horizons: 3d and 5d close-to-close returns.

## Important Caveats

- This is **US-stock-native**, not a copied Alpha191 implementation.
- Alpha191 is used only as idea inspiration: short-horizon price/volume interaction, range location, reversal, breakout, volatility compression, and slope.
- Apex daily bars currently report null VWAP on tested names, so VWAP-style factors use typical price `(O+H+L+C)/4`.
- Candidate ranking is for short-day swing candidates where options can express leverage. It is not a trade instruction; option structure still needs chain liquidity, spread, IV, event, and risk checks.

## Selected Factor Stack

{_markdown_table(selected[["factor", "idea_family", "ic3_mean", "ic3_t", "ic3_hit", "ic5_mean", "ic5_t", "dates3", "coverage_latest"]])}

## 5 Candidate Shortlist

{_markdown_table(shortlist[["ticker", "sector", "alpha_direction", "option_leverage_score", "alpha_composite", "alignment_count", "setup_direction", "setup_score", "iv_rank", "liquidity_rank", "scanner_score", "direction", "bias"]])}

## Output Files

- `{paths["factor_eval"]}`
- `{paths["ranked"]}`
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
    parser.add_argument("--eval-days", type=int, default=252)
    parser.add_argument("--min-obs", type=int, default=180)
    parser.add_argument("--min-names", type=int, default=40)
    parser.add_argument("--min-ic-dates", type=int, default=120)
    parser.add_argument("--min-abs-ic", type=float, default=0.01)
    parser.add_argument("--max-factors", type=int, default=10)
    parser.add_argument("--shortlist-size", type=int, default=5)
    parser.add_argument("--min-spot", type=float, default=20.0)
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
