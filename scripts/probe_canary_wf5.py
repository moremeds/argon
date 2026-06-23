"""WF-5 probe: investigate `speed.score`'s role in the 2024 quiet regime.

After v2-A returned verdict STOP (AC-F4: WF-5 regressed -0.134), the open
question is what `speed.score` was capturing in the 2023-01-02 → 2024-12-31
window such that removing it materially hurt 60d AUC. This script is the
first probe — exploratory, not a test.

What it does:
  1. Pulls v1 walk-forward daily rows for WF-5 from regime_backtest_daily.
  2. Tabulates `payload.speed` (.score / .state) distributions per day.
  3. Side-by-sides WF-5 against WF-3 (where v2 won big, +0.087) and WF-1
     (where v2 broke even, +0.009) so you can SEE the regime difference.
  4. Computes simple descriptives: pct days speed.state != NEUTRAL,
     distribution of speed.score (0/8/20 are the only valid values),
     correlation of speed.score with v1 composite score within the window.

Why this matters: the user articulated speed as an "early instability
detector in quiet regimes, not a panic detector." This probe is the first
step to test that hypothesis empirically.

Usage:
  PGUSER=chenxi UW_SCAN_API_KEY=local-smoke uv run python scripts/probe_canary_wf5.py

Output is human-readable + TSV-parseable. Not persisted to DB — just stdout.

Spec context: docs/research/regime/canary-5yr-executive-summary.md §14
Decision context: docs/research/regime/_iterations/canary-v2c-design-notes.md
"""

from __future__ import annotations

import argparse
import statistics
import sys

import psycopg

from uw_scan.config import Settings

WINDOWS = {
    "WF-1": ("2015-01-01", "2016-12-31", "China deval, Brexit"),
    "WF-3": ("2019-01-01", "2020-09-30", "Repo crisis, COVID crash"),
    "WF-5": ("2023-01-01", "2024-12-31", "Bond-yield selloff, 2024 quiet"),
}


def _fetch_v1_window_daily(conn, *, schema: str, window_id: str) -> list[dict]:
    """Pull v1 walk-forward daily rows for one window_id.

    Joins regime_backtest_daily to its parent run via run_id, filters to
    production canary v1 walk-forward, returns daily rows ordered by date.
    """
    sql = f"""
        SELECT d.trade_date, d.score, d.level, d.payload
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
        for trade_date, score, level, payload in cur.fetchall():
            speed = payload.get("speed", {})
            # payload.speed shape varies — handle both nested dict and raw int.
            speed_score: int | None = None
            speed_state: str | None = None
            if isinstance(speed, dict):
                # walk-forward daily payload shape is the canary_scoring
                # `speed` sub-dict: {"score": int, "state": str, ...}
                # OR (older format) just the integer score under "speed" key.
                speed_score = speed.get("score")
                speed_state = speed.get("state")
            elif isinstance(speed, (int, float)):
                speed_score = int(speed)
            rows.append(
                {
                    "date": trade_date,
                    "score": float(score) if score is not None else None,
                    "band": level,
                    "tactical": payload.get("tactical"),
                    "structural": payload.get("structural"),
                    "speed_score": speed_score,
                    "speed_state": speed_state,
                    "warning_state": payload.get("warning_state"),
                }
            )
        return rows


def _summarize(rows: list[dict], label: str) -> dict:
    """Compute descriptive stats for one window's daily rows."""
    n = len(rows)
    speed_scores = [r["speed_score"] for r in rows if r["speed_score"] is not None]
    speed_states = [r["speed_state"] for r in rows if r["speed_state"] is not None]
    composite_scores = [r["score"] for r in rows if r["score"] is not None]

    state_counts: dict[str, int] = {}
    for s in speed_states:
        state_counts[s] = state_counts.get(s, 0) + 1

    score_value_counts: dict[int, int] = {}
    for s in speed_scores:
        score_value_counts[s] = score_value_counts.get(s, 0) + 1

    pct_nonzero_speed = (
        100.0 * sum(1 for s in speed_scores if s and s > 0) / len(speed_scores)
        if speed_scores
        else 0.0
    )

    speed_score_mean = statistics.mean(speed_scores) if speed_scores else 0.0
    composite_mean = statistics.mean(composite_scores) if composite_scores else 0.0

    return {
        "label": label,
        "n_days": n,
        "speed_score_mean": speed_score_mean,
        "speed_score_value_counts": score_value_counts,
        "speed_state_counts": state_counts,
        "pct_days_speed_nonzero": pct_nonzero_speed,
        "composite_score_mean": composite_mean,
    }


def _print_window_summary(s: dict, window_id: str) -> None:
    print(f"\n=== {window_id} — {s['label']} (n={s['n_days']} daily rows) ===")
    print(
        f"  speed.score: mean={s['speed_score_mean']:.3f}  pct_days_nonzero={s['pct_days_speed_nonzero']:.1f}%"
    )
    print(
        f"  speed.score value distribution: {dict(sorted(s['speed_score_value_counts'].items()))}"
    )
    print(f"  speed.state distribution: {s['speed_state_counts']}")
    print(f"  composite score mean: {s['composite_score_mean']:.3f}")


def _print_tsv(summaries: dict[str, dict]) -> None:
    print("\n=== TSV (window\tn\tspeed_mean\tspeed_pct_nonzero\tcomposite_mean) ===")
    for wid, s in summaries.items():
        print(
            f"{wid}\t{s['n_days']}\t"
            f"{s['speed_score_mean']:.3f}\t{s['pct_days_speed_nonzero']:.1f}\t"
            f"{s['composite_score_mean']:.3f}"
        )


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()

    settings = Settings.from_env()
    summaries: dict[str, dict] = {}
    with psycopg.connect(settings.db_dsn()) as conn:
        for wid, (start, end, label) in WINDOWS.items():
            rows = _fetch_v1_window_daily(
                conn, schema=settings.db_schema, window_id=wid
            )
            if not rows:
                print(
                    f"WARN: {wid} has zero v1 walk-forward daily rows. "
                    f"Has --walk-forward run with this batch?",
                    file=sys.stderr,
                )
                continue
            s = _summarize(rows, f"{label} ({start} → {end})")
            summaries[wid] = s
            _print_window_summary(s, wid)

    if not summaries:
        print(
            "ERROR: no v1 walk-forward daily rows found for any window.",
            file=sys.stderr,
        )
        return 1

    _print_tsv(summaries)

    print("\n=== Probe questions to explore from here ===")
    print("1. If WF-5's speed_pct_nonzero is comparable to WF-3's, speed is")
    print("   firing similarly but contributes to AUC differently — that's")
    print("   the regime-conditional contribution hypothesis.")
    print("2. If WF-5's speed_pct_nonzero is materially HIGHER than WF-3's,")
    print("   speed is overfiring in quiet — could be a calibration artifact.")
    print("3. Cross-reference with forward 60d returns by speed.state bucket.")
    print("   (Next probe — needs SPX join from vol_index_daily.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
