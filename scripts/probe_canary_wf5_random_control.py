"""WF-5 random-control probe: does BTD beat 43 random within-window days?

Follow-on to scripts/probe_canary_wf5_fwd_return.py. The prior probe
established that in WF-5 the BTD bucket's forward 60d return is +11.4%
vs +4.0% NONE baseline (Welch's t=+17.16). Open caveat: monotonic
positive lift across horizons suggests possible selection-on-dip
effect — maybe ANY 43 days within WF-5 would show ~similar lift if
they happened to fall in the post-March-2023 SPX rally.

This probe resolves the caveat via bootstrap percentile test:
  - For each (window, bucket-of-interest, horizon), build a null
    distribution by drawing K=10000 random samples of n=43 days
    WITHOUT replacement from the pool of non-{bucket} days within
    that window, computing each sample's mean forward log-return.
  - Compare the OBSERVED bucket mean against the null distribution.
  - Report observed, null mean ± std, percentile of observed in
    null, two-tailed p-value approximation.

Decision rule (locks direction B if BTD survives):
  - BTD observed >= 99th percentile of null (p <= 0.02) in WF-5
    → BTD signal beats random within-window selection → direction
    B's evidence base survives, can lock.
  - 50th <= pctile < 99th → ambiguous; need stricter control
    (matched on prior 20d return, or alternative bucketing).
  - < 50th → BTD signal collapses; reconsider direction call.

Statistical details:
  - K=10000 bootstrap samples, fixed seed (42) for reproducibility.
  - Sampling WITHOUT replacement (BTD picked 43 distinct days; with-
    replacement would inflate null variance and make BTD look more
    significant than warranted).
  - Pool = window-wide non-{bucket} days. So BTD's null excludes
    BTD days; CCA's null excludes CCA days.
  - Per-horizon independent filtering for forward-return availability
    (drops rows where forward close is past the SPX series tail).

Usage:
  PGUSER=chenxi UW_SCAN_API_KEY=local-smoke uv run python \\
      scripts/probe_canary_wf5_random_control.py

Output: stdout (human-readable + TSV). Not persisted to DB.

Spec context:  docs/research/regime/canary-v2c-design-notes.md §1
Prior probes:  scripts/probe_canary_wf5.py (warning_state inventory)
               scripts/probe_canary_wf5_fwd_return.py (BTD vs NONE Welch's t)
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from datetime import date

import psycopg

from uw_scan.config import Settings

WINDOWS: dict[str, tuple[str, str, str]] = {
    "WF-1": ("2015-01-01", "2016-12-31", "China deval, Brexit"),
    "WF-3": ("2019-01-01", "2020-09-30", "Repo crisis, COVID crash"),
    "WF-5": ("2023-01-01", "2024-12-31", "Bond-yield selloff, 2024 quiet"),
}

HORIZONS_TD = (20, 60, 120)

# Buckets to test against random-control null. WF-1 and WF-5 only have BTD
# as a non-NONE bucket; WF-3 has both CCA and BTD. The probe runs every
# bucket present in each window.
BUCKETS_OF_INTEREST = ("BUY_THE_DIP_ACTIVE", "CONFIRMED_CANARY_ACTIVE")

K_BOOTSTRAP = 10_000
SEED = 42


def _fetch_v1_window_daily(conn, *, schema: str, window_id: str) -> list[dict]:
    """Pull v1 walk-forward daily rows for one window_id.

    Reads payload.warning_state (top-level string). Same query shape as
    probe_canary_wf5_fwd_return.py.
    """
    sql = f"""
        SELECT d.trade_date, d.payload
        FROM {schema}.regime_backtest_daily d
        JOIN {schema}.regime_backtest_runs r ON d.run_id = r.id
        WHERE r.indicator = 'canary'
          AND r.run_scope = 'production'
          AND r.composite_version = '1'
          AND r.params->>'phase' = 'walk_forward'
          AND r.params->>'window_id' = %s
          AND r.completed_at IS NOT NULL
        ORDER BY d.trade_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (window_id,))
        rows = []
        for trade_date, payload in cur.fetchall():
            warning_state = payload.get("warning_state") or "UNKNOWN"
            rows.append({"date": trade_date, "warning_state": warning_state})
        return rows


def _fetch_spx_close_series(
    conn, *, schema: str, start: date, end: date
) -> tuple[dict[date, int], list[float]]:
    """Pull SPX close series from vol_index_daily for [start, end].

    Returns (date_to_idx, closes_asc).
    """
    sql = f"""
        SELECT trade_date, close
        FROM {schema}.vol_index_daily
        WHERE symbol = 'SPX'
          AND trade_date BETWEEN %s AND %s
        ORDER BY trade_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start, end))
        rows = cur.fetchall()
    dates_asc = [r[0] for r in rows]
    closes_asc = [float(r[1]) for r in rows]
    date_to_idx = {d: i for i, d in enumerate(dates_asc)}
    return date_to_idx, closes_asc


def _forward_log_return(
    *,
    date_to_idx: dict[date, int],
    closes: list[float],
    spot_date: date,
    horizon_td: int,
) -> float | None:
    i = date_to_idx.get(spot_date)
    if i is None:
        return None
    j = i + horizon_td
    if j >= len(closes):
        return None
    spot, fwd = closes[i], closes[j]
    if spot <= 0 or fwd <= 0:
        return None
    return math.log(fwd / spot)


def _compute_returns_by_state(
    *,
    rows: list[dict],
    date_to_idx: dict[date, int],
    closes: list[float],
) -> dict[str, dict[int, list[float]]]:
    """Build {warning_state: {horizon: [returns]}} for one window."""
    buckets: dict[str, dict[int, list[float]]] = {}
    for r in rows:
        state = r["warning_state"]
        state_buckets = buckets.setdefault(state, {h: [] for h in HORIZONS_TD})
        for h in HORIZONS_TD:
            fr = _forward_log_return(
                date_to_idx=date_to_idx,
                closes=closes,
                spot_date=r["date"],
                horizon_td=h,
            )
            if fr is not None:
                state_buckets[h].append(fr)
    return buckets


def _bootstrap_null(
    *,
    pool_returns: list[float],
    n: int,
    k: int,
    rng: random.Random,
) -> list[float]:
    """Draw k samples of size n WITHOUT replacement from pool_returns;
    return each sample's mean."""
    if len(pool_returns) < n:
        return []
    means: list[float] = []
    for _ in range(k):
        sample = rng.sample(pool_returns, n)
        means.append(statistics.mean(sample))
    return means


def _percentile_of(obs: float, null_dist: list[float]) -> float:
    """Fraction (0-100) of null distribution at or below obs."""
    if not null_dist:
        return float("nan")
    below_or_eq = sum(1 for x in null_dist if x <= obs)
    return 100.0 * below_or_eq / len(null_dist)


def _two_tailed_p(pctile: float) -> float:
    """Approximate two-tailed p-value from percentile.

    pctile=99.5 → p=0.01;  pctile=50 → p=1.0;  pctile=0.5 → p=0.01.
    """
    return min(pctile, 100.0 - pctile) * 2.0 / 100.0


def _print_window_section(
    *,
    window_id: str,
    label: str,
    buckets: dict[str, dict[int, list[float]]],
    rng: random.Random,
) -> list[dict]:
    """Per-window section + TSV-summary rows. Returns rows for global TSV."""
    print(f"\n=== {window_id} — {label} ===")
    summary_rows: list[dict] = []
    for bucket_name in BUCKETS_OF_INTEREST:
        bucket = buckets.get(bucket_name)
        if not bucket:
            continue
        print(f"\n  Bucket: {bucket_name}")
        for h in HORIZONS_TD:
            obs_returns = bucket.get(h, [])
            if len(obs_returns) < 2:
                print(f"    {h}td: n={len(obs_returns)} — skipped")
                continue
            obs_mean = statistics.mean(obs_returns)
            n_obs = len(obs_returns)

            pool: list[float] = []
            for other_name, other in buckets.items():
                if other_name == bucket_name:
                    continue
                pool.extend(other.get(h, []))

            if len(pool) < n_obs:
                print(f"    {h}td: pool ({len(pool)}) < n_obs ({n_obs}) — skipped")
                continue

            null = _bootstrap_null(pool_returns=pool, n=n_obs, k=K_BOOTSTRAP, rng=rng)
            null_mean = statistics.mean(null)
            null_std = statistics.stdev(null) if len(null) > 1 else 0.0
            pct = _percentile_of(obs_mean, null)
            p = _two_tailed_p(pct)

            verdict = (
                "BEATS NULL"
                if pct >= 99.0
                else "INSIDE NULL"
                if pct >= 50.0
                else "WORSE THAN NULL"
            )

            print(
                f"    {h:>3}td:  obs={obs_mean:+.4f} (n={n_obs})  "
                f"null={null_mean:+.4f} ± {null_std:.4f}  "
                f"pctile={pct:.2f}  p≈{p:.4f}  {verdict}"
            )
            summary_rows.append(
                {
                    "window": window_id,
                    "bucket": bucket_name,
                    "horizon": h,
                    "n_obs": n_obs,
                    "obs_mean": obs_mean,
                    "null_mean": null_mean,
                    "null_std": null_std,
                    "pctile": pct,
                    "p": p,
                    "verdict": verdict,
                }
            )
    return summary_rows


def _print_tsv(summary_rows: list[dict]) -> None:
    print(
        "\n=== TSV (window\tbucket\thorizon\tn_obs\tobs\tnull_mean\tnull_std\tpctile\tp\tverdict) ==="
    )
    for r in summary_rows:
        print(
            f"{r['window']}\t{r['bucket']}\t{r['horizon']}td\t{r['n_obs']}\t"
            f"{r['obs_mean']:+.4f}\t{r['null_mean']:+.4f}\t{r['null_std']:.4f}\t"
            f"{r['pctile']:.2f}\t{r['p']:.4f}\t{r['verdict']}"
        )


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()

    rng = random.Random(SEED)
    print(f"[seed={SEED}  K_bootstrap={K_BOOTSTRAP}]")

    settings = Settings.from_env()
    win_start = min(date.fromisoformat(s) for s, _, _ in WINDOWS.values())
    win_end = max(date.fromisoformat(e) for _, e, _ in WINDOWS.values())
    spx_start = date(win_start.year - 1, 1, 1)
    spx_end = date(win_end.year + 1, 12, 31)

    all_rows: list[dict] = []
    with psycopg.connect(settings.db_dsn()) as conn:
        date_to_idx, closes = _fetch_spx_close_series(
            conn, schema=settings.db_schema, start=spx_start, end=spx_end
        )
        if not closes:
            print(
                f"ERROR: no SPX rows in vol_index_daily for {spx_start}..{spx_end}",
                file=sys.stderr,
            )
            return 1

        for wid, (start, end, label) in WINDOWS.items():
            rows = _fetch_v1_window_daily(
                conn, schema=settings.db_schema, window_id=wid
            )
            if not rows:
                print(f"WARN: {wid} no v1 walk-forward rows.", file=sys.stderr)
                continue
            buckets = _compute_returns_by_state(
                rows=rows, date_to_idx=date_to_idx, closes=closes
            )
            section_rows = _print_window_section(
                window_id=wid,
                label=f"{label} ({start} → {end})",
                buckets=buckets,
                rng=rng,
            )
            all_rows.extend(section_rows)

    if not all_rows:
        print("ERROR: no buckets tested.", file=sys.stderr)
        return 1

    _print_tsv(all_rows)

    print("\n=== Decision summary ===")
    btd_wf5_results = [
        r
        for r in all_rows
        if r["window"] == "WF-5" and r["bucket"] == "BUY_THE_DIP_ACTIVE"
    ]
    if btd_wf5_results:
        beats = [r for r in btd_wf5_results if r["pctile"] >= 99.0]
        if len(beats) == len(btd_wf5_results):
            print("- WF-5 BTD survives random-control at ALL horizons (p<=0.02).")
            print("  → Direction B's evidence base SURVIVES. Can lock direction B.")
        elif beats:
            print(
                f"- WF-5 BTD beats random-control at {len(beats)}/{len(btd_wf5_results)} horizons."
            )
            print("  → Mixed evidence; eyeball the failing horizons before locking.")
        else:
            print("- WF-5 BTD does NOT beat random-control at any horizon.")
            print("  → Direction B's evidence base COLLAPSES. Reconsider direction.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
