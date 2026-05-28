"""WF-5 forward-return probe: does warning_state predict in quiet regimes?

Follow-on to scripts/probe_canary_wf5.py. The first probe established that
WF-5's speed fires (score >= 8) on 100% of days while WF-3 quiets 10%.
Open question: when warning_state fires in WF-5, is it predicting anything
about forward SPX returns, or is it noise that v1's additive formula
happens to absorb?

Payload shape (verified against WF-5 row 2023-01-03):
  - payload.speed         → integer score (0 / 8 / 20)
  - payload.warning_state → semantic bucket: NONE / CONFIRMED_CANARY_ACTIVE
                            / BUY_THE_DIP_ACTIVE
  (Note: probe_canary_wf5.py had a defensive `speed.state` reader that
  never fired — older nested shape doesn't exist in current payloads.)

What it does:
  1. For each window in {WF-1, WF-3, WF-5}, pulls v1 walk-forward daily
     rows from regime_backtest_daily.
  2. Pulls SPX close series from vol_index_daily (single shared series).
  3. For each row, looks up forward 20 / 60 / 120 trading-day SPX log-return.
  4. Buckets by warning_state, reports per-bucket count, mean, median,
     std, IQR, plus Welch's t for non-NONE vs NONE (no p-value).
  5. Side-by-sides the three windows.

Inventory (from production canary v1 walk-forward, verified 2026-05-28):
  WF-1  NONE=461  BTD=43                                (no CCA — quiet)
  WF-3  NONE=355  CCA=43  BTD=43                        (full crucible)
  WF-5  NONE=459  BTD=43                                (no CCA — quiet)

Interpretation guide (per canary-v2c-design-notes.md §1):
  - WF-5 has only NONE vs BTD — there is NO warning-firing bucket to test.
    What this DOES reveal: in a quiet regime, does BTD predict forward
    returns differently than baseline? (BTD is a dip-buy signal, so
    positive forward returns would just confirm v1's BTD logic.)
  - The deeper hypothesis ("speed is an early-instability detector in
    quiet regimes") CANNOT be tested directly here because WF-5's
    warning_state never escalates beyond BTD. This is itself a finding:
    if v2-A's WF-5 regression was caused by removing speed, the mechanism
    is NOT speed-as-warning — it's the integer score's drift contribution
    to the composite, independent of warning_state.
  - WF-3 is the discriminating crucible: 3-bucket breakout including CCA.
    If CCA non-NONE has a strongly negative forward-return signal in
    WF-3 but BTD has a positive one, the warning_state bucket carries
    real directional content during crisis.
  - WF-1 is a sanity baseline.

Usage:
  PGUSER=chenxi UW_SCAN_API_KEY=local-smoke uv run python \\
      scripts/probe_canary_wf5_fwd_return.py

Output: stdout (human-readable + TSV). Not persisted to DB.

Spec context: docs/research/regime/canary-v2c-design-notes.md §1
Prior probe:  scripts/probe_canary_wf5.py
"""

from __future__ import annotations

import argparse
import math
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


def _fetch_v1_window_daily(conn, *, schema: str, window_id: str) -> list[dict]:
    """Pull v1 walk-forward daily rows for one window_id.

    Reads payload.warning_state (top-level string field). The integer
    payload.speed is also extracted for cross-checking; see the inventory
    in this file's module docstring.
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
            speed_raw = payload.get("speed")
            speed = int(speed_raw) if isinstance(speed_raw, (int, float)) else None
            rows.append(
                {"date": trade_date, "warning_state": warning_state, "speed": speed}
            )
        return rows


def _fetch_spx_close_series(
    conn, *, schema: str, start: date, end: date
) -> tuple[list[date], dict[date, int], list[float]]:
    """Pull SPX close series from vol_index_daily for [start, end].

    Returns (dates_asc, date_to_idx, closes_asc) — the trading-day index
    lets us advance by trading days (not calendar days) for forward returns.
    Schema verified: vol_index_daily(symbol, trade_date, ..., close, ...).
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
    return dates_asc, date_to_idx, closes_asc


def _forward_log_return(
    *,
    date_to_idx: dict[date, int],
    closes: list[float],
    spot_date: date,
    horizon_td: int,
) -> float | None:
    """Look up the trading-day-indexed forward log-return, or None at the
    series tail."""
    i = date_to_idx.get(spot_date)
    if i is None:
        return None
    j = i + horizon_td
    if j >= len(closes):
        return None
    spot = closes[i]
    fwd = closes[j]
    if spot <= 0 or fwd <= 0:
        return None
    return math.log(fwd / spot)


def _welch_t_stat(a: list[float], b: list[float]) -> float | None:
    """Welch's t-statistic for mean(a) - mean(b). No p-value; user reads
    magnitude (|t| > 2 ≈ noteworthy, > 3 ≈ strong, given n's reported)."""
    if len(a) < 2 or len(b) < 2:
        return None
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)
    se = math.sqrt(var_a / len(a) + var_b / len(b))
    if se == 0:
        return None
    return (statistics.mean(a) - statistics.mean(b)) / se


def _bucket_stats(returns: list[float]) -> dict:
    """count / mean / median / std / IQR (Q3-Q1) for one bucket."""
    n = len(returns)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "std": None, "iqr": None}
    if n == 1:
        return {
            "n": 1,
            "mean": returns[0],
            "median": returns[0],
            "std": None,
            "iqr": None,
        }
    qs = statistics.quantiles(returns, n=4)
    return {
        "n": n,
        "mean": statistics.mean(returns),
        "median": statistics.median(returns),
        "std": statistics.stdev(returns),
        "iqr": qs[2] - qs[0],
    }


def _print_window_section(
    *,
    window_id: str,
    label: str,
    buckets: dict[str, dict[int, list[float]]],
) -> None:
    """One section per window: per-state-bucket × per-horizon stats table."""
    print(f"\n=== {window_id} — {label} ===")
    states_sorted = sorted(buckets.keys())
    if not states_sorted:
        print("  (no rows)")
        return
    for h in HORIZONS_TD:
        print(f"\n  horizon {h}td:")
        print(
            "    {:<18}  {:>6}  {:>9}  {:>9}  {:>9}  {:>9}".format(
                "state", "n", "mean", "median", "std", "iqr"
            )
        )
        for state in states_sorted:
            rs = buckets[state].get(h, [])
            s = _bucket_stats(rs)
            mean = f"{s['mean']:+.4f}" if s["mean"] is not None else "—"
            med = f"{s['median']:+.4f}" if s["median"] is not None else "—"
            std = f"{s['std']:.4f}" if s["std"] is not None else "—"
            iqr = f"{s['iqr']:.4f}" if s["iqr"] is not None else "—"
            print(
                "    {:<18}  {:>6}  {:>9}  {:>9}  {:>9}  {:>9}".format(
                    state, s["n"], mean, med, std, iqr
                )
            )
        non_none = []
        for state, by_h in buckets.items():
            if state and state != "NONE":
                non_none.extend(by_h.get(h, []))
        none_bucket = buckets.get("NONE", {}).get(h, [])
        t = _welch_t_stat(non_none, none_bucket)
        if t is not None:
            print(
                f"    Welch's t (non-NONE vs NONE): "
                f"{t:+.2f}  n_nn={len(non_none)}  n_n={len(none_bucket)}"
            )
        else:
            print(
                "    Welch's t (non-NONE vs NONE): — "
                f"(n_nn={len(non_none)}, n_n={len(none_bucket)})"
            )


def _print_tsv_summary(
    summaries: dict[str, dict[str, dict[int, list[float]]]],
) -> None:
    """TSV one row per (window, horizon): non-NEUTRAL mean - NEUTRAL mean, t."""
    print("\n=== TSV (window\thorizon\tn_nn\tn_n\tmean_nn\tmean_n\tdiff\twelch_t) ===")
    for wid, buckets in summaries.items():
        for h in HORIZONS_TD:
            nn = []
            for state, by_h in buckets.items():
                if state and state != "NONE":
                    nn.extend(by_h.get(h, []))
            n = buckets.get("NONE", {}).get(h, [])
            mean_nn = statistics.mean(nn) if nn else 0.0
            mean_n = statistics.mean(n) if n else 0.0
            t = _welch_t_stat(nn, n)
            t_str = f"{t:+.3f}" if t is not None else "—"
            print(
                f"{wid}\t{h}td\t{len(nn)}\t{len(n)}\t"
                f"{mean_nn:+.4f}\t{mean_n:+.4f}\t"
                f"{(mean_nn - mean_n):+.4f}\t{t_str}"
            )


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()

    settings = Settings.from_env()

    win_start = min(date.fromisoformat(s) for s, _, _ in WINDOWS.values())
    win_end = max(date.fromisoformat(e) for _, e, _ in WINDOWS.values())
    spx_start = date(win_start.year - 1, 1, 1)
    spx_end = date(win_end.year + 1, 12, 31)

    summaries: dict[str, dict[str, dict[int, list[float]]]] = {}
    with psycopg.connect(settings.db_dsn()) as conn:
        _, date_to_idx, closes = _fetch_spx_close_series(
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
                print(
                    f"WARN: {wid} has zero v1 walk-forward daily rows.",
                    file=sys.stderr,
                )
                continue

            buckets: dict[str, dict[int, list[float]]] = {}
            for r in rows:
                state = r["warning_state"] or "UNKNOWN"
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

            summaries[wid] = buckets
            _print_window_section(
                window_id=wid, label=f"{label} ({start} → {end})", buckets=buckets
            )

    if not summaries:
        print("ERROR: no v1 walk-forward rows for any window.", file=sys.stderr)
        return 1

    _print_tsv_summary(summaries)

    print("\n=== How to read this ===")
    print("- WF-3 is the crucible: 3-bucket breakout (NONE / CCA / BTD).")
    print("  Strongly negative t in CCA bucket = warning catches selloff;")
    print("  strongly positive t in BTD bucket = dip-buy works in crisis.")
    print("- WF-1 + WF-5 only have NONE vs BTD (no CCA fires in quiet).")
    print("  Positive t = BTD predicts above-baseline forward returns,")
    print("  confirming v1's dip-buy logic even in non-crisis regimes.")
    print("- The 'speed-as-quiet-instability' hypothesis (v2-A regression")
    print("  source) is NOT directly testable here — WF-5 warning_state")
    print("  never escalates beyond BTD. The integer speed=8→20 transition")
    print("  IS what BTD captures, so this probe DOES indirectly probe it.")
    print("- If BTD shows large positive forward returns in WF-5, v2-A's")
    print("  removal of speed cost those days' contribution to ranking →")
    print("  supports v2-C direction A or B (preserve quiet-regime BTD lift).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
