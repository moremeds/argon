"""Measure regime-state flip/whipsaw rates in cri_snapshots and vcg_snapshots.

Step 1 of the adaptive-smoothing evaluation (see the companion catalog in
`scripts/research/adaptive_ema.py`). Answers one question before any smoother or
debouncer gets built: do the regime state series actually chatter?

Method -- run-length analysis, which maps directly onto the candidate fixes:
  * A *flip* is state[i] != state[i-1] within a contiguous series.
  * A *whipsaw* is a run of length <= WHIPSAW_MAX that is sandwiched between two
    runs of the SAME other state (out-and-back). That is the alert failure mode:
    fire, then unfire.
  * A dwell/confirmation filter of N bars suppresses every run shorter than N,
    so the run-length histogram states directly what dwell would buy.

Series analysed:
  * EOD daily -- one row per data_date (latest scanned_at wins; the hourly
    :20/:25 scans and backfills write many rows per date). Contiguity = the
    ordered trading-date sequence.
  * Live intraday -- ~5-min cadence, segmented PER SESSION. An overnight gap is
    not a flip, so sessions are never joined.

Read-only. Persists a markdown trace to docs/research/ (standing rule: a number
you cannot reproduce from a saved trace did not happen).

Reproduce:
    export PGPASSWORD=...   # argon_app on the mini
    uv run python scripts/research/regime_flip_rate_probe.py \
        --host 100.66.147.98 --db option_wizard
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

WHIPSAW_MAX = 2  # a run this short or shorter, sandwiched, counts as a whipsaw
DWELL_CANDIDATES = (2, 3, 4)

# (label, table, state expression). VCG's `regime` column is constant
# DIVERGENCE across every row on the mini as of 2026-07-27, so `interpretation`
# is its only varying state -- using `regime` would trivially report zero flips.
SERIES = (
    ("CRI level", "cri_snapshots", "cri_level"),
    ("VCG interpretation", "vcg_snapshots", "interpretation"),
)

EOD_SQL = """
SELECT DISTINCT ON (data_date) data_date, {state}
FROM uw_scan.{table}
WHERE basis = 'eod' AND data_date IS NOT NULL AND {state} IS NOT NULL
ORDER BY data_date, scanned_at DESC
"""

LIVE_SQL = """
SELECT data_date, scanned_at, {state}
FROM uw_scan.{table}
WHERE basis = 'live' AND data_date IS NOT NULL AND {state} IS NOT NULL
ORDER BY data_date, scanned_at
"""


@dataclass
class Runs:
    """Run-length summary for one or more contiguous state segments."""

    observations: int = 0
    segments: int = 0
    runs: list[tuple[str, int]] = field(default_factory=list)
    whipsaws: list[tuple[str, int]] = field(default_factory=list)
    states: Counter = field(default_factory=Counter)

    @property
    def flips(self) -> int:
        # Each segment's first run is not preceded by a flip.
        return max(0, len(self.runs) - self.segments)

    @property
    def whipsaw_share(self) -> float:
        return len(self.whipsaws) / self.flips if self.flips else 0.0

    def suppressed_by_dwell(self, n: int) -> int:
        """Runs shorter than n -- what a dwell-n confirmation filter removes."""
        return sum(1 for _, length in self.runs if length < n)


def _segment_runs(states: list[str]) -> list[tuple[str, int]]:
    runs: list[tuple[str, int]] = []
    for s in states:
        if runs and runs[-1][0] == s:
            runs[-1] = (s, runs[-1][1] + 1)
        else:
            runs.append((s, 1))
    return runs


def analyse(segments: list[list[str]]) -> Runs:
    out = Runs()
    for seg in segments:
        if not seg:
            continue
        out.segments += 1
        out.observations += len(seg)
        out.states.update(seg)
        runs = _segment_runs(seg)
        out.runs.extend(runs)
        # Sandwiched short run: prev and next runs exist and share a state.
        for i in range(1, len(runs) - 1):
            state, length = runs[i]
            if length <= WHIPSAW_MAX and runs[i - 1][0] == runs[i + 1][0]:
                out.whipsaws.append((state, length))
    return out


def fetch(conn, sql: str, table: str, state: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql.format(table=table, state=state))
        return cur.fetchall()


def _months(dates: list[date]) -> float:
    if len(dates) < 2:
        return 0.0
    return max((max(dates) - min(dates)).days, 1) / 30.44


def render(results: dict[str, dict[str, tuple[Runs, str]]]) -> str:
    lines = [
        "# Regime state flip-rate probe",
        "",
        "Step 1 of the adaptive-smoothing evaluation. Measures whether CRI/VCG",
        "regime states chatter enough to justify a debouncer (hysteresis/dwell)",
        "or an adaptive smoother -- before building either.",
        "",
        f"- Whipsaw definition: a sandwiched run of <= {WHIPSAW_MAX} observations",
        "  (state flips out and back to where it came from).",
        "- Source: `uw_scan.{cri,vcg}_snapshots` on the mini (`option_wizard`).",
        "- Reproduce: `uv run python scripts/research/regime_flip_rate_probe.py"
        " --host 100.66.147.98 --db option_wizard`",
        "",
    ]
    for basis, series in results.items():
        lines += [f"## {basis}", ""]
        header = (
            "| Series | Obs | Segments | Flips | Flips/mo | Whipsaws | "
            "Whipsaw share | "
            + " | ".join(f"dwell-{n}" for n in DWELL_CANDIDATES)
            + " |"
        )
        lines += [header, "|" + "---|" * (7 + len(DWELL_CANDIDATES))]
        for label, (r, span) in series.items():
            dwell = " | ".join(str(r.suppressed_by_dwell(n)) for n in DWELL_CANDIDATES)
            lines.append(
                f"| {label} | {r.observations} | {r.segments} | {r.flips} | "
                f"{span} | {len(r.whipsaws)} | {r.whipsaw_share:.0%} | {dwell} |"
            )
        lines.append("")
        for label, (r, _) in series.items():
            hist = Counter(length for _, length in r.runs)
            dist = ", ".join(f"{k}:{hist[k]}" for k in sorted(hist))
            mix = ", ".join(f"{s} {c}" for s, c in r.states.most_common())
            lines += [f"- **{label}** state mix: {mix}", f"  - run lengths: {dist}"]
        lines.append("")
    lines += [
        "## Reading this",
        "",
        "`dwell-N` counts runs shorter than N observations -- exactly what an",
        "N-bar confirmation filter would suppress. If whipsaw share is near zero",
        "there is no chatter problem and both the debouncer and the adaptive-EMA",
        "work are unwarranted.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("UW_SCAN_DB_HOST", "127.0.0.1"))
    ap.add_argument("--db", default=os.environ.get("UW_SCAN_DB_NAME", "option_wizard"))
    ap.add_argument("--user", default=os.environ.get("UW_SCAN_DB_USER", "argon_app"))
    ap.add_argument("--port", default=os.environ.get("UW_SCAN_DB_PORT", "5432"))
    ap.add_argument("--out", default="docs/research/2026-07-27-regime-flip-rate.md")
    args = ap.parse_args()

    results: dict[str, dict[str, tuple[Runs, str]]] = {
        "EOD daily": {},
        "Live intraday": {},
    }
    with psycopg.connect(
        host=args.host, port=args.port, dbname=args.db, user=args.user
    ) as conn:
        for label, table, state in SERIES:
            rows = fetch(conn, EOD_SQL, table, state)
            r = analyse([[s for _, s in rows]])
            span = (
                f"{r.flips / m:.1f}" if (m := _months([d for d, _ in rows])) else "n/a"
            )
            results["EOD daily"][label] = (r, span)

            rows = fetch(conn, LIVE_SQL, table, state)
            sessions: dict[date, list[str]] = {}
            for d, _ts, s in rows:
                sessions.setdefault(d, []).append(s)
            r = analyse(list(sessions.values()))
            m = _months(list(sessions))
            results["Live intraday"][label] = (r, f"{r.flips / m:.1f}" if m else "n/a")

    out = Path(args.out)
    out.write_text(render(results))
    print(render(results))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
