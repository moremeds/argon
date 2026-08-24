"""Census the continuous features under the macro domain states, before anything is fitted.

READ-ONLY. Replays the engines at historical instants and harvests the CONTINUOUS values
they carry -- factor levels, factor changes, confidence terms, contradiction counts. It
never calls ``_persist``: ``macro_domain_states`` rows are immutable and undeletable
(migration 125), so a speculative replay written to prod could never be taken back.

Why this exists: the 2026-08-23 flip census killed the categorical state label as a
validation unit (4/8/13 transitions in 68 monthly instants). That census chose a MONTHLY
clock. The evidence store's availability structure does not require one, and the honest
question for MC6 is what sample a continuous feature could actually carry.

Two numbers per feature, and the second is the one that decides:

  points      how many PIT instants produced a value
  eff_n       points adjusted for AR(1) autocorrelation, N*(1-rho)/(1+rho)

A slow-moving level read weekly is not one independent observation per read. Reporting
``points`` alone would restate the overlapping-window error that the flip census avoided
by accident.

    docker exec argon-worker-massive-0-1 python /tmp/macro_continuous_feature_preflight.py

Verdict: docs/research/2026-08-24-macro-continuous-feature-preflight/VERDICT.md
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from uw_scan.config import Settings
from uw_scan.macro.evidence_store import (
    load_inflation_observations,
    load_rates_observations,
    load_usd_observations,
)
from uw_scan.macro.inflation import compute_inflation_state
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.macro.rates import compute_rates_state
from uw_scan.macro.usd import UpstreamState, compute_usd_state
from uw_scan.worker.jobs.macro_state_jobs import _attribution, _paths
from uw_scan.worker.scheduler import _repo

#: Weekly, because that is what the binding publisher supports. DTWEXBGS carries 1,405
#: daily periods but only 293 distinct ``available_at`` instants over the window -- it is
#: a weekly release carrying daily observations, so replaying it daily would resample the
#: same release five times and inflate every count by 5x while adding no information.
STEP = timedelta(days=7)
START = datetime(2021, 1, 4, tzinfo=UTC)
END = datetime(2026, 8, 18, tzinfo=UTC)

#: Evidence availability, measured directly rather than assumed from a contract's declared
#: frequency. A series whose vintages were backfilled at retrieval time has one instant no
#: matter how many periods it holds, and that is invisible from ``frequency``.
AVAILABILITY_SQL = """
SELECT domain, series_id, frequency,
       COUNT(*)                     AS rows,
       COUNT(DISTINCT period_end)   AS periods,
       COUNT(DISTINCT available_at) AS avail_instants,
       MIN(period_end)::text        AS first_period,
       MAX(period_end)::text        AS last_period
FROM uw_scan.macro_observations
WHERE quality_status = 'valid'
GROUP BY 1, 2, 3
ORDER BY 1, avail_instants DESC
"""


def instants():
    inst = START
    while inst <= END:
        yield inst
        inst += STEP


def harvest(state) -> dict[str, float]:
    """Every continuous number a domain state carries, flattened to one row."""
    out: dict[str, float] = {
        "confidence": float(state.confidence),
        "contradiction_count": float(len(state.contradictions)),
    }
    for term in state.confidence_reasons:
        out[f"term.{term.term}"] = float(term.value)
    for factor in state.factors:
        out[f"level.{factor.series_id}"] = float(factor.value)
        if factor.change_over_window is not None:
            out[f"change.{factor.series_id}"] = float(factor.change_over_window)
    return out


def ar1_effective_n(values: list[float]) -> tuple[float, float]:
    """Return (lag-1 autocorrelation, effective sample size).

    A level sampled faster than it moves carries far less information than its row count
    claims. N*(1-rho)/(1+rho) is the standard AR(1) correction; it is a floor on honesty,
    not a precise variance estimate, and a feature that fails it is not rescued by a
    better estimator.
    """
    n = len(values)
    if n < 3:
        return (float("nan"), float(n))
    mean = sum(values) / n
    dev = [v - mean for v in values]
    denom = sum(d * d for d in dev)
    if denom == 0:
        return (1.0, 1.0)  # a constant carries one observation, whatever its length
    rho = sum(dev[i] * dev[i + 1] for i in range(n - 1)) / denom
    rho = max(-0.999, min(0.999, rho))
    return (rho, n * (1 - rho) / (1 + rho))


def main() -> None:
    settings = Settings.from_env()
    panels: dict[str, dict[str, list[float]]] = {
        d: defaultdict(list) for d in ("inflation", "policy_rates", "usd")
    }
    errors: dict[str, dict[str, int]] = {d: defaultdict(int) for d in panels}
    covered: dict[str, int] = defaultdict(int)

    with _repo(settings) as repo:
        with repo._conn.cursor() as cur:  # noqa: SLF001 - read-only census
            cur.execute(AVAILABILITY_SQL)
            cols = [c.name for c in cur.description]
            availability = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

        for inst in instants():
            rates_state = None

            try:
                infl = compute_inflation_state(
                    load_inflation_observations(repo, as_of=inst),
                    as_of=inst,
                    prior_state=None,
                )
                covered["inflation"] += 1
                for k, v in harvest(infl).items():
                    panels["inflation"][k].append(v)
            except Exception as exc:
                errors["inflation"][type(exc).__name__] += 1

            try:
                obs = load_rates_observations(repo, as_of=inst)
                rates_state = compute_rates_state(
                    _paths(build_policy_comparison(repo, as_of=inst)),
                    as_of=inst,
                    observations=obs,
                    attribution=_attribution(obs, as_of=inst),
                    prior_state=None,
                )
                covered["policy_rates"] += 1
                for k, v in harvest(rates_state).items():
                    panels["policy_rates"][k].append(v)
            except Exception as exc:
                errors["policy_rates"][type(exc).__name__] += 1

            try:
                upstream = (
                    ()
                    if rates_state is None
                    else (
                        UpstreamState(
                            domain="policy_rates",
                            state=rates_state.state,
                            direction=rates_state.direction,
                            inputs_hash=rates_state.inputs_hash,
                            as_of=inst,
                        ),
                    )
                )
                usd = compute_usd_state(
                    load_usd_observations(repo, as_of=inst),
                    as_of=inst,
                    upstream=upstream,
                    prior_state=None,
                )
                covered["usd"] += 1
                for k, v in harvest(usd).items():
                    panels["usd"][k].append(v)
            except Exception as exc:
                errors["usd"][type(exc).__name__] += 1

    features = []
    for domain, cols in panels.items():
        for name, values in sorted(cols.items()):
            rho, eff = ar1_effective_n(values)
            distinct = len(set(values))
            features.append(
                {
                    "domain": domain,
                    "feature": name,
                    "points": len(values),
                    "distinct_values": distinct,
                    "rho_lag1": None if rho != rho else round(rho, 4),
                    "eff_n": round(eff, 1),
                    "constant": distinct <= 1,
                }
            )

    print(
        json.dumps(
            {
                "window": {
                    "start": START.isoformat(),
                    "end": END.isoformat(),
                    "step_days": 7,
                },
                "instants_attempted": sum(1 for _ in instants()),
                "instants_covered": dict(covered),
                "errors": {d: dict(e) for d, e in errors.items()},
                "availability": availability,
                "features": features,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
