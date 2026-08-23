"""Sweep the USD state classifier's entry threshold, and test hysteresis against it.

READ-ONLY.  Never persists: it replays ``compute_usd_state``'s classification over the
stored evidence at monthly ``as_of`` instants and counts how often the label changes.
``macro_domain_states`` rows are immutable and undeletable (migration 125), so a sweep
that wrote its candidates would be permanent.

Two questions, one run:

1. Where should the boundary sit?  A classifier whose boundary sits near the MEDIAN of
   its own input distribution crosses it maximally often, because crossing density peaks
   where the density does.  The sweep reports each candidate's percentile alongside its
   flip count so the choice is calibrated rather than picked.
2. Does hysteresis help?  For each entry threshold it also runs a dual-threshold
   (Schmitt) variant that leaves a directional state only below a lower exit band.

Measured 2026-08-23 over 2021-01..2026-08 (68 monthly replays, 12,330 momentum points):
median |63-obs change| 1.45%, p75 2.91%, p90 4.57%.

    enter  pctile   exit  flips  longest run
      2.0   60.6%   none     29         6 mo     <- retired
      3.0   76.2%   none     13        14 mo     <- shipped
      3.0   76.2%   2.25     17        12 mo
      3.0   76.2%   1.50     23          7 mo
      5.0   92.8%   none      9        22 mo

The ``exit_band == enter`` rows reproduce ``compute_usd_state`` exactly; verified against
the real engine with parameters injected as a kwarg.

Hysteresis was REJECTED on this evidence: at every entry threshold the dual-threshold
variant left flips flat or RAISED them, because a wider band relocates transitions
(STRENGTHENING -> WEAKENING directly) rather than removing them.  The lever is where the
boundary sits, not how sticky it is.

Run inside a worker container, which has the repo and the prod DSN:

    docker cp scripts/research/usd_threshold_sweep.py argon-worker-massive-0-1:/tmp/
    docker exec argon-worker-massive-0-1 python /tmp/usd_threshold_sweep.py

Verdict: docs/research/2026-08-23-macro-state-replay-flip-census.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from statistics import median

from uw_scan.config import Settings
from uw_scan.macro.evidence_store import load_usd_observations
from uw_scan.macro.usd import ANCHOR_SERIES, DEFAULT_USD_PARAMETERS
from uw_scan.worker.scheduler import _repo

WINDOW_OBS = DEFAULT_USD_PARAMETERS.momentum_window_obs
ENTRY_CANDIDATES = [Decimal(x) for x in ("2.0", "2.5", "3.0", "3.5", "4.0", "4.5", "5.0")]
START_YEAR, END = 2021, (2026, 8)


def momentum_path(values: list[Decimal]) -> list[Decimal]:
    """Every 63-observation change computable from the window, oldest first."""
    return [
        (values[i] - values[i - WINDOW_OBS]) / values[i - WINDOW_OBS] * Decimal(100)
        for i in range(WINDOW_OBS, len(values))
        if values[i - WINDOW_OBS] != 0
    ]


def classify(path: list[Decimal], enter: Decimal, exit_band: Decimal) -> str:
    """Walk the path, seeded RANGEBOUND.  ``exit_band == enter`` is no hysteresis.

    Seeded rather than carried from storage on purpose: the answer at an ``as_of`` stays a
    pure function of the observations knowable then, which is what makes a replay of a
    stored row reproduce it.

    A path too short to yield a single momentum point is UNKNOWN, not RANGEBOUND -- the
    same answer ``_state`` gives, so the ``exit_band == enter`` rows reproduce the shipped
    classifier exactly instead of silently merging the warm-up months into one long run.
    """
    if not path:
        return "UNKNOWN"
    state = "RANGEBOUND"
    for m in path:
        if state == "STRENGTHENING":
            if m < exit_band:
                state = "WEAKENING" if m <= -enter else "RANGEBOUND"
        elif state == "WEAKENING":
            if m > -exit_band:
                state = "STRENGTHENING" if m >= enter else "RANGEBOUND"
        elif m >= enter:
            state = "STRENGTHENING"
        elif m <= -enter:
            state = "WEAKENING"
    return state


def month_starts():
    for year in range(START_YEAR, END[0] + 1):
        for month in range(1, 13):
            if (year, month) > END:
                return
            yield datetime(year, month, 1, tzinfo=UTC)


def run_lengths(states: list[str]) -> list[int]:
    runs, current, n = [], states[0], 1
    for state in states[1:]:
        if state == current:
            n += 1
        else:
            runs.append(n)
            current, n = state, 1
    runs.append(n)
    return runs


def main() -> None:
    settings = Settings.from_env()
    paths: dict[str, list[Decimal]] = {}
    with _repo(settings) as repo:
        for instant in month_starts():
            observations = load_usd_observations(repo, as_of=instant)
            newest_per_period: dict[object, Decimal] = {}
            for obs in sorted(
                (
                    o
                    for o in observations
                    if o.series_id == ANCHOR_SERIES and o.is_known_on(instant)
                ),
                key=lambda o: (o.period_end, o.available_at),
            ):
                newest_per_period[obs.period_end] = obs.value
            values = [newest_per_period[k] for k in sorted(newest_per_period)]
            paths[instant.strftime("%Y-%m")] = momentum_path(values)

    every_move = sorted(abs(m) for path in paths.values() for m in path)
    if not every_move:
        raise SystemExit("no momentum points -- is the evidence store populated?")

    def percentile_of(threshold: Decimal) -> float:
        return 100.0 * sum(1 for m in every_move if m < threshold) / len(every_move)

    print(
        f"|{WINDOW_OBS}-obs change| over {len(every_move)} points "
        f"({START_YEAR}-01..{END[0]}-{END[1]:02d}): "
        f"median={median(every_move):.2f}%  "
        f"p75={every_move[int(0.75 * len(every_move))]:.2f}%  "
        f"p90={every_move[int(0.90 * len(every_move))]:.2f}%\n"
    )
    print(f"{'enter':>6} {'pctile':>7} {'exit':>6} {'flips':>6} {'longest run':>12}")
    print("-" * 46)
    for enter in ENTRY_CANDIDATES:
        for exit_band in (enter, enter * Decimal("0.75"), enter * Decimal("0.5")):
            states = [classify(p, enter, exit_band) for p in paths.values()]
            flips = sum(1 for a, b in zip(states, states[1:]) if a != b)
            label = "none" if exit_band == enter else f"{exit_band:.2f}"
            print(
                f"{enter:>6} {percentile_of(enter):>6.1f}% {label:>6} {flips:>6} "
                f"{max(run_lengths(states)):>9} mo"
            )
        print()


if __name__ == "__main__":
    main()
