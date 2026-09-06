#!/usr/bin/env python
"""Arm-H counterfactual of the SPX 1-5d density cone, scored against run 3's arm-G record.

`scripts/research/spx_density_calibration.py` scored the cone argon actually published:
arm **G** (Normal innovations in the GJR likelihood, multi-start, §3.4 retry ladder),
persisted as `backtest_sweep_runs` id **3**, strategy `spx_density_calibration`. This
script asks the one counterfactual that costs nothing but CPU: would arm **H** — the
same arm with **Student-t** innovations in the likelihood, identical in every other
respect (`density/fit.ARMS`) — have been better calibrated over the same sessions?

Method, and the three things that make the comparison fair:

1. **Same inputs, same truncation.** Each as_of is replayed through
   `density.forecast.compute_forecast(bars, as_of=..., arm="H")` over the SAME
   `fetch_spx_series(PANEL_FIRST_DATE)` series the backfill script uses. The panel rail
   pins the index frame and `seed_for(i)` pins the seed, so arm H is drawn from the same
   Monte-Carlo stream arm G was — the two differ in the fitted parameters and nothing
   else. The recomputed `anchor_close` is asserted equal to the stored one; a mismatch
   means the series moved under us and the run refuses rather than scoring a different
   anchor's cone against arm G's outcome.
2. **Same outcomes and same baseline.** `realised_return` and the EWMA `baseline_q*`
   columns are READ from the existing `spx_density_forecast` rows, never recomputed.
   The arm-A baseline is analytic and seed-independent, so it is identical under either
   arm — reading it removes even the possibility of a float-path difference in the
   denominator of every pinball ratio.
3. **Same metric code.** `score_row` / `aggregate` / `build_groups` / `print_tables` are
   IMPORTED from `spx_density_calibration`, not reimplemented. Every metric definition,
   every Wilson interval, every PIT convention is byte-identical to run 3's.

Every caveat in `spx_density_calibration`'s module docstring binds here too — in
particular CAVEAT 1 (overlapping windows for h > 1, so the intervals are optimistic) and
CAVEAT 2 (only `origin='prospective'` rows are a live record; the reconstructed cells are
replay). And one more that is specific to this script:

CAVEAT 4 - ARM H IS SCORED ON THE SAME WINDOW ARM G WAS. This is a re-score of one fixed
    window, not an out-of-sample test of an arm-selection rule. Arm G was itself chosen by
    signal-lab's v13 run on an earlier window, so a win here is evidence about THIS window
    and a reason to run a proper selection study, never on its own a reason to switch the
    published arm.

Reproduce (the mini's prod DB is the only tier that carries the 83 as_of rows):
    eval "$(ssh macmini 'grep -E "^UW_SCAN_DB_(USER|PASSWORD|PORT)=" /opt/argon/.env')"
    env UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
        UW_SCAN_DB_USER="$UW_SCAN_DB_USER" UW_SCAN_DB_PASSWORD="$UW_SCAN_DB_PASSWORD" \\
        UW_SCAN_DB_PORT="$UW_SCAN_DB_PORT" UW_SCAN_DB_SCHEMA=uw_scan \\
        UW_SCAN_API_KEY=not-used \\
      uv run --frozen python scripts/research/spx_density_arm_h.py

Reads:  uw_scan.spx_density_forecast (settled rows only), uw_scan.vol_index_daily,
        uw_scan.backtest_sweep_{runs,results} (run 3, for the side-by-side)
Writes: uw_scan.backtest_sweep_runs / _results ONLY, strategy
        'spx-density-calibration-arm-H'. NEVER spx_density_forecast — the published log
        is arm G's by definition and this script has no business rewriting it.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import psycopg

from uw_scan.backtest import run_sweep
from uw_scan.config import Settings
from uw_scan.density.constants import PANEL_FIRST_DATE
from uw_scan.density.fit import ARMS
from uw_scan.density.forecast import compute_forecast
from uw_scan.storage.backtest_repository import BacktestRepository
from uw_scan.storage.spx_density_repository import SpxDensityRepository

# The metric math is run 3's, loaded wholesale from the baseline script. Reimplementing
# any of it would make the side-by-side a comparison of two scorers rather than of two
# arms. Loaded by path because scripts/ is not an importable package — the same loader
# tests/unit/scripts/test_spx_density_calibration.py uses.
_CAL_PATH = Path(__file__).resolve().parent / "spx_density_calibration.py"
_spec = importlib.util.spec_from_file_location("spx_density_calibration", _CAL_PATH)
cal = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cal
_spec.loader.exec_module(cal)

LEVELS = cal.LEVELS
SELECT_COLS = cal.SELECT_COLS
Scored = cal.Scored
aggregate = cal.aggregate
build_groups = cal.build_groups
print_tables = cal.print_tables
score_row = cal.score_row

log = logging.getLogger("spx_density_arm_h")

ARM = "H"
STRATEGY_PREFIX = "spx-density-calibration-arm-"


def strategy_for(arm: str, seed_offset: int) -> str:
    """'spx-density-calibration-arm-H'; '-seed1' suffix marks a noise-floor control."""
    return f"{STRATEGY_PREFIX}{arm}" + (f"-seed{seed_offset}" if seed_offset else "")


STRATEGY = strategy_for(ARM, 0)
BASELINE_STRATEGY = "spx_density_calibration"
BASELINE_RUN_ID = 3

REPRODUCE = (
    'eval "$(ssh macmini \'grep -E "^UW_SCAN_DB_(USER|PASSWORD|PORT)=" '
    "/opt/argon/.env')\" && "
    "env UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard "
    'UW_SCAN_DB_USER="$UW_SCAN_DB_USER" UW_SCAN_DB_PASSWORD="$UW_SCAN_DB_PASSWORD" '
    'UW_SCAN_DB_PORT="$UW_SCAN_DB_PORT" UW_SCAN_DB_SCHEMA=uw_scan '
    "UW_SCAN_API_KEY=not-used "
    "uv run --frozen python scripts/research/spx_density_arm_h.py"
)  # + --arm X --seed-offset N when off-default


QUANTILE_STEMS = tuple(stem for _, stem in LEVELS)


class MissingInputError(RuntimeError):
    """A required input is absent or disagrees. Never filled, never defaulted."""


# --------------------------------------------------------------------------------------
# load
# --------------------------------------------------------------------------------------


def load_published_rows(conn, schema: str) -> list[dict]:
    """Run 3's exact row set (settled + binned), plus `anchor_close` for the rail check.

    `SELECT_COLS` is imported so the column list cannot drift from the baseline's.
    """
    sql = f"""
        SELECT {SELECT_COLS}, anchor_close
          FROM {schema}.spx_density_forecast
         WHERE realised_return IS NOT NULL
           AND density_bins_jsonb IS NOT NULL
         ORDER BY as_of, h
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def load_baseline_metrics(
    conn, schema: str, run_id: int
) -> dict[tuple[str, str], dict]:
    """Run 3's per-cell metrics, keyed (origin, h) exactly as `build_groups` keys them."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT strategy, status FROM {schema}.backtest_sweep_runs WHERE id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise MissingInputError(f"baseline run id {run_id} does not exist")
    if row[0] != BASELINE_STRATEGY:
        raise MissingInputError(
            f"baseline run id {run_id} has strategy {row[0]!r}, "
            f"expected {BASELINE_STRATEGY!r} — refusing to compare against another study"
        )
    if row[1] != "completed":
        raise MissingInputError(f"baseline run id {run_id} status is {row[1]!r}")

    repo = BacktestRepository(conn, schema=schema)
    out: dict[tuple[str, str], dict] = {}
    for r in repo.fetch_run_results(run_id):
        if r["status"] != "ok" or r["metrics"] is None:
            continue
        cfg = r["config"]
        out[(str(cfg["origin"]), str(cfg["h"]))] = r["metrics"]
    if not out:
        raise MissingInputError(f"baseline run id {run_id} has no ok result rows")
    return out


# --------------------------------------------------------------------------------------
# arm-H replay
# --------------------------------------------------------------------------------------


def replay_arm(
    bars: Sequence[tuple[date, float]],
    as_ofs: Sequence[date],
    *,
    arm: str = ARM,
    seed_offset: int = 0,
) -> dict[tuple[date, int], dict]:
    """(as_of, h) -> {'anchor_close', 'q05'..'q95', 'density_bins_jsonb', 'fallback_used'}.

    Uses `compute_forecast`'s own as_of truncation — the same call the backfill script
    makes — so the seed is the v13 panel-index convention and the replay is bit-faithful
    to what THIS arm would have issued that night. Nothing here is caught and defaulted:
    a `PanelMismatchError` or `SeriesTooShortError` propagates and kills the run.
    """
    bar_dates = {d for d, _ in bars}
    out: dict[tuple[date, int], dict] = {}
    for n, as_of in enumerate(as_ofs, start=1):
        if as_of not in bar_dates:
            raise MissingInputError(
                f"as_of {as_of} has no SPX bar in vol_index_daily — truncation would "
                "silently anchor an earlier session"
            )
        result = compute_forecast(bars, as_of=as_of, arm=arm, seed_offset=seed_offset)
        if result.as_of != as_of:
            raise MissingInputError(f"replay anchored {result.as_of}, expected {as_of}")
        for row in result.rows:
            cell = {stem: row[stem] for stem in QUANTILE_STEMS}
            cell["anchor_close"] = result.anchor_close
            cell["density_bins_jsonb"] = row["density_bins_jsonb"]
            cell["fallback_used"] = result.fallback_used
            out[(as_of, int(row["h"]))] = cell
        log.info(
            "replayed %d/%d as_of=%s arm=%s seed=%d fallback=%s",
            n,
            len(as_ofs),
            as_of,
            arm,
            result.seed,
            result.fallback_used,
        )
    return out


def merge_rows(
    published: Sequence[Mapping],
    replayed: Mapping[tuple[date, int], dict],
) -> list[dict]:
    """One scoring row per published cell: arm-H quantiles + bins, published outcome and
    published EWMA baseline. Any missing or disagreeing piece raises."""
    merged: list[dict] = []
    for pub in published:
        key = (pub["as_of"], int(pub["h"]))
        cell = replayed.get(key)
        if cell is None:
            raise MissingInputError(f"arm replay produced no cell for {key}")
        if cell["density_bins_jsonb"] is None:
            raise MissingInputError(f"replayed cell {key} has no density bins")
        got, want = float(cell["anchor_close"]), float(pub["anchor_close"])
        if got != want:
            raise MissingInputError(
                f"anchor_close disagreement at {key}: replay {got} != published {want}"
            )
        row = {
            "as_of": pub["as_of"],
            "h": int(pub["h"]),
            "origin": pub["origin"],
            "realised_return": pub["realised_return"],
            "density_bins_jsonb": cell["density_bins_jsonb"],
        }
        for stem in QUANTILE_STEMS:
            row[stem] = cell[stem]
            b = pub[f"baseline_{stem}"]
            if b is None:
                raise MissingInputError(f"published baseline_{stem} is NULL at {key}")
            row[f"baseline_{stem}"] = b
        if row["realised_return"] is None:
            raise MissingInputError(f"published realised_return is NULL at {key}")
        merged.append(row)
    return merged


# --------------------------------------------------------------------------------------
# summary
# --------------------------------------------------------------------------------------

SUMMARY_KEYS: tuple[tuple[str, str, int], ...] = (
    ("pinball_ratio_q05", "q05 pinball ratio", 4),
    ("pinball_ratio_q90", "q90 pinball ratio", 4),
    ("pinball_ratio_q95", "q95 pinball ratio", 4),
    ("pinball_mean", "mean pinball (model)", 6),
    ("pinball_ratio_mean", "mean pinball ratio", 4),
)


def _num(v, places: int) -> str:
    return "-" if v is None else f"{float(v):.{places}f}"


def print_summary(
    results: Sequence[dict],
    baseline: Mapping[tuple[str, str], dict],
    *,
    baseline_run_id: int,
    arm: str = ARM,
) -> None:
    """The headline cells, the replayed arm next to run 3's arm G, pooled per origin."""
    by_key = {
        (str(r["config"]["origin"]), str(r["config"]["h"])): r["metrics"]
        for r in results
    }
    print()
    print(
        f"### Arm {arm} vs run {baseline_run_id} (arm G), pooled over h within origin"
    )
    print()
    print(f"| origin | n | metric | arm {arm} | run {baseline_run_id} (arm G) |")
    print("| --- | --- | --- | --- | --- |")
    for origin in ("reconstructed", "prospective"):
        key = (origin, "all")
        m, b = by_key.get(key), baseline.get(key)
        if m is None:
            log.warning("no arm-%s cell for %s — skipped in the summary", arm, key)
            continue
        if b is None:
            raise MissingInputError(
                f"run {baseline_run_id} has no {key} cell to compare against"
            )
        if int(m["n"]) != int(b["n"]):
            raise MissingInputError(
                f"{key}: arm {arm} scored {m['n']} rows, run {baseline_run_id} scored "
                f"{b['n']} — the two are not the same window"
            )
        for mkey, label, places in SUMMARY_KEYS:
            print(
                f"| {origin} | {m['n']} | {label} | {_num(m.get(mkey), places)} "
                f"| {_num(b.get(mkey), places)} |"
            )
        mh, bh = list(m["pit_deciles"]), list(b["pit_deciles"])
        print(
            f"| {origin} | {m['n']} | PIT deciles 1+2 (count) "
            f"| {mh[0] + mh[1]} ({mh[0]}+{mh[1]}) | {bh[0] + bh[1]} ({bh[0]}+{bh[1]}) |"
        )
    print()


def notes_for(arm: str, seed_offset: int) -> str:
    spec = ARMS[arm]
    control = (
        f" NOISE-FLOOR CONTROL: same arm as production, every cone seed is "
        f"seed_for(i)+{seed_offset}; any metric delta vs the baseline is Monte-Carlo "
        "noise, the yardstick for whether an arm's delta clears noise."
        if seed_offset
        else ""
    )
    return (
        f"Arm-{arm} counterfactual of the SPX 1-5d density cone. BASELINE: "
        f"backtest_sweep_runs id {BASELINE_RUN_ID}, strategy '{BASELINE_STRATEGY}' — the "
        "arm-G (Normal-innovation GJR) cone argon actually published, scored over the same "
        f"sessions. Arm {arm} is density/fit.ARMS['{arm}'] = {spec!r} (G is "
        f"{ARMS['G']!r}).{control} "
        "METHOD: every as_of is replayed through density.forecast.compute_forecast("
        f"bars, as_of=..., arm='{arm}', seed_offset={seed_offset}) over the same "
        "fetch_spx_series(PANEL_FIRST_DATE) series the backfill script uses, so the panel "
        "rail pins the index frame and seed_for(i) pins the Monte-Carlo seed. Each "
        "replayed anchor_close is asserted equal to the published one. realised_return "
        "and the EWMA baseline_q* columns are READ from the existing spx_density_forecast "
        "rows, never recomputed, so the outcome and the pinball-ratio denominator are "
        "byte-identical to the baseline's. Metric code (score_row, aggregate, "
        "build_groups) is imported from scripts/research/spx_density_calibration.py, not "
        "reimplemented. Result-row shape (config {origin, h}, metrics, n_trades) matches "
        f"run {BASELINE_RUN_ID} cell for cell. "
        "CAVEATS 1-3 of spx_density_calibration bind unchanged: overlapping target windows "
        "for h > 1 make the Wilson intervals and KS p-values optimistic; origin="
        "'reconstructed' is replay, only origin='prospective' is a live record; the PIT "
        "tails outside the (0.005, 0.995) histogram clip get the midpoint of an "
        "unresolvable interval. "
        f"CAVEAT 4 - arm {arm} is scored on the SAME window arm G was, so this is a "
        "re-score of one fixed window, not an out-of-sample test of an arm-selection rule. "
        "Arm G was itself selected by signal-lab's v13 run on an earlier window; a win here "
        "is a reason to run a proper selection study, never on its own a reason to switch "
        "the published arm. "
        "Reads spx_density_forecast (never writes it); writes backtest_sweep_* only."
    )


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="score and print, but persist nothing (no backtest_sweep_* rows).",
    )
    ap.add_argument(
        "--limit-as-of",
        type=int,
        default=None,
        help=(
            "Replay only the first N as_of sessions. --dry-run only: a partial window "
            "must never be persisted as if it were the study."
        ),
    )
    ap.add_argument("--baseline-run-id", type=int, default=BASELINE_RUN_ID)
    ap.add_argument("--arm", default=ARM, choices=sorted(ARMS))
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.limit_as_of is not None and not args.dry_run:
        raise SystemExit("--limit-as-of requires --dry-run")
    strategy = strategy_for(args.arm, args.seed_offset)

    settings = Settings.from_env()
    sha = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        or None
    )

    with psycopg.connect(settings.db_dsn()) as conn:
        published = load_published_rows(conn, settings.db_schema)
        if not published:
            raise SystemExit(
                "No settled spx_density_forecast rows with density bins — this DB tier "
                "does not carry the published cone log. Nothing to re-score."
            )
        baseline = load_baseline_metrics(conn, settings.db_schema, args.baseline_run_id)

        as_ofs = sorted({r["as_of"] for r in published})
        if args.limit_as_of is not None:
            as_ofs = as_ofs[: args.limit_as_of]
            published = [r for r in published if r["as_of"] in set(as_ofs)]
        log.info(
            "re-scoring %d published cells over %d as_of sessions %s..%s with arm %s",
            len(published),
            len(as_ofs),
            as_ofs[0],
            as_ofs[-1],
            args.arm,
        )

        sdr = SpxDensityRepository(conn, schema=settings.db_schema)
        bars = sdr.fetch_spx_series(PANEL_FIRST_DATE)
        if len(bars) < 2:
            raise SystemExit(
                "no SPX series in vol_index_daily — the replay has no input"
            )

        replayed = replay_arm(bars, as_ofs, arm=args.arm, seed_offset=args.seed_offset)
        merged = merge_rows(published, replayed)
        scored: list[Scored] = [score_row(r) for r in merged]
        n_fallback = sum(1 for c in replayed.values() if c["fallback_used"])
        log.info(
            "scored %d rows, origins=%s, labelled fallbacks=%d of %d cells",
            len(scored),
            sorted({r.origin for r in scored}),
            n_fallback,
            len(replayed),
        )

        groups = build_groups(scored)
        by_key = {(str(c["origin"]), str(c["h"])): rows for c, rows in groups}
        params_grid = {
            "arm": args.arm,
            "seed_offset": args.seed_offset,
            "baseline_arm": "G",
            "baseline_run_id": args.baseline_run_id,
            "baseline_strategy": BASELINE_STRATEGY,
            "quantile_levels": [tau for tau, _ in LEVELS],
            "pit_deciles": 10,
            "aggregations": ["origin_x_h", "h_pooled", "origin_pooled"],
        }

        if args.dry_run:
            log.info("--dry-run: computing metrics in process, persisting nothing")
            results = [
                {
                    "config": c,
                    "metrics": aggregate(rows),
                    "n_trades": len(rows),
                }
                for c, rows in groups
            ]
            run_id = None
        else:
            out = run_sweep(
                [c for c, _ in groups],
                lambda cfg: {
                    "metrics": aggregate(by_key[(str(cfg["origin"]), str(cfg["h"]))]),
                    "n_trades": len(by_key[(str(cfg["origin"]), str(cfg["h"]))]),
                },
                repo=BacktestRepository(conn, schema=settings.db_schema),
                strategy=strategy,
                reproduce_cmd=REPRODUCE
                + (f" --arm {args.arm}" if args.arm != ARM else "")
                + (f" --seed-offset {args.seed_offset}" if args.seed_offset else ""),
                params_grid=params_grid,
                git_sha=sha,
                data_start=min(r.as_of for r in scored),
                data_end=max(r.as_of for r in scored),
                notes=notes_for(args.arm, args.seed_offset),
            )
            results, run_id = out["results"], out["run_id"]
            log.info("run_id=%s ok=%s error=%s", run_id, out["n_ok"], out["n_error"])

    print_tables(results)
    if args.limit_as_of is None:
        print_summary(
            results, baseline, baseline_run_id=args.baseline_run_id, arm=args.arm
        )
    else:
        # print_summary refuses a cell whose n differs from the baseline's, and under
        # --limit-as-of every cell does. That guard is the point (a truncated window
        # next to run 3's full one would read as a comparison), so the plumbing knob
        # skips the side-by-side rather than loosening it.
        log.info(
            "--limit-as-of truncated the window to %d as_of sessions; the run-%d "
            "side-by-side is skipped (not comparable), tables above are arm-%s only",
            args.limit_as_of,
            args.baseline_run_id,
            args.arm,
        )
    if run_id is None:
        log.info("dry run complete — nothing persisted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
