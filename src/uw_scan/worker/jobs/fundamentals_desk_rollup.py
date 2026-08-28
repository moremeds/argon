"""Nightly desk matrix rollup (spec §3c, Task 12): per-name revenue YoY and
gross-margin trajectory, persisted so the chain x metric matrix reads it at
request time with zero recompute.

Reads the newest-accepted-version statement panel via `current_statement_panel`
("today's view" -- newest obs per (ticker, period_end, statement), every period
per ticker, not a today-only filter -- see that module's docstring) and derives
`rev_yoy`/`gross_margin`/`gross_profit` through the SAME `build_features` math
the fundamental card uses. This job never re-implements payload selection or
the feature arithmetic; it only reshapes and persists.

HONEST ABSENCE, PER METRIC, PER PERIOD
---------------------------------------
A metric whose raw input field was flagged by an integrity check on THAT
period's own observations renders None -- never a wrong number and never
carried forward from a prior period. This mirrors the card path exactly:
`FundamentalObsRepository.violated_fields` names which raw provider fields
(`gross_profit`, not the feature name) a check fired on, and
`FEATURE_INPUTS` maps a feature back to the raw fields it consumes (see
`fundamentals/card.py::_checks_for`, duplicated here in miniature rather than
imported -- that helper is private to the card-assembly module, and this
job's only shared contract with it is `FEATURE_INPUTS` + `violated_fields`).
A ticker with one bad field still produces a row for that period; only the
affected metric goes None.

This is deliberately NOT the same filter `fundamental_scoring.py` uses
(`fundamentals.validity.excluded_fields`, gated by the active engine's
validity policy) -- that policy can exclude an entire observation from
scoring depending on which method version is active. This job answers a
simpler, engine-version-independent question -- "does the card believe this
raw figure" -- and uses `violated_fields` directly, matching the brief.

KNOWLEDGE_DATE mirrors `fundamental_scoring._knowledge_date`'s fallback: a
real filing date wins; absent one, `period_end + FALLBACK_LAG_DAYS` (US
filers must file a 10-Q within ~40-45 days of quarter end, so erring LATE
cannot manufacture look-ahead). Duplicated rather than imported for the same
reason as `_checks_for` above -- the scoring module's version is private to
its own knowledge-quarter bucketing.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import psycopg

from uw_scan.fundamentals.features import (
    FALLBACK_LAG_DAYS,
    FEATURE_INPUTS,
    build_features,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_panels import current_statement_panel
from uw_scan.storage.fundamentals_desk import FundamentalsDeskRepository

log = logging.getLogger(__name__)


def _f(row: dict | None, key: str) -> float | None:
    if not row:
        return None
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2: non-numeric statement cell -> None
        return None


def _knowledge_date(per: dict[str, Any], period: str, period_end: date) -> date:
    filed = per["filing_dates"].get(period)
    if filed:
        return datetime.strptime(filed[:10], "%Y-%m-%d").date()
    return period_end + timedelta(days=FALLBACK_LAG_DAYS)


def _checks_for(feature: str, violated: dict[str, list[str]]) -> list[str]:
    """Check names firing on any raw field this feature consumes. Mirrors
    `fundamentals.card._checks_for`."""
    return sorted(
        {
            check
            for source in FEATURE_INPUTS[feature]
            for check in violated.get(source, [])
        }
    )


def fundamentals_desk_rollup(
    conn: psycopg.Connection, *, schema: str = "uw_scan", dry_run: bool = False
) -> dict[str, int]:
    """One row per (ticker, period_end) across the full statement universe.

    `dry_run=True` computes every row exactly as a real run would and skips
    only the final `upsert_rows` write, so a caller previewing the run sees
    the real counts, never an estimate.
    """
    panel = current_statement_panel(conn, tickers=None, schema=schema)
    feats = build_features(panel)
    obs = FundamentalObsRepository(conn, schema=schema)

    rows: list[dict[str, Any]] = []
    for ticker, periods in feats.items():
        per = panel[ticker]
        for period, values in periods.items():
            period_end = date.fromisoformat(period)
            obs_ids = per["obs_ids"].get(period) or []
            violated = obs.violated_fields(obs_ids)

            rev_yoy = values.get("rev_growth")
            if _checks_for("rev_growth", violated):
                rev_yoy = None

            gross_margin = values.get("gross_margin")
            if _checks_for("gross_margin", violated):
                gross_margin = None

            gross_profit = _f(per["income-statements"].get(period), "gross_profit")
            if violated.get("gross_profit"):
                gross_profit = None

            rows.append(
                {
                    "ticker": ticker,
                    "period_end": period_end,
                    "rev_yoy": rev_yoy,
                    "gross_margin": gross_margin,
                    "gross_profit": gross_profit,
                    "knowledge_date": _knowledge_date(per, period, period_end),
                }
            )

    written = 0
    if not dry_run:
        written = FundamentalsDeskRepository(conn, schema=schema).upsert_rows(rows)

    result = {"tickers": len(feats), "rows": len(rows), "written": written}
    log.info("fundamentals_desk_rollup: %s", result)
    return result
