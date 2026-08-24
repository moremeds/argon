"""The two statement-panel read contracts, kept deliberately apart.

`current_statement_panel` answers "what does Argon believe TODAY" — newest
accepted version per identity. It is what the stock card, the statement history
endpoint and the anchor refresh want, and its behaviour is unchanged from the
`statement_panel()` this module extracted.

`statement_panel_as_of` answers "what could have been known at time T" — the
strongest-evidence version admitted by a named policy at a cutoff. It fails
closed: an observation with no claim, or with only untimed claims, never appears.

WHY THEY ARE NOT ONE FUNCTION WITH A FLAG
-----------------------------------------
Because the failure mode is silent. A single reader that "falls back" to current
behaviour when history is thin produces a full, plausible cross-section built
from figures the market had not seen — indistinguishable, downstream, from a
correct one. Two names, two return shapes, and no default that degrades.

HOW A VERSION'S AVAILABILITY IS COMPUTED
----------------------------------------
One observation may carry several admitted claims. Its effective availability is
the EARLIEST of them, not the latest: `capture_bounded @2024` says "safe no
earlier than 2024" while `true_pit @2020` says "actually published 2020", and
when both are held the second is simply the better-evidenced truth. Taking the
earliest is what lets later SEC evidence CORRECT a conservative capture bound
without anyone rewriting the capture claim.

Among versions, the one with the latest effective availability at or before the
cutoff wins — that is the most recent thing knowable at T. `obs_id` breaks a
genuine tie and appears nowhere else in the ordering: it is an insertion counter,
and treating it as availability is the bug this module was written to remove.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg

from uw_scan.fundamentals.observation_time import (
    EvidenceClass,
    EvidencePolicy,
    claim_strength,
    policy_classes,
)

#: Statement key in the observation table -> key in the panel `features` consumes.
#: A statement outside this map is skipped rather than crashing the panel: the
#: table's `statement` column is provider-shaped and may grow a value the feature
#: layer has no home for.
_STATEMENT_KEYS = {
    "income": "income-statements",
    "balance": "balance-sheets",
    "cash_flow": "cash-flows",
}

#: The Python strength ordering, rendered as SQL. Generated rather than written
#: out so the two cannot drift — a hand-copied CASE that disagrees with
#: `claim_strength` would pick a different claim's metadata than the code says.
_STRENGTH_SQL = (
    "CASE a.evidence_class "
    + " ".join(
        f"WHEN '{cls.value}' THEN {claim_strength(cls)}" for cls in EvidenceClass
    )
    + " END"
)


def _empty_period_map() -> dict[str, Any]:
    return {
        "income-statements": {},
        "balance-sheets": {},
        "cash-flows": {},
        "filing_dates": {},
        "obs_ids": {},
    }


def _reshape(rows: Sequence[tuple], *, with_availability: bool) -> dict[str, Any]:
    """Rows -> the dict `fundamentals.features` consumes.

    Shared by both readers on purpose: the panel's shape is a contract with the
    feature layer, and two copies of it would drift the moment one grows a key.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker, period_end, statement, raw, filed, obs_id = row[:6]
        key = _STATEMENT_KEYS.get(statement)
        if key is None:
            continue
        per = out.setdefault(ticker, _empty_period_map())
        if with_availability:
            per.setdefault("availability", {})
        period = period_end.isoformat()
        per[key][period] = raw
        per["obs_ids"].setdefault(period, []).append(obs_id)
        if filed:
            per["filing_dates"][period] = filed.isoformat()
        if with_availability:
            evidence_class, available_at, claim_key, availability_id = row[6:10]
            per["availability"].setdefault(period, {})[statement] = {
                "obs_id": obs_id,
                "availability_id": availability_id,
                "evidence_class": EvidenceClass(evidence_class),
                "available_at": available_at,
                "claim_key": claim_key,
            }
    return out


def current_statement_panel(
    conn: psycopg.Connection,
    tickers: Sequence[str] | None = None,
    period_type: str = "quarterly",
    *,
    schema: str = "uw_scan",
) -> dict[str, dict[str, Any]]:
    """Newest accepted version per (ticker, period, statement) — today's view.

    A restatement is a new immutable row, so "current" is the highest `obs_id`
    and never an edit to an older one. That is a correct answer to "what do we
    believe now" and a wrong answer to "what was knowable then", which is why
    the historical question has its own function.
    """
    where = ["period_type = %s"]
    params: list[Any] = [period_type]
    if tickers is not None:
        where.append("ticker = ANY(%s)")
        params.append(list(tickers))
    sql = f"""
        SELECT DISTINCT ON (ticker, period_end, statement)
               ticker, period_end, statement, raw_jsonb, filing_published_at,
               obs_id
          FROM {schema}.fundamental_statement_obs
         WHERE {" AND ".join(where)}
         ORDER BY ticker, period_end, statement, obs_id DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _reshape(cur.fetchall(), with_availability=False)


def statement_panel_as_of(
    conn: psycopg.Connection,
    *,
    as_of: datetime,
    evidence_policy: EvidencePolicy | str,
    tickers: Sequence[str] | None = None,
    period_type: str = "quarterly",
    schema: str = "uw_scan",
) -> dict[str, dict[str, Any]]:
    """Versions admitted by `evidence_policy` at `as_of`, newest-available wins.

    The returned panel carries everything the current one does plus an
    `availability` map — `{period: {statement: {obs_id, availability_id,
    evidence_class, available_at, claim_key}}}` — so a caller can bind WHICH
    version it used and
    WHY to its own result identity without re-querying the claims.

    Raises on a naive `as_of`: comparing it against timezone-aware claims is
    either an error or, worse, a silent several-hour shift across the cutoff.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError(
            "as_of must be timezone-aware; a naive cutoff cannot be compared "
            "against availability claims"
        )
    policy = EvidencePolicy(evidence_policy)
    admitted = sorted(c.value for c in policy_classes(policy))

    where = ["o.period_type = %(period_type)s"]
    params: dict[str, Any] = {
        "period_type": period_type,
        "as_of": as_of,
        "classes": admitted,
    }
    if tickers is not None:
        where.append("o.ticker = ANY(%(tickers)s)")
        params["tickers"] = list(tickers)

    # `best` reduces each observation's admitted claims to the earliest defensible
    # instant, preferring the stronger class when two share it. `availability_id`
    # is the final tie-break so repeated reads agree.
    sql = f"""
        WITH best AS (
            SELECT DISTINCT ON (a.obs_id)
                   a.obs_id, a.evidence_class, a.available_at, a.claim_key,
                   a.availability_id
              FROM {schema}.fundamental_obs_availability a
             WHERE a.evidence_class = ANY(%(classes)s)
               AND a.available_at <= %(as_of)s
             ORDER BY a.obs_id, a.available_at ASC, {_STRENGTH_SQL} DESC,
                      a.availability_id ASC
        )
        SELECT DISTINCT ON (o.ticker, o.period_end, o.statement)
               o.ticker, o.period_end, o.statement, o.raw_jsonb,
               o.filing_published_at, o.obs_id,
               best.evidence_class, best.available_at, best.claim_key,
               best.availability_id
          FROM {schema}.fundamental_statement_obs o
          JOIN best ON best.obs_id = o.obs_id
         WHERE {" AND ".join(where)}
         ORDER BY o.ticker, o.period_end, o.statement,
                  best.available_at DESC, o.obs_id DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _reshape(cur.fetchall(), with_availability=True)
