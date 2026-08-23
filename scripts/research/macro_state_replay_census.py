"""Replay the macro domain states over history and census their transitions.

READ-ONLY: computes states at historical ``as_of`` instants and prints them.  It never
calls ``_persist``, which matters because ``macro_domain_states`` rows are immutable and
undeletable (migration 125) -- a speculative replay written to prod could never be taken
back.

Answers one question: is a macro state label a testable object?  A categorical whose
history holds 4 transitions cannot carry a t-stat no matter how many years you replay.

    docker exec argon-worker-massive-0-1 python /tmp/macro_state_replay_census.py

Verdict for the 2021-01..2026-08 window: docs/research/2026-08-23-macro-state-replay-flip-census.md
"""
from datetime import UTC, datetime

from uw_scan.config import Settings
from uw_scan.macro.evidence_store import (
    load_inflation_observations, load_rates_observations, load_usd_observations,
)
from uw_scan.macro.inflation import compute_inflation_state
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.macro.rates import compute_rates_state
from uw_scan.macro.usd import UpstreamState, compute_usd_state
from uw_scan.worker.jobs.macro_state_jobs import _attribution, _paths
from uw_scan.worker.scheduler import _repo


def months():
    for y in range(2021, 2027):
        for m in range(1, 13):
            if (y, m) > (2026, 8):
                return
            yield datetime(y, m, 1, tzinfo=UTC)


def main() -> None:
    s = Settings.from_env()
    series: dict[str, list[tuple[str, str, str]]] = {"inflation": [], "policy_rates": [], "usd": []}
    with _repo(s) as repo:
        for inst in months():
            tag = inst.strftime("%Y-%m")
            try:
                infl = compute_inflation_state(
                    load_inflation_observations(repo, as_of=inst), as_of=inst, prior_state=None)
                series["inflation"].append((tag, infl.state, infl.direction))
            except Exception as exc:
                series["inflation"].append((tag, f"ERR:{type(exc).__name__}", "-"))
            rates = None
            try:
                obs = load_rates_observations(repo, as_of=inst)
                rates = compute_rates_state(
                    _paths(build_policy_comparison(repo, as_of=inst)), as_of=inst,
                    observations=obs, attribution=_attribution(obs, as_of=inst), prior_state=None)
                series["policy_rates"].append((tag, rates.state, rates.direction))
            except Exception as exc:
                series["policy_rates"].append((tag, f"ERR:{type(exc).__name__}", "-"))
            try:
                up = () if rates is None else (UpstreamState(
                    domain="policy_rates", state=rates.state, direction=rates.direction,
                    inputs_hash=rates.inputs_hash, as_of=inst),)
                usd = compute_usd_state(load_usd_observations(repo, as_of=inst), as_of=inst,
                                        upstream=up, prior_state=None)
                series["usd"].append((tag, usd.state, usd.direction))
            except Exception as exc:
                series["usd"].append((tag, f"ERR:{type(exc).__name__}", "-"))

    for dom, rows in series.items():
        flips = sum(1 for a, b in zip(rows, rows[1:]) if a[1] != b[1])
        dflips = sum(1 for a, b in zip(rows, rows[1:]) if a[2] != b[2])
        labels = sorted({r[1] for r in rows})
        print(f"\n=== {dom}: {len(rows)} months, {flips} state flips, {dflips} direction flips")
        print(f"    labels seen: {labels}")
        prev = None
        for tag, st, di in rows:
            if st != prev:
                print(f"    {tag}  -> {st:<22} {di}")
                prev = st


if __name__ == "__main__":
    main()
