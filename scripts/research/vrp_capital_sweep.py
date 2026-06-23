"""Two-layer macro short-vol on ONE shared $50k account — capital-utilisation sweep.

Strategy:
  BASE    = the deployed winner (reports/vrp_macro_signal.WINNER): bull put spread,
            0.25Δ / 0.125Δ wing, ~30 trading-day hold, weekly entry, ramp+ vrp-z
            sizing, held to expiry. SPX 20-yr monthly-ROR Sharpe ≈ 1.65.
  OVERLAY = binary: when vrp_z >= rich_threshold, sell `overlay_mult` extra sets of
            the same spread.
Account: $50,000 shared across SPY/QQQ/IWM; integer contracts floored to a risk-% of
$50k; a rung opens only if its margin fits the remaining buying power (else skipped,
logged). Idle cash earns rf (4%) → reported P&L is excess; gross = excess + rf.

Pricing/loaders are REUSED unchanged (flat-vol BS; VIX/VXN/RVX + equity lake). Flat-vol
ignores skew → the put-spread credit is a conservative floor (real fills ≥ modeled).

Persists the FULL result set to docs/research/vrp/_iterations/capital-sweep-results.csv (every config
× every metric). Deterministic — no RNG.

Run (MacBook local, reads option_wizard_local + the lake):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_capital_sweep.py
"""

from __future__ import annotations

import csv
import pathlib
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import WINNER, backtest_laddered
from uw_scan.storage.repository import Repository

NAMES = ("SPY", "QQQ", "IWM")
# VXN (2009-09-14) / RVX (2009-09-16) gate the QQQ/IWM sleeves; with the 252-day
# vrp-z warmup the first QQQ/IWM rung is ~Sep 2010. SPY (VIX, from 2006) trades
# earlier. min_date filters entries; the true span is read from the result.
COMMON_START = date(2009, 1, 1)
CAPITAL = 50_000.0

SWEEP_BASE_RISK_PCT = (0.03, 0.05, 0.08, 0.10)
SWEEP_OVERLAY_MULT = (1.0, 2.0)
SWEEP_RICH_THRESHOLD = (0.5, 1.0, 1.5)

OUT_CSV = pathlib.Path("docs/research/vrp/_iterations/capital-sweep-results.csv")

_FIELDS = [
    "base_risk_pct",
    "overlay_mult",
    "rich_threshold",
    "overlay_enabled",
    "n_rungs",
    "n_skipped_rungs",
    "skip_rate",
    "contracts_desired_total",
    "contracts_filled_total",
    "fill_rate",
    "total_return_excess",
    "years",
    "ann_return_excess",
    "ann_return_gross",
    "cagr_excess",
    "cagr_gross",
    "sharpe",
    "maxdd_dollars",
    "maxdd_pct",
    "util_mean",
    "util_peak",
    "win_rate",
    "breach_rate",
]


def _row(capcfg: CapitalConfig, overlay_enabled: bool, m: dict) -> dict:
    return {
        "base_risk_pct": capcfg.base_risk_pct,
        "overlay_mult": capcfg.overlay_mult if overlay_enabled else 0.0,
        "rich_threshold": capcfg.rich_threshold,
        "overlay_enabled": int(overlay_enabled),
        **{k: m[k] for k in _FIELDS if k in m},
    }


def main() -> None:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    rf = settings.vrp_risk_free_rate
    try:
        loadeds = {nm: load_index_vol(repo, nm) for nm in NAMES}

        # reconciliation: SPX TRULY-uncapped base-only ledger Sharpe vs backtest_laddered
        # (capital=1e9, base_risk_pct=0.05 → ~30% peak, no skips; huge N → floor noise ≪ 0.15)
        spx = load_index_vol(repo, "SPX")
        eng = backtest_laddered(spx, settings, WINNER, min_date=COMMON_START)
        recon_cfg = CapitalConfig(
            capital=1_000_000_000.0,
            base_risk_pct=0.05,
            overlay_mult=0.0,
            rich_threshold=99.0,
            names=("SPX",),
            min_date=COMMON_START,
        )
        recon = account_metrics(
            simulate_account({"SPX": spx}, settings, recon_cfg), recon_cfg, rf
        )
        print(
            f"RECONCILE SPX base-only uncapped: ledger Sharpe {recon['sharpe']:.3f} "
            f"vs backtest_laddered {eng['sharpe']:.3f} (Δ {abs(recon['sharpe'] - eng['sharpe']):.3f}); "
            f"skipped={recon['n_skipped_rungs']} util_peak={recon['util_peak']:.3f}\n"
        )

        rows: list[dict] = []
        # base-only baselines (one per base_risk_pct; overlay disabled)
        for brp in SWEEP_BASE_RISK_PCT:
            cfg = CapitalConfig(
                capital=CAPITAL,
                base_risk_pct=brp,
                overlay_mult=0.0,
                rich_threshold=99.0,
                names=NAMES,
                min_date=COMMON_START,
            )
            m = account_metrics(simulate_account(loadeds, settings, cfg), cfg, rf)
            rows.append(_row(cfg, overlay_enabled=False, m=m))

        # base + overlay grid
        for brp in SWEEP_BASE_RISK_PCT:
            for omult in SWEEP_OVERLAY_MULT:
                for rt in SWEEP_RICH_THRESHOLD:
                    cfg = CapitalConfig(
                        capital=CAPITAL,
                        base_risk_pct=brp,
                        overlay_mult=omult,
                        rich_threshold=rt,
                        names=NAMES,
                        min_date=COMMON_START,
                    )
                    m = account_metrics(
                        simulate_account(loadeds, settings, cfg), cfg, rf
                    )
                    rows.append(_row(cfg, overlay_enabled=True, m=m))

        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with OUT_CSV.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows → {OUT_CSV}\n")

        # headline frontier: top 8 base+overlay by ann_return_gross
        bo = sorted(
            [r for r in rows if r["overlay_enabled"]],
            key=lambda r: -r["ann_return_gross"],
        )[:8]
        print(
            f"{'brp':>5}{'omlt':>6}{'rich':>6}{'annGross':>10}{'sharpe':>8}"
            f"{'maxDD%':>8}{'util_avg':>9}{'util_pk':>8}{'skip%':>7}"
        )
        for r in bo:
            print(
                f"{r['base_risk_pct']:>5.2f}{r['overlay_mult']:>6.1f}{r['rich_threshold']:>6.1f}"
                f"{r['ann_return_gross']:>10.3f}{r['sharpe']:>8.2f}{r['maxdd_pct']:>8.3f}"
                f"{r['util_mean']:>9.3f}{r['util_peak']:>8.3f}{r['skip_rate']:>7.2f}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
