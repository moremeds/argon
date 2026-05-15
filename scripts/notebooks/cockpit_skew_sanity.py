"""Phase 0 Cockpit skew sign-convention sanity check.

Reads persisted 25-delta risk-reversal skew history, computes rolling 180-row
z-scores, and saves distribution/time-series plots under /tmp by default.

Run:
    uv run --with matplotlib python scripts/notebooks/cockpit_skew_sanity.py \
        --env-file /Users/chenxi/projects/unusual-whales/.env
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg
from psycopg import sql

from uw_scan.config import Settings


DEFAULT_TICKERS = ["SPY", "QQQ", "IWM", "SPX"]
ROLLING_WINDOW = 180
PROVISIONAL_MIN_PERIODS = 60


@dataclass(frozen=True)
class RiskOffWindow:
    label: str
    start: date
    end: date


RISK_OFF_WINDOWS = [
    RiskOffWindow("2025 Aug carry-unwind", date(2025, 8, 1), date(2025, 8, 8)),
    RiskOffWindow("2026 Q1 risk-off", date(2026, 2, 20), date(2026, 4, 8)),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional .env path. Defaults to repo-local .env if present.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="Tickers to inspect.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp"),
        help="Directory for cockpit_skew_*.png and summary CSV outputs.",
    )
    return parser.parse_args()


def load_skew(settings: Settings, tickers: list[str]) -> pd.DataFrame:
    start = date.today() - timedelta(days=365)
    query = sql.SQL(
        """
        SELECT ticker, market_date, expiry, risk_reversal
        FROM {schema}.risk_reversal_skew_history
        WHERE delta = 25
          AND ticker = ANY(%s)
          AND market_date >= %s
          AND risk_reversal IS NOT NULL
        ORDER BY ticker, expiry, market_date
        """
    ).format(schema=sql.Identifier(settings.db_schema))

    with psycopg.connect(settings.db_dsn()) as conn:
        return pd.read_sql_query(query.as_string(conn), conn, params=(tickers, start))


def choose_longest_expiry(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw.copy()

    counts = (
        raw.groupby(["ticker", "expiry"], as_index=False)
        .agg(
            rows=("market_date", "count"),
            first_date=("market_date", "min"),
            last_date=("market_date", "max"),
        )
        .sort_values(
            ["ticker", "rows", "last_date", "expiry"],
            ascending=[True, False, False, True],
        )
    )
    chosen = counts.groupby("ticker", as_index=False).head(1)
    chosen_key = chosen[["ticker", "expiry"]]
    return raw.merge(chosen_key, on=["ticker", "expiry"], how="inner")


def compute_zscores(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    out = df.sort_values(["ticker", "market_date"]).copy()
    out["risk_reversal"] = pd.to_numeric(out["risk_reversal"])
    grouped = out.groupby("ticker", group_keys=False)["risk_reversal"]

    rolling = grouped.rolling(
        window=ROLLING_WINDOW,
        min_periods=PROVISIONAL_MIN_PERIODS,
    )
    out["rr_mean_180d"] = rolling.mean().reset_index(level=0, drop=True)
    out["rr_std_180d"] = rolling.std(ddof=0).reset_index(level=0, drop=True)
    out["skew_25d_zscore_180d"] = (
        (out["risk_reversal"] - out["rr_mean_180d"]) / out["rr_std_180d"]
    )
    out.loc[out["rr_std_180d"] == 0, "skew_25d_zscore_180d"] = pd.NA
    out["window_observations"] = (
        grouped.rolling(window=ROLLING_WINDOW, min_periods=1)
        .count()
        .reset_index(level=0, drop=True)
        .astype(int)
    )
    out["strict_180d"] = out["window_observations"] >= ROLLING_WINDOW
    return out


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker, part in df.groupby("ticker"):
        z = part["skew_25d_zscore_180d"].dropna()
        rows.append(
            {
                "ticker": ticker,
                "expiry": part["expiry"].iloc[0],
                "first_date": part["market_date"].min(),
                "last_date": part["market_date"].max(),
                "rows": len(part),
                "zscore_rows": len(z),
                "strict_180d_rows": int(part["strict_180d"].sum()),
                "extreme_negative_days": int((z < -1).sum()),
                "extreme_positive_days": int((z > 1).sum()),
                "last_risk_reversal": part["risk_reversal"].iloc[-1],
                "last_zscore": z.iloc[-1] if not z.empty else pd.NA,
            }
        )
    return pd.DataFrame(rows).sort_values("ticker")


def plot_outputs(df: pd.DataFrame, output_dir: Path) -> tuple[Path, Path]:
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    distribution_path = output_dir / "cockpit_skew_distribution.png"
    timeseries_path = output_dir / "cockpit_skew_timeseries.png"

    valid = df.dropna(subset=["skew_25d_zscore_180d"])

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True, sharey=True)
    for ax, (ticker, part) in zip(axes.ravel(), valid.groupby("ticker")):
        ax.hist(part["skew_25d_zscore_180d"], bins=30, color="#4f7cac", alpha=0.85)
        ax.axvline(-1, color="#b42318", linestyle="--", linewidth=1)
        ax.axvline(1, color="#1b7f4c", linestyle="--", linewidth=1)
        ax.set_title(ticker)
        ax.set_xlabel("skew_25d_zscore_180d")
        ax.set_ylabel("days")
    fig.tight_layout()
    fig.savefig(distribution_path, dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(4, 1, figsize=(13, 10), sharex=True)
    for ax, (ticker, part) in zip(axes, valid.groupby("ticker")):
        ax.plot(
            pd.to_datetime(part["market_date"]),
            part["skew_25d_zscore_180d"],
            color="#1f4e79",
            linewidth=1.25,
        )
        ax.axhline(-1, color="#b42318", linestyle="--", linewidth=1)
        ax.axhline(1, color="#1b7f4c", linestyle="--", linewidth=1)
        ax.axhline(0, color="#777777", linewidth=0.8)
        for window in RISK_OFF_WINDOWS:
            ax.axvspan(window.start, window.end, color="#d92d20", alpha=0.10)
        ax.set_title(ticker)
        ax.set_ylabel("z")
    axes[-1].set_xlabel("market_date")
    fig.tight_layout()
    fig.savefig(timeseries_path, dpi=150)
    plt.close(fig)
    return distribution_path, timeseries_path


def main() -> int:
    args = parse_args()
    settings = Settings.from_env(args.env_file)
    tickers = [ticker.upper() for ticker in args.tickers]
    raw = load_skew(settings, tickers)
    chosen = choose_longest_expiry(raw)
    scored = compute_zscores(chosen)
    summary = summarize(scored)
    distribution_path, timeseries_path = plot_outputs(scored, args.output_dir)

    scored_path = args.output_dir / "cockpit_skew_scored.csv"
    summary_path = args.output_dir / "cockpit_skew_summary.csv"
    scored.to_csv(scored_path, index=False)
    summary.to_csv(summary_path, index=False)

    print("Wrote:")
    print(f"- {distribution_path}")
    print(f"- {timeseries_path}")
    print(f"- {scored_path}")
    print(f"- {summary_path}")
    print()
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
