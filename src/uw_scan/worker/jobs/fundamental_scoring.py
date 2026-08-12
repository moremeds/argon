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
from datetime import date, datetime, timedelta
from typing import Any

import psycopg

from uw_scan.fundamentals.features import FALLBACK_LAG_DAYS, FEATURES, build_features
from uw_scan.fundamentals.scoring import (
    MIN_CROSS_SECTION,
    composite_scores,
    cross_section_z,
    inputs_hash,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

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


def fundamental_scoring(
    *,
    conn: psycopg.Connection,
    tier: str = "ranked",
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
) -> dict[str, int]:
    """Score every knowledge-quarter cross-section in the panel. Returns counters."""
    obs = FundamentalObsRepository(conn, schema=schema)
    scores = FundamentalScoresRepository(conn, schema=schema)

    engine = scores.active_version()
    if engine is None:
        log.error(
            "fundamental_scoring: no active method version — seed one with "
            "scripts/seed_fundamental_method.py before scoring"
        )
        return {"buckets": 0, "scored": 0, "inserted": 0, "skipped_thin": 0}

    names = tickers if tickers is not None else obs.list_universe(tier)
    if not names:
        log.info("fundamental_scoring: tier %r is empty — nothing to do", tier)
        return {"buckets": 0, "scored": 0, "inserted": 0, "skipped_thin": 0}

    panel_raw = obs.statement_panel(names)
    feats = build_features(panel_raw)

    # bucket -> ticker -> row. One name gets ONE vote per cross-section; when a
    # late 10-K and an on-time 10-Q land in the same quarter, the fresher period
    # wins rather than both competing.
    buckets: dict[str, dict[str, Any]] = {}
    for ticker, per_period in feats.items():
        per = panel_raw[ticker]
        for period, values in per_period.items():
            know, known = _knowledge_date(per, period)
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
            }

    totals = {"buckets": 0, "scored": 0, "inserted": 0, "skipped_thin": 0}
    for bucket in sorted(buckets):
        rows = buckets[bucket]
        if len(rows) < MIN_CROSS_SECTION:
            totals["skipped_thin"] += 1
            continue
        zs = cross_section_z(rows)
        comp = composite_scores(zs, rows)

        # as_of is the LAST knowledge date in the cross-section: the date by which
        # every name in it was public, and therefore the earliest date this
        # ranking could legitimately have been computed.
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
                        features=d["features"], company_type=None, engine=engine
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
                }
            )
        inserted = scores.insert_scores(out)
        totals["buckets"] += 1
        totals["scored"] += len(out)
        totals["inserted"] += inserted

    log.info("fundamental_scoring: %s", totals)
    return totals
