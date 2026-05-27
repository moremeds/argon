"""Build the 7-crisis fixture for VCG v2 integration tests.

Uses the current long-form schema:
  - uw_scan.vol_index_daily(symbol, trade_date, close, adj_close, ...)
  - uw_scan.macro_series_daily(series_id, obs_date, value, as_of, ...)

The output is not only crisis-window rows. VCG v2 uses rolling state, so the
fixture preserves contiguous warmup context from earliest crisis start minus
500 calendar days through the latest crisis end.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import yaml

from uw_scan.cards.regime_classification_labels import derive_level1_frame
from uw_scan.config import Settings

log = logging.getLogger(__name__)

FIXTURE_DIR = Path("tests/integration/regime/fixtures")
THRESHOLDS_YAML = Path("docs/research/regime/ground-truth-labels/level1-thresholds.yaml")
NAMED_CRISES_YAML = Path("docs/research/regime/ground-truth-labels/named-crises.yaml")
WARMUP_DAYS = 500

EXPECTED_PER_WINDOW_TRUTH_STRESS = {
    "GFC-Lehman": 105,
    "Eurozone-sovereign": 113,
    "China-devaluation-2015": 39,
    "Q4-2018-vol-regime": 50,
    "COVID-2020": 24,
    "2022-rates-bear": 189,
    "2023-SVB-week": 8,
}
EXPECTED_TOTAL_TRUTH_STRESS = sum(EXPECTED_PER_WINDOW_TRUTH_STRESS.values())
TRUTH_STRESS_LABELS = {"EDR", "RISK_OFF", "PANIC"}


def _load_crisis_windows() -> list[dict]:
    data = yaml.safe_load(NAMED_CRISES_YAML.read_text())
    return data["crises"]


def _crisis_name(ts: pd.Timestamp, windows: list[dict]) -> str | None:
    d = ts.date()
    for window in windows:
        start = date.fromisoformat(window["start_date"])
        end = date.fromisoformat(window["end_date"])
        if start <= d <= end:
            return str(window["name"])
    return None


def _assert_fixture_quality(
    df: pd.DataFrame,
    truth_df: pd.DataFrame,
    windows: list[dict],
) -> None:
    required = ["vix", "vvix", "hyg", "spx_close"]
    for col in required:
        if col not in df.columns:
            raise RuntimeError(f"fixture missing required column: {col}")

    in_crisis = df[df["crisis_window"].notna()]
    null_counts = in_crisis[required].isna().sum()
    if null_counts.any():
        raise RuntimeError(
            "fixture has nulls in crisis windows on required columns: "
            f"{null_counts[null_counts > 0].to_dict()}"
        )

    for window, group in in_crisis.groupby("crisis_window"):
        in_window_dates = group["trade_date"].sort_values().reset_index(drop=True)
        diffs = in_window_dates.diff().dt.days.dropna()
        max_gap = int(diffs.max()) if not diffs.empty else 0
        if max_gap > 7:
            raise RuntimeError(
                f"fixture has a gap of {max_gap} days inside crisis window {window!r}"
            )

    present_windows = set(in_crisis["crisis_window"].unique())
    expected_windows = {w["name"] for w in windows}
    missing_windows = expected_windows - present_windows
    if missing_windows:
        raise RuntimeError(f"fixture is missing crisis windows: {sorted(missing_windows)}")

    truth_stress = truth_df[truth_df["truth_status"].isin(TRUTH_STRESS_LABELS)]
    n_truth_stress = len(truth_stress)
    if n_truth_stress != EXPECTED_TOTAL_TRUTH_STRESS:
        raise RuntimeError(
            f"fixture has {n_truth_stress} truth-stress days; expected "
            f"{EXPECTED_TOTAL_TRUTH_STRESS}. Per-window breakdown: "
            f"{truth_stress.groupby('crisis_window').size().to_dict()}"
        )

    actual_per_window = truth_stress.groupby("crisis_window").size().to_dict()
    for window, expected_count in EXPECTED_PER_WINDOW_TRUTH_STRESS.items():
        actual = int(actual_per_window.get(window, 0))
        if actual != expected_count:
            raise RuntimeError(
                f"crisis window {window!r}: fixture has {actual} truth-stress "
                f"days; expected {expected_count}"
            )

    log.info(
        "fixture quality verified: %d rows total, %d truth-stress days across %d windows",
        len(df),
        n_truth_stress,
        len(present_windows),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    windows = _load_crisis_windows()
    thresholds = yaml.safe_load(THRESHOLDS_YAML.read_text())
    truth_eval_start = date.fromisoformat(thresholds["eval_start"])
    crisis_start = min(date.fromisoformat(w["start_date"]) for w in windows)
    eval_end = max(date.fromisoformat(w["end_date"]) for w in windows)
    fixture_data_start = crisis_start - timedelta(days=WARMUP_DAYS)
    data_start = min(truth_eval_start - timedelta(days=400), fixture_data_start)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT trade_date, symbol, close, adj_close
              FROM uw_scan.vol_index_daily
             WHERE symbol IN ('VIX', 'VVIX', 'SPX', 'HYG')
               AND trade_date BETWEEN %s AND %s
             ORDER BY trade_date, symbol
            """,
            (data_start, eval_end),
        )
        raw = pd.DataFrame(
            cur.fetchall(), columns=["trade_date", "symbol", "close", "adj_close"]
        )
        raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.normalize()
        raw["price"] = raw.apply(
            lambda r: r["adj_close"]
            if r["symbol"] == "HYG" and pd.notna(r["adj_close"])
            else r["close"],
            axis=1,
        )
        raw_pivot = raw.pivot(index="trade_date", columns="symbol", values="price").sort_index()
        truth_pivot = raw_pivot[["VIX", "VVIX", "SPX"]].ffill().rename(
            columns={"VIX": "vix", "VVIX": "vvix", "SPX": "spx_close"}
        )
        # Use the VCG-observable trading calendar for the fixture rows. Truth
        # percentiles are computed on the broader vol/SPX calendar first, then
        # aligned down to these dates; this matches the persisted audit run.
        trading_mask = (
            raw_pivot[["VIX", "SPX", "HYG"]].notna().all(axis=1)
            & (raw_pivot.index >= pd.Timestamp(fixture_data_start))
            & (raw_pivot.index <= pd.Timestamp(eval_end))
        )
        pivot = (
            raw_pivot.ffill()
            .loc[trading_mask]
            .rename(
                columns={
                    "VIX": "vix",
                    "VVIX": "vvix",
                    "HYG": "hyg",
                    "SPX": "spx_close",
                }
            )
        )
        df = pivot[["vix", "vvix", "hyg", "spx_close"]].reset_index()
        df["crisis_window"] = df["trade_date"].apply(lambda d: _crisis_name(d, windows))
        log.info("vol_complex contiguous slice: %d rows", len(df))

        cur.execute(
            """
            SELECT DISTINCT ON (series_id, obs_date) obs_date, series_id, value
              FROM uw_scan.macro_series_daily
             WHERE series_id IN ('NFCI', 'ANFCI', 'USREC')
               AND obs_date >= %s
             ORDER BY series_id, obs_date, as_of DESC
            """,
            (data_start,),
        )
        macro = pd.DataFrame(cur.fetchall(), columns=["obs_date", "series_id", "value"])
        macro["obs_date"] = pd.to_datetime(macro["obs_date"]).dt.normalize()
        macro_pivot = macro.pivot(index="obs_date", columns="series_id", values="value")
        macro_pivot = macro_pivot.sort_index().ffill()
        nfci = macro_pivot.reindex(truth_pivot.index, method="ffill")["NFCI"].astype(float)

        truth = derive_level1_frame(
            vix=truth_pivot["vix"].astype(float),
            vvix=truth_pivot["vvix"].astype(float),
            spx=truth_pivot["spx_close"].astype(float),
            credit_stress=nfci,
            thresholds=thresholds,
        )
        truth = truth.loc[truth.index.intersection(pivot.index)]
        truth_df = pd.DataFrame(
            {
                "trade_date": truth.index,
                "truth_status": truth["truth_label"].astype("string"),
            }
        )
        truth_df["crisis_window"] = truth_df["trade_date"].apply(
            lambda d: _crisis_name(d, windows)
        )
        truth_df = truth_df[truth_df["crisis_window"].notna()]
        log.info("truth labels inside crisis windows: %d rows", len(truth_df))

        _assert_fixture_quality(df, truth_df, windows)

        vol_out = FIXTURE_DIR / "seven_crisis_vol_complex.parquet"
        truth_out = FIXTURE_DIR / "seven_crisis_truth_labels.parquet"
        df.to_parquet(vol_out, index=False)
        truth_df.to_parquet(truth_out, index=False)
        log.info("wrote %s", vol_out)
        log.info("wrote %s", truth_out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
