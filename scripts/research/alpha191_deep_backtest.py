"""Deep single-name backtest of Alpha191-derived momentum + fade signals.

Honest cross-sectional engine (fixes the overlap inflation in the earlier scan):
non-overlapping rebalance every N trading days, quintile long/short, daily
mark-to-market, turnover cost. Universe = S&P 500 + Nasdaq-100 union from the
committed membership tables. Deep apex history (~1995+).

Signals reproduce us_short_swing_factor_scan._factor_library formulas:
  momentum = 0.40*ru(mom_10) + 0.30*ru(slope_12) + 0.20*ru(gap_follow) + 0.10*liq
  fade     = -ru(slope_6 - slope_20)          (ru(x) = (cs_rank(x) - 0.5) * 2)

CAVEATS (in report too): survivorship-biased (today's constituents on old data),
underlying-return only (no options PnL), vwap is a typical-price proxy on daily
bars, quintile L/S is dollar-neutral so Sharpe is selection skill not beta.

Reproduce:
  uv run python scripts/research/alpha191_deep_backtest.py \
    --universe-dir docs/research/alpha191-short-swing/universe \
    --out docs/research/alpha191-short-swing/deep_backtest
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252.0


# ---------- data load (apex-only, concurrent) ----------
def _fetch_one(apex_url: str, ticker: str, start: str, end: str) -> list[dict]:
    url = (
        f"{apex_url}/bars/{ticker}?timeframe=1d"
        f"&start={start}T00:00:00Z&end={end}T00:00:00Z"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            bars = json.load(resp).get("bars", [])
    except Exception:  # noqa: BLE001 research robustness
        return []
    out = []
    for b in bars:
        if b.get("time") is None or b.get("close") is None:
            continue
        out.append(
            {
                "ticker": ticker,
                "date": b["time"][:10],
                "open": b.get("open"),
                "high": b.get("high"),
                "low": b.get("low"),
                "close": b.get("close"),
                "volume": b.get("volume"),
                "vwap": b.get("vwap"),
            }
        )
    return out


def load_apex(
    apex_url: str, tickers: list[str], start: str, end: str, workers: int
) -> pd.DataFrame:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        chunks = ex.map(lambda t: _fetch_one(apex_url, t, start, end), tickers)
    rows = [r for c in chunks for r in c]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for c in ("open", "high", "low", "close", "volume", "vwap"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def wide(ohlc: pd.DataFrame, min_obs: int) -> dict[str, pd.DataFrame]:
    mats = {
        c: ohlc.pivot(index="date", columns="ticker", values=c)
        .sort_index()
        .astype(float)
        for c in ("open", "high", "low", "close", "volume")
    }
    keep = mats["close"].columns[mats["close"].notna().sum() >= min_obs]
    return {k: v[keep].ffill(limit=3) for k, v in mats.items()}


# ---------- signals ----------
def cs_rank(f: pd.DataFrame) -> pd.DataFrame:
    return f.rank(axis=1, pct=True)


def ru(f: pd.DataFrame) -> pd.DataFrame:  # rank-unit -> [-1, 1]
    return (cs_rank(f) - 0.5) * 2.0


def fast_slope(logc: pd.DataFrame, w: int) -> pd.DataFrame:
    """Vectorized OLS slope of logc over a w-window vs a normalized time axis.

    Equal to us_short_swing_factor_scan._reg_slope (asserted in self-check) but
    C-level rolling sums instead of per-window polyfit.
    """
    ps = pd.Series(np.arange(len(logc.index), dtype=float), index=logc.index)
    ry = logc.rolling(w).sum()
    rpy = logc.mul(ps, axis=0).rolling(w).sum()
    sigma = float(np.std(np.arange(w)))  # population std of [0..w-1]
    coef = ps - (w - 1) / 2.0
    return (rpy.sub(ry.mul(coef, axis=0))) / (w * sigma)


def build_scores(m: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close, vol, open_ = m["close"], m["volume"], m["open"]
    logc = np.log(close)
    mom_5 = close / close.shift(5) - 1.0
    mom_10 = close / close.shift(10) - 1.0
    gap_follow = (open_ / close.shift(1) - 1.0) * (vol / vol.rolling(20).mean())
    slope_12 = fast_slope(logc, 12)
    slope_accel = fast_slope(logc, 6) - fast_slope(logc, 20)
    liq = ru((close * vol).rolling(20).mean())
    return {
        "momentum": 0.40 * ru(mom_10)
        + 0.30 * ru(slope_12)
        + 0.20 * ru(gap_follow)
        + 0.10 * liq,
        "fade": -ru(slope_accel),
        "baseline_mom10": ru(mom_10),
        # mirror of short-horizon momentum: long recent losers / short winners
        "reversal_5": -ru(mom_5),
        "reversal_10": -ru(mom_10),
        # long-horizon (Jegadeesh-Titman) momentum: the robust factor
        "lt_mom_3": ru(close / close.shift(63) - 1.0),
        "lt_mom_6": ru(close / close.shift(126) - 1.0),
        "lt_mom_12_1": ru(close.shift(21) / close.shift(252) - 1.0),  # 12-minus-1 month
    }


# ---------- engine: non-overlapping quintile L/S, daily MTM ----------
def run_ls(
    score: pd.DataFrame,
    close: pd.DataFrame,
    horizon: int,
    q: float,
    cost_rate: float,
    min_names: int,
    bt_start: pd.Timestamp,
    skip: int = 0,
) -> tuple[pd.Series, list[dict]]:
    ret = close.pct_change()
    idx = close.index
    dates = [d for d in idx if pd.Timestamp(d) >= bt_start]
    if len(dates) <= horizon:
        return pd.Series(dtype=float), []
    rebals = dates[::horizon][:-1]  # non-overlapping

    weights = pd.DataFrame(0.0, index=idx, columns=close.columns)
    log: list[dict] = []
    prev_w = pd.Series(0.0, index=close.columns)
    for t in rebals:
        s = score.loc[t].dropna()
        s = s[close.loc[t].notna().reindex(s.index).fillna(False)]
        if len(s) < min_names:
            continue
        lo, hi = s.quantile(q), s.quantile(1 - q)
        longs, shorts = s[s >= hi].index, s[s <= lo].index
        if len(longs) == 0 or len(shorts) == 0:
            continue
        w = pd.Series(0.0, index=close.columns)
        w[longs] = 0.5 / len(longs)
        w[shorts] = -0.5 / len(shorts)
        # hold w from t until (exclusive) next rebalance
        nxt = rebals[rebals.index(t) + 1] if t != rebals[-1] else dates[-1]
        weights.loc[t:nxt] = w.values
        one_way = float((w - prev_w).abs().sum()) / 2.0
        prev_w = w
        log.append(
            {
                "rebal_date": t,
                "n_long": len(longs),
                "n_short": len(shorts),
                "one_way_turnover": one_way,
                "longs": ",".join(list(longs)[:20]),
                "shorts": ",".join(list(shorts)[:20]),
            }
        )

    # daily P&L: weight decided at rebalance earns the NEXT day's return
    # weight set at rebalance t normally earns ret(t+1); skip>0 delays entry to
    # t+1+skip to strip non-tradable bid-ask bounce right after the signal.
    daily = (weights.shift(1 + skip) * ret).sum(axis=1)
    # turnover cost charged on each rebalance day
    cost = pd.Series(0.0, index=idx)
    for row in log:
        cost.loc[row["rebal_date"]] = row["one_way_turnover"] * cost_rate
    net = (daily - cost).reindex(dates).fillna(0.0)

    # per-rebalance realized period return (net), for hit rate
    for i, row in enumerate(log):
        t = row["rebal_date"]
        nxt = log[i + 1]["rebal_date"] if i + 1 < len(log) else dates[-1]
        seg = net.loc[t:nxt]
        row["period_ret_net"] = float((1 + seg).prod() - 1)
    return net, log


def run_buyhold(close: pd.DataFrame, bt_start: pd.Timestamp) -> pd.Series:
    ret = close.pct_change()
    daily = ret.mean(axis=1)  # equal-weight available names
    dates = [d for d in close.index if pd.Timestamp(d) >= bt_start]
    return daily.reindex(dates).fillna(0.0)


# ---------- metrics ----------
def metrics(net: pd.Series) -> dict:
    net = net.dropna()
    if len(net) < 60:
        return {}
    eq = (1 + net).cumprod()
    years = len(net) / TRADING_DAYS
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = net.std() * np.sqrt(TRADING_DAYS)
    down = net[net < 0].std() * np.sqrt(TRADING_DAYS)
    dd = float((eq / eq.cummax() - 1).min())
    return {
        "cagr": round(float(cagr), 4),
        "ann_vol": round(float(vol), 4),
        "sharpe": round(float(net.mean() * TRADING_DAYS / vol), 3) if vol else None,
        "sortino": round(float(net.mean() * TRADING_DAYS / down), 3) if down else None,
        "max_drawdown": round(dd, 4),
        "days": len(net),
    }


def per_year(net: pd.Series) -> list[dict]:
    net = net.dropna()
    idx = pd.to_datetime(net.index)
    out = []
    for yr, grp in net.groupby(idx.year):
        v = grp.std() * np.sqrt(TRADING_DAYS)
        out.append(
            {
                "year": int(yr),
                "total_return": round(float((1 + grp).prod() - 1), 4),
                "sharpe": round(float(grp.mean() * TRADING_DAYS / v), 2) if v else None,
                "days": len(grp),
            }
        )
    return out


def _md(df: pd.DataFrame) -> str:  # tiny markdown table, no tabulate dep
    cols = list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = [
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
        for row in df.itertuples(index=False)
    ]
    return "\n".join([head, sep, *body])


def _self_check() -> None:
    # fast_slope must equal a direct polyfit slope
    rng = np.arange(1, 41, dtype=float).reshape(-1, 1) + np.array([0.0, 5.0])
    df = pd.DataFrame(np.log(rng + 100), columns=["A", "B"])
    fs = fast_slope(df, 12).iloc[-1]
    x = np.arange(12, dtype=float)
    x = (x - x.mean()) / (x.std() or 1.0)
    ref = {c: float(np.polyfit(x, df[c].iloc[-12:].to_numpy(), 1)[0]) for c in df}
    for c in df:
        assert abs(fs[c] - ref[c]) < 1e-9, (
            f"fast_slope mismatch {c}: {fs[c]} vs {ref[c]}"
        )


def run(args: argparse.Namespace) -> None:
    _self_check()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    udir = Path(args.universe_dir)
    with (udir / "universe_union.csv").open() as f:
        tickers = [r["ticker"] for r in csv.DictReader(f)]
    # drop the known-broken/thin names so they don't distort the cross-section
    need = udir / "coverage" / "needs_enrichment.csv"
    if need.exists():
        with need.open() as f:
            drop = {
                r["ticker"]
                for r in csv.DictReader(f)
                if r["status"] in {"thin", "missing"}
            }
        tickers = [t for t in tickers if t not in drop]

    cache = out / "ohlc_cache.pkl"
    if args.use_cache and cache.exists():
        print(f"loading OHLC from cache {cache}")
        ohlc = pd.read_pickle(cache)  # noqa: S301 (our own cache file)
    else:
        print(f"loading {len(tickers)} tickers from apex...")
        ohlc = load_apex(
            args.apex_url, tickers, args.start_date, args.end_date, args.workers
        )
        ohlc.to_pickle(cache)
    m = wide(ohlc, args.min_obs)
    close = m["close"]
    print(
        f"universe after min_obs>={args.min_obs}: {close.shape[1]} names, "
        f"{close.index.min()}..{close.index.max()}"
    )
    scores = build_scores(m)
    bt_start = pd.Timestamp(args.backtest_start)

    equity = {}
    summary_rows, year_rows, log_rows = [], [], []
    configs = [
        ("momentum", 5),
        ("momentum", 10),
        ("momentum", 15),
        ("fade", 5),
        ("fade", 10),
        ("fade", 15),
        ("baseline_mom10", 10),
        ("reversal_5", 5),
        ("reversal_5", 10),
        ("reversal_10", 10),
        ("reversal_10", 15),
        ("lt_mom_3", 21),
        ("lt_mom_6", 21),
        ("lt_mom_12_1", 21),
    ]
    for name, h in configs:
        net, log = run_ls(
            scores[name],
            close,
            h,
            args.quantile,
            args.cost_bps / 1e4,
            args.min_names,
            bt_start,
            args.skip,
        )
        if net.empty:
            continue
        cfg = f"{name}_{h}d"
        equity[cfg] = (1 + net).cumprod()
        hit = np.mean([r["period_ret_net"] > 0 for r in log]) if log else None
        for span, seg in (
            ("full", net),
            ("IS_<=2023", net[pd.to_datetime(net.index) < "2024-01-01"]),
            ("OOS_2024+", net[pd.to_datetime(net.index) >= "2024-01-01"]),
        ):
            mt = metrics(seg)
            if mt:
                summary_rows.append(
                    {
                        "config": cfg,
                        "strategy": name,
                        "horizon": h,
                        "span": span,
                        "n_rebalances": len(log),
                        "period_hit_rate": round(float(hit), 3)
                        if hit is not None
                        else None,
                        "avg_one_way_turnover": round(
                            float(np.mean([r["one_way_turnover"] for r in log])), 3
                        )
                        if log
                        else None,
                        **mt,
                    }
                )
        for yr in per_year(net):
            year_rows.append({"config": cfg, **yr})
        for r in log:
            log_rows.append({"config": cfg, **r})

    bh = run_buyhold(close, bt_start)
    equity["buyhold_eqw"] = (1 + bh).cumprod()
    for span, seg in (
        ("full", bh),
        ("IS_<=2023", bh[pd.to_datetime(bh.index) < "2024-01-01"]),
        ("OOS_2024+", bh[pd.to_datetime(bh.index) >= "2024-01-01"]),
    ):
        mt = metrics(seg)
        if mt:
            summary_rows.append(
                {
                    "config": "buyhold_eqw",
                    "strategy": "baseline",
                    "horizon": None,
                    "span": span,
                    **mt,
                }
            )

    pd.DataFrame(equity).to_csv(out / "equity_curves.csv")
    pd.DataFrame(summary_rows).to_csv(out / "metrics_summary.csv", index=False)
    pd.DataFrame(year_rows).to_csv(out / "per_year.csv", index=False)
    pd.DataFrame(log_rows).to_csv(out / "rebalance_log.csv", index=False)

    summ = pd.DataFrame(summary_rows)
    full = summ[summ["span"] == "full"].sort_values("sharpe", ascending=False)
    report = f"""# Alpha191 deep backtest — S&P 500 + Nasdaq-100 single names

Universe: {close.shape[1]} names · history {close.index.min()}..{close.index.max()}
· backtest from {args.backtest_start} · quintile={args.quantile} · cost={args.cost_bps}bps/unit-turnover.

## Headline (full-sample, sorted by Sharpe)

{_md(full[["config", "cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "period_hit_rate", "days"]])}

## Caveats
- **Survivorship-biased**: today's SP500+NDX100 tested on old data; delisted losers absent. Deep numbers overstate. (Fix later via index_membership_changes.csv.)
- Underlying-return only; no options PnL, no earnings/event filter.
- Dollar-neutral L/S -> Sharpe is selection skill, not market beta (cf. buyhold_eqw).
- vwap proxy = typical price on daily bars.

Files: equity_curves.csv, metrics_summary.csv, per_year.csv, rebalance_log.csv

Reproduce: `uv run python scripts/research/alpha191_deep_backtest.py --universe-dir {args.universe_dir} --out {args.out}`
"""
    (out / "report.md").write_text(report)
    print(report)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--universe-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--apex-url", default="http://100.66.147.98:8322")
    p.add_argument("--start-date", default="1995-01-01")
    p.add_argument("--end-date", default="2026-07-06")
    p.add_argument("--backtest-start", default="1997-01-01")
    p.add_argument("--min-obs", type=int, default=252)
    p.add_argument("--min-names", type=int, default=50)
    p.add_argument("--quantile", type=float, default=0.2)
    p.add_argument("--cost-bps", type=float, default=10.0)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument(
        "--use-cache",
        action="store_true",
        help="reuse ohlc_cache.pkl in --out instead of refetching apex",
    )
    p.add_argument(
        "--skip",
        type=int,
        default=0,
        help="delay entry N days after signal (bid-ask-bounce robustness)",
    )
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
