"""VRP backtest ITERATION 4 — robustness experiments on the SPX macro short-vol WINNER.

Experiments (each vs two baselines: iteration-3 SPX base case + SPY buy-and-hold):
  0 min viable starting capital   -> iter4-min-capital.csv
  1 extra position (overlay vs staggered tranche, comp + non-comp; floor C0) -> iter4-extra-position.csv
  2 entry weekday (uncapped + floor C0)  -> iter4-weekday.csv
  3 bear-market start (summary + full equity path) -> iter4-bear-start.csv + iter4-bear-start-path.csv
  4 Monte-Carlo (jitter/bootstrap/random-start/random-start-bear/config; UNCAPPED basis)
        -> iter4-mc.csv (summary) + iter4-mc-trials.csv (every trial — full trace)

SPX-only; SPY is the buy-and-hold benchmark. Deterministic given SEED below (set
VRP_MC_TRIALS=50 for a fast pass). Reuses pricing/loaders unchanged. Persists every
config × every metric; DictWriter uses extrasaction='raise' so nothing is silently dropped.

Run (MacBook local — option_wizard_local + the lake):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_robustness_run.py

Run (against the mini for most-recent data + pre-2009 history — source creds from .env.local first):
  set -a; source .env.local; set +a; UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_robustness_run.py
"""

from __future__ import annotations

import csv
import dataclasses
import math
import os
import pathlib
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    _contiguous_monthly,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_robustness import (
    bear_start_study,
    buy_and_hold,
    equity_curve_metrics,
    mc_block_bootstrap,
    mc_config_perturb,
    mc_entry_jitter,
    mc_random_start,
    min_viable_capital,
    monthly_equity,
    weekday_sweep,
)
from uw_scan.storage.repository import Repository

OUT = pathlib.Path("docs/research/vrp/")
SEED = 20260623
BEAR_STARTS = (date(2015, 8, 1), date(2018, 9, 20), date(2020, 2, 19), date(2022, 1, 3))
FLOOR_RISK_PCT = 0.20  # one SPX spread ~ this fraction of the floor account
UNCAPPED_CAPITAL = (
    1_000_000_000.0  # clean-signal basis: no skips, Sharpe ~ backtest_laddered
)
N_TRIALS = int(os.environ.get("VRP_MC_TRIALS", "200"))  # MC trials/driver (env-tunable)
# full metric surface persisted for the deterministic experiments — superset of all three
# metric sources (account_metrics *_excess, geometric plain, buy-and-hold). extrasaction='raise'
# then guarantees no metric key is ever silently dropped (persist-every-trace).
WIDE_FIELDS = [
    "variant",
    "basis",
    "sharpe",
    "ann_return",
    "ann_return_excess",
    "ann_return_gross",
    "cagr",
    "cagr_excess",
    "cagr_gross",
    "maxdd_pct",
    "maxdd_dollars",
    "util_mean",
    "util_peak",
    "skip_rate",
    "fill_rate",
    "win_rate",
    "breach_rate",
    "n_rungs",
    "n_skipped_rungs",
    "contracts_desired_total",
    "contracts_filled_total",
    "total_return_excess",
    "years",
]


def _write(name: str, fields: list[str], rows: list[dict]) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        # extrasaction='raise': a row with a key absent from `fields` is a bug, not something
        # to silently drop (persist-every-trace). Missing keys are written as "".
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {path}")


def _metrics(res, cfg, rf, *, compounding: bool) -> dict:
    """Full metric dict for one book. Non-comp → account_metrics (linear, net÷initial cap).
    Comp → equity_curve_metrics (geometric on E_t/E_{t-1}-1) patched with the activity stats
    from account_metrics (util/skip/contracts — those are basis-independent)."""
    if compounding:
        m = dict(
            equity_curve_metrics(monthly_equity(res, cfg.capital), cfg.capital, rf)
        )
        am = account_metrics(res, cfg, rf)
        for k in (
            "util_mean",
            "util_peak",
            "skip_rate",
            "fill_rate",
            "win_rate",
            "breach_rate",
            "n_rungs",
            "n_skipped_rungs",
            "contracts_desired_total",
            "contracts_filled_total",
        ):
            m[k] = am[k]
        return m
    return dict(account_metrics(res, cfg, rf))


def main() -> None:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    rf = settings.vrp_risk_free_rate
    try:
        spx = load_index_vol(repo, "SPX")
        spy = load_index_vol(repo, "SPY")

        # --- 0: min viable capital -> pick the floor C0 (FAIL LOUD if untradeable) ---
        mv = min_viable_capital(spx, settings, hold=30)
        if mv["first_entry_date"] is None or FLOOR_RISK_PCT not in mv["c0_floor"]:
            raise RuntimeError(
                f"no tradeable SPX entry / no floor at {FLOOR_RISK_PCT:.0%} — is SPX+VIX "
                f"history loaded? got {mv}"
            )
        c0_start = mv["c0_floor"][
            FLOOR_RISK_PCT
        ]  # smallest to START (cheapest 2007 spread)
        # SPX spot — hence spread max-loss — rises ~15x over 2007-2026, so the start-floor
        # can't afford a recent spread and the book goes dormant. The real account size for a
        # multi-decade SPX book is the smallest that affords the LARGEST (recent) spread.
        c0 = math.ceil(mv["max_mlpc"] / FLOOR_RISK_PCT / 1000) * 1000
        print(
            f"min capital: first_mlpc=${mv['first_mlpc']:,.0f} (start floor ${c0_start:,.0f}) "
            f"max_mlpc=${mv['max_mlpc']:,.0f} -> trade-throughout account "
            f"${c0:,.0f} @ {FLOOR_RISK_PCT:.0%}"
        )
        _write(
            "iter4-min-capital.csv",
            [
                "risk_pct",
                "first_entry_date",
                "first_mlpc",
                "max_mlpc",
                "c0_floor_start",
                "c0_floor_throughout",
            ],
            [
                {
                    "risk_pct": k,
                    "first_entry_date": mv["first_entry_date"],
                    "first_mlpc": mv["first_mlpc"],
                    "max_mlpc": mv["max_mlpc"],
                    "c0_floor_start": v,  # smallest to start in 2007
                    "c0_floor_throughout": math.ceil(mv["max_mlpc"] / k / 1000) * 1000,
                }
                for k, v in mv["c0_floor"].items()
            ],
        )

        # two bases: floor C0 (real-account affordability) + uncapped (clean signal, no skips).
        floor_cfg = CapitalConfig(
            capital=c0,
            base_risk_pct=FLOOR_RISK_PCT,
            overlay_mult=0.0,
            rich_threshold=99.0,
            names=("SPX",),
        )
        unc_cfg = CapitalConfig(
            capital=UNCAPPED_CAPITAL,
            base_risk_pct=0.05,
            overlay_mult=0.0,
            rich_threshold=99.0,
            names=("SPX",),
        )
        base_res = simulate_account({"SPX": spx}, settings, floor_cfg)
        base_metrics = account_metrics(base_res, floor_cfg, rf)
        unc_res = simulate_account({"SPX": spx}, settings, unc_cfg)
        bh = buy_and_hold(
            spy.adj, c0, rf, min_date=base_res.span[0]
        )  # same window as the book
        bh_m = {
            k: v for k, v in bh.items() if k not in ("start", "end")
        }  # metrics only

        def _baseline_rows(extra: dict) -> list[dict]:
            # both baselines on EVERY experiment (global constraint)
            return [
                {"variant": "baseline_iter3_spx", **extra, **base_metrics},
                {"variant": "baseline_spy_buyhold", **extra, **bh_m},
            ]

        # --- 1: extra position (floor C0; base vs overlay vs staggered; comp + non-comp) ---
        print("exp1 extra-position ...")
        ep_rows: list[dict] = []
        for compounding in (False, True):
            for arm, mut in (
                ("base", {}),
                ("contract_overlay", {"overlay_mult": 1.0, "rich_threshold": 1.0}),
                ("staggered_tranche", {"extra_tranche": True, "rich_threshold": 1.0}),
            ):
                cfg = dataclasses.replace(floor_cfg, compounding=compounding, **mut)
                res = simulate_account({"SPX": spx}, settings, cfg)
                tag = "comp" if compounding else "noncomp"
                ep_rows.append(
                    {
                        "variant": f"{arm}_{tag}",
                        "basis": "floor",
                        **_metrics(res, cfg, rf, compounding=compounding),
                    }
                )
        ep_rows += _baseline_rows({"basis": "floor"})
        _write("iter4-extra-position.csv", WIDE_FIELDS, ep_rows)

        # --- 2: weekday (BOTH bases — uncapped clean signal + floor C0) ---
        print("exp2 weekday ...")
        wd_rows: list[dict] = []
        for basis, cfg0 in (("uncapped", unc_cfg), ("floor", floor_cfg)):
            for r in weekday_sweep(spx, settings, cfg0, rf):
                wd = r.pop("entry_weekday")
                wd_rows.append(
                    {"variant": f"weekday_{wd}_{basis}", "basis": basis, **r}
                )
        wd_rows += _baseline_rows({"basis": "floor"})
        _write("iter4-weekday.csv", WIDE_FIELDS, wd_rows)

        # --- 3: bear start (summary + full equity path; baselines on the summary) ---
        print("exp3 bear-start ...")
        bs_summary, bs_path = bear_start_study(
            spx, settings, floor_cfg, rf, starts=BEAR_STARTS
        )
        for r in bs_summary:
            r["variant"] = f"bear_{r['start']}"
        bs_fields = [
            "variant",
            "start",
            "n_rungs",
            "sharpe",
            "cagr",
            "maxdd_pct",
            "ret_6m",
            "maxdd_6m_pct",
            "ret_12m",
            "maxdd_12m_pct",
            "ret_36m",
            "maxdd_36m_pct",
        ]
        for b in _baseline_rows({}):  # pad to bs_fields; bridge cagr_excess→cagr
            pad = {k: b.get(k) for k in bs_fields}
            pad["cagr"] = b.get("cagr", b.get("cagr_excess"))
            bs_summary.append(pad)
        _write("iter4-bear-start.csv", bs_fields, bs_summary)
        _write(
            "iter4-bear-start-path.csv",
            ["start", "year", "month", "equity", "drawdown_pct"],
            bs_path,
        )

        # --- 4: Monte Carlo (UNCAPPED clean-signal basis; summary + per-trial full trace) ---
        print(f"exp4 monte-carlo ({N_TRIALS} trials/driver) ...")
        boot_src = _contiguous_monthly(
            unc_res.monthly_excess
        )  # zero-filled → centres on base
        bear_lo, bear_hi = date(2007, 1, 1), date(2009, 6, 30)  # GFC window for #5
        mc = {
            "entry_jitter": mc_entry_jitter(
                spx, settings, unc_cfg, rf, n_trials=N_TRIALS, seed=SEED
            ),
            "block_bootstrap": mc_block_bootstrap(
                boot_src, n_trials=max(N_TRIALS, 500), seed=SEED, rf=rf
            ),
            "random_start": mc_random_start(
                spx, settings, unc_cfg, rf, n_trials=N_TRIALS, seed=SEED
            ),
            "random_start_bear": mc_random_start(
                spx,
                settings,
                unc_cfg,
                rf,
                n_trials=N_TRIALS,
                seed=SEED,
                min_start=bear_lo,
                max_start=bear_hi,
                min_tail_months=12,
            ),
            "config_perturb": mc_config_perturb(
                spx, settings, unc_cfg, rf, n_trials=N_TRIALS, seed=SEED
            ),
        }
        sk = ("metric", "n_trials", "n_valid", "seed", "mean", "median", "p5", "p95")
        mc_summary = [{"test": k, **{kk: v[kk] for kk in sk}} for k, v in mc.items()]
        for name_, sharpe in (
            ("baseline_iter3_spx", base_metrics["sharpe"]),
            ("baseline_spy_buyhold", bh_m["sharpe"]),
        ):
            mc_summary.append(
                {
                    "test": name_,
                    "metric": "sharpe",
                    "n_trials": 1,
                    "n_valid": 1,
                    "seed": SEED,
                    "mean": sharpe,
                    "median": sharpe,
                    "p5": sharpe,
                    "p95": sharpe,
                }
            )
        _write("iter4-mc.csv", ["test", *sk], mc_summary)
        mc_trials = [{"test": k, **t} for k, v in mc.items() for t in v["trials"]]
        _write("iter4-mc-trials.csv", ["test", "trial", "value", "param"], mc_trials)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
