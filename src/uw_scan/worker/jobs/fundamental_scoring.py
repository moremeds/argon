"""Stage-2 scoring job — cross-sectional subscores and composite (migration 117).

Reads the tier-1 statement panel, forms one cross-section per KNOWLEDGE QUARTER,
and persists a score row per (ticker, as_of) under the active method version.

WHY KNOWLEDGE QUARTER AND NOT FISCAL PERIOD
-------------------------------------------
Filers do not share a fiscal calendar — NVDA's quarter ends 01-31, MSFT's 12-31.
Keying a cross-section on `fiscal_date_ending` shatters it into thin slices that
then fall under the width floor and are dropped SILENTLY. That bug cost a
published finding once (an `asset_turnover` t of −4.30 that was really −0.49), so
the panel is keyed on when the information became public, which is the only basis
on which two names belong in one cross-section anyway.

WHAT THIS JOB DOES NOT DO
-------------------------
It does not decide anything. The composite it writes is a sort key across the wide
tier and nothing more: not an expected return (zero measured gross alpha), not a
risk score (the top decile is riskier than the middle), not a per-name forecast
(the within-ticker test is a powered null). Consumers carry those limits.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import psycopg

from uw_scan.fundamentals.features import FALLBACK_LAG_DAYS, FEATURES, build_features
from uw_scan.fundamentals.scoring import (
    MIN_CROSS_SECTION,
    composite_scores,
    cross_section_z,
    inputs_hash,
)
from uw_scan.fundamentals.observation_time import EvidencePolicy
from uw_scan.fundamentals.validity import (
    VALIDITY_POLICY_EXCLUDE,
    apply_validity,
    excluded_fields,
    policy_for_engine,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_panels import (
    current_statement_panel,
    statement_panel_as_of,
)
from uw_scan.storage.fundamental_provenance import (
    ROLE_EXCLUDED,
    ROLE_USED,
    STAGE_FEATURES,
    STAGE_PANEL,
    FundamentalProvenanceRepository,
)
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

#: What the `evidence_policy` column holds for a row built from the CURRENT
#: panel. Not a member of `EvidencePolicy`: that enum is the set of HISTORICAL
#: admission rules, and adding "current" to it would hand a replay a way to ask
#: for exactly the rows that must fail closed.
CURRENT_VINTAGE_POLICY = "current_vintage"

log = logging.getLogger(__name__)


def _knowledge_date(per: dict[str, Any], period: str) -> tuple[date, bool]:
    """(knowledge date, whether it came from a real filing_date).

    The fallback is recorded rather than hidden. It errs EARLY for late filers,
    which manufactures look-ahead — measured cost is composite IC 0.059 with the
    fallback against 0.039 without — so a consumer needing leak-free data must be
    able to filter it out.
    """
    filed = per["filing_dates"].get(period)
    if filed:
        return (datetime.strptime(filed[:10], "%Y-%m-%d").date(), True)
    period_end = datetime.strptime(period[:10], "%Y-%m-%d").date()
    return (period_end + timedelta(days=FALLBACK_LAG_DAYS), False)


def _period_available_at(per: dict[str, Any], period: str) -> date | None:
    """When every statement of `period` had become available, as a date.

    MAX across the three statements: the period is not usable until its last leg
    is. Returns None when the panel carried no availability block for it, which
    only happens if a caller mixes a current panel into a replay.
    """
    evidence = (per.get("availability") or {}).get(period) or {}
    instants = [e["available_at"] for e in evidence.values() if e.get("available_at")]
    return max(instants).date() if instants else None


def _build_buckets(
    feats: dict[str, Any],
    panel_raw: dict[str, Any],
    *,
    knowledge_cutoff: date,
    availability_wins: bool = False,
) -> tuple[dict[str, dict[str, Any]], int]:
    """Group one row per (knowledge quarter, ticker). Returns (buckets, withheld).

    One name gets ONE vote per cross-section: when a late 10-K and an on-time
    10-Q land in the same quarter, the fresher period wins rather than both
    competing.

    A period whose knowledge date has not ARRIVED is withheld. When a filer's
    real filing date is still unknown, `_knowledge_date` estimates `period_end +
    FALLBACK_LAG_DAYS`, and for a fresh quarter that estimate lands in the
    future — the name simply is not public yet. Admitting it breaks two things
    at once: it contributes to every other name's z-score using figures the
    market has not seen, and because `as_of` is the bucket's MAX knowledge date,
    one unarrived estimate stamps the entire cross-section with a future date.
    A future `as_of` then wins `ORDER BY as_of DESC` against every later run,
    freezing the card on one stale compute until the calendar catches up.
    Measured on prod 2026-08-23: AMAT and CSCO (period_end 2026-07-31, no filing
    date) stamped 371 rows `2026-09-14` and shadowed six days of fresher scores.
    """
    buckets: dict[str, dict[str, Any]] = {}
    withheld = 0
    for ticker, per_period in feats.items():
        per = panel_raw[ticker]
        for period, values in per_period.items():
            know, known = _knowledge_date(per, period)
            if availability_wins:
                # A restated version became knowable when IT was published, not
                # when the period's ORIGINAL filing was. Bucketing a 2023
                # restatement under 2020 is the contamination this work removes,
                # and `filing_published_at` is the same on both versions — so in
                # a replay the availability claim is the only honest clock.
                available = _period_available_at(per, period)
                if available is None:
                    continue
                know = available
            if know > knowledge_cutoff:
                withheld += 1
                continue
            bucket = f"{know.year}Q{(know.month - 1) // 3 + 1}"
            slot = buckets.setdefault(bucket, {})
            prior = slot.get(ticker)
            if prior and prior["period"] >= period:
                continue
            slot[ticker] = {
                "features": values,
                "period": period,
                "knowledge_date": know,
                "filing_date_known": known,
                "obs_ids": sorted(per["obs_ids"].get(period, [])),
                "availability_ids": sorted(
                    e["availability_id"]
                    for e in ((per.get("availability") or {}).get(period) or {}).values()
                    if e.get("availability_id") is not None
                ),
            }
    return buckets, withheld


def _violated_by_ticker_period(
    obs: FundamentalObsRepository, panel: dict[str, Any]
) -> dict[str, dict[str, set[str]]]:
    """{ticker: {period: {violated field, ...}}} for the panel actually loaded.

    One query for the whole panel. Reads the panel's OWN `obs_ids` rather than
    re-selecting by ticker, so the violations line up with the exact content
    versions this run scored — under a replay those are not today's versions.
    """
    all_ids = [
        obs_id
        for per in panel.values()
        for ids in (per.get("obs_ids") or {}).values()
        for obs_id in ids
    ]
    if not all_ids:
        return {}
    by_obs = obs.violations_by_obs(all_ids)
    if not by_obs:
        return {}
    out: dict[str, dict[str, set[str]]] = {}
    for ticker, per in panel.items():
        per_period: dict[str, set[str]] = {}
        for period, ids in (per.get("obs_ids") or {}).items():
            fields: set[str] = set()
            for obs_id in ids:
                found = by_obs.get(obs_id)
                if found:
                    fields |= excluded_fields(found)
            if fields:
                per_period[period] = fields
        if per_period:
            out[ticker] = per_period
    return out


def _record_provenance(
    *,
    provenance: FundamentalProvenanceRepository,
    result_ids: dict[tuple[str, Any], int],
    rows: dict[str, dict[str, Any]],
    violated: dict[str, dict[str, set[str]]],
    as_of: date,
) -> int:
    """Link each score to the observations it used, and those it withheld.

    The `excluded` rows are the ones an array of ids could never express: the
    observation WAS considered, its values were withheld by an integrity check,
    and a reader asking "why is this feature na" gets the check name rather than
    an absence.
    """
    links: list[dict[str, Any]] = []
    for ticker, d in rows.items():
        result_id = result_ids.get((ticker, as_of))
        if result_id is None:
            continue
        bad_fields = (violated.get(ticker) or {}).get(d["period"]) or set()
        for obs_id in d["obs_ids"]:
            links.append(
                {
                    "result_id": result_id,
                    "obs_id": obs_id,
                    "role": ROLE_USED,
                    "stage": STAGE_PANEL,
                    "detail": {"period": d["period"]},
                }
            )
            if bad_fields:
                links.append(
                    {
                        "result_id": result_id,
                        "obs_id": obs_id,
                        "role": ROLE_EXCLUDED,
                        "stage": STAGE_FEATURES,
                        "detail": {
                            "period": d["period"],
                            "withheld_fields": sorted(bad_fields),
                        },
                    }
                )
    return provenance.record(links)


def fundamental_scoring(
    *,
    conn: psycopg.Connection,
    tier: str = "ranked",
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
    knowledge_cutoff: date | None = None,
    evidence_policy: EvidencePolicy | str | None = None,
    engine_version: str | None = None,
) -> dict[str, int]:
    """Score every knowledge-quarter cross-section in the panel. Returns counters.

    `knowledge_cutoff` defaults to today and bounds which periods are public
    enough to score. It is a parameter rather than an inline `date.today()` so a
    replay names its own as-of, and so a test does not depend on the wall clock.

    `evidence_policy` selects the statement panel and is the whole point of this
    signature:

    - **None** — the CURRENT panel, newest version per identity. Unchanged
      behaviour, written as `evidence_policy='current_vintage'` with a NULL
      cutoff. This is the scheduled refresh's mode and is not a replay: it stands
      at no particular time.
    - **`TRUE_PIT_ONLY` / `CAPTURE_BOUNDED`** — a replay. Only versions the policy
      can defend at `knowledge_cutoff` are admitted, and each row is bucketed by
      when ITS version became available rather than by the period's original
      filing date.

    There is deliberately no historical default. A caller that wants a replay
    says so; a caller that does not gets today's panel and a row that says so.

    WHAT A REPLAY CANNOT DO
    -----------------------
    Running at a LATE cutoff does not faithfully reproduce an EARLY bucket. A
    name whose 2020 filing was superseded in 2023 appears in the 2023 bucket, not
    the 2020 one, because the panel returns one version per identity — the best
    one admissible at the cutoff. To reconstruct the cross-section as it stood in
    quarter B, run with `knowledge_cutoff` inside B. The alternative — a panel
    read per bucket — is real work and belongs with M2's run ledger, not here.
    """
    cutoff = knowledge_cutoff or date.today()
    policy = EvidencePolicy(evidence_policy) if evidence_policy is not None else None
    policy_name = policy.value if policy is not None else CURRENT_VINTAGE_POLICY
    # The replay stands at the END of its cutoff day: a filing published that
    # morning was knowable that day, and a midnight boundary would drop it.
    as_of_cutoff = (
        datetime.combine(cutoff, time.max).replace(tzinfo=UTC)
        if policy is not None
        else None
    )
    obs = FundamentalObsRepository(conn, schema=schema)
    scores = FundamentalScoresRepository(conn, schema=schema)

    # An explicit engine is how a comparison run scores the SAME panel under two
    # methods without flipping the production default. It is not a general
    # escape hatch: the validity policy still comes from the version, so an
    # override cannot decouple the method from the label.
    engine = engine_version or scores.active_version()
    if engine is None:
        log.error(
            "fundamental_scoring: no active method version — seed one with "
            "scripts/seed_fundamental_method.py before scoring"
        )
        return {
            "buckets": 0,
            "scored": 0,
            "inserted": 0,
            "skipped_thin": 0,
            "withheld_unpublished": 0,
            "excluded_no_evidence": 0,
        }

    names = tickers if tickers is not None else obs.list_universe(tier)
    if not names:
        log.info("fundamental_scoring: tier %r is empty — nothing to do", tier)
        return {
            "buckets": 0,
            "scored": 0,
            "inserted": 0,
            "skipped_thin": 0,
            "withheld_unpublished": 0,
            "excluded_no_evidence": 0,
        }

    if policy is None:
        panel_raw = current_statement_panel(conn, names, schema=schema)
        excluded = 0
    else:
        panel_raw = statement_panel_as_of(
            conn,
            as_of=as_of_cutoff,
            evidence_policy=policy,
            tickers=names,
            schema=schema,
        )
        # What the policy REFUSED, reported rather than implied. A replay that
        # returns a thin cross-section and says nothing about why looks
        # identical to a universe that simply has few names.
        excluded = _excluded_periods(
            current_statement_panel(conn, names, schema=schema), panel_raw
        )

    feats = build_features(panel_raw)

    # M1.1: under an engine whose policy says so, a value the integrity checks
    # impugn is withheld from the MATH, not only from the card. The policy is
    # read from the engine version rather than passed in, so a row can never
    # claim a method it did not run.
    validity = policy_for_engine(engine)
    validity_counters = {"values_excluded": 0, "periods_touched": 0}
    violated_by_period: dict[str, dict[str, set[str]]] = {}
    prov = FundamentalProvenanceRepository(conn, schema=schema)
    if validity == VALIDITY_POLICY_EXCLUDE:
        violated_by_period = _violated_by_ticker_period(obs, panel_raw)
        feats, validity_counters = apply_validity(feats, violated_by_period)

    buckets, withheld = _build_buckets(
        feats,
        panel_raw,
        knowledge_cutoff=cutoff,
        availability_wins=policy is not None,
    )

    totals = {
        "buckets": 0,
        "scored": 0,
        "inserted": 0,
        "skipped_thin": 0,
        "withheld_unpublished": withheld,
        "excluded_no_evidence": excluded,
        "validity_values_excluded": validity_counters["values_excluded"],
        "validity_periods_touched": validity_counters["periods_touched"],
        "provenance_rows": 0,
    }
    for bucket in sorted(buckets):
        rows = buckets[bucket]
        if len(rows) < MIN_CROSS_SECTION:
            totals["skipped_thin"] += 1
            continue
        zs = cross_section_z(rows)
        comp = composite_scores(zs, rows)

        # as_of is the LAST knowledge date in the cross-section: the date by which
        # every name in it was public, and therefore the earliest date this
        # ranking could legitimately have been computed. That sentence is only
        # true because `_build_buckets` withheld unarrived estimates — a single
        # one in here would date the ranking's birth in the future.
        as_of = max(d["knowledge_date"] for d in rows.values())

        out: list[dict[str, Any]] = []
        for ticker, d in rows.items():
            present = sum(1 for f in FEATURES if d["features"].get(f) is not None)
            out.append(
                {
                    "ticker": ticker,
                    "as_of": as_of,
                    "engine_version": engine,
                    "inputs_hash": inputs_hash(
                        features=d["features"],
                        company_type=None,
                        engine=engine,
                        evidence_policy=policy.value if policy else None,
                    ),
                    "period_end": datetime.strptime(
                        d["period"][:10], "%Y-%m-%d"
                    ).date(),
                    "knowledge_date": d["knowledge_date"],
                    "filing_date_known": d["filing_date_known"],
                    "composite": comp.get(ticker),
                    **{f: d["features"].get(f) for f in FEATURES},
                    "features_present": present,
                    "source_obs_ids": d["obs_ids"],
                    "evidence_policy": policy_name,
                    "as_of_cutoff": as_of_cutoff,
                    "availability_ids": d.get("availability_ids") or [],
                }
            )
        inserted = scores.insert_scores(out)
        totals["buckets"] += 1
        totals["scored"] += len(out)
        totals["inserted"] += inserted

        # M1.3: typed provenance, under engines that declare a validity policy
        # other than "off". v1 rows are deliberately NOT backfilled — absence of
        # rows there must keep reading as `legacy`, not as "cited nothing".
        if validity == VALIDITY_POLICY_EXCLUDE:
            totals["provenance_rows"] += _record_provenance(
                provenance=prov,
                result_ids=scores.result_ids(out),
                rows=rows,
                violated=violated_by_period,
                as_of=as_of,
            )

    log.info("fundamental_scoring[%s]: %s", policy_name, totals)
    return totals


def _excluded_periods(current: dict[str, Any], admitted: dict[str, Any]) -> int:
    """(ticker, period) pairs the current panel has that the policy refused."""
    count = 0
    for ticker, per in current.items():
        admitted_periods = set(
            (admitted.get(ticker) or {}).get("balance-sheets", {})
        ) | set((admitted.get(ticker) or {}).get("income-statements", {}))
        have = set(per.get("balance-sheets", {})) | set(
            per.get("income-statements", {})
        )
        count += len(have - admitted_periods)
    return count
