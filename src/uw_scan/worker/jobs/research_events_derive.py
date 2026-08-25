"""Derive typed events and deterministic risk facts from ingested evidence (M6).

Every row this writes points back at something Argon already holds. Nothing here
reads a news feed, and nothing generates a fact — the classes that would need
either are KILLED by the discovery gate below rather than represented as
supported-but-empty.

THE DISCOVERY GATE, MEASURED 2026-08-25
---------------------------------------
Live, with the row counts that decided it:

    sec_filing                37,510   sec_filing_index
    sec_amendment              1,806   sec_filing_index (is_amendment)
    statement_published       45,196   fundamental_statement_obs.filing_published_at
    segment_disclosure         3,203   revenue_breakdown_obs (business segments)
    geographic_disclosure      7,088   revenue_breakdown_obs (geographical)
    input_violation            1,006   fundamental_obs_violations

Killed:

    restatement                    1   ONE multi-version identity in 87,177
                                       observations. A class that fires once is
                                       not a class; it is an anecdote.
    customer_concentration         0   lives in SEC document TEXT, not ingested
    supplier_relationship          0   same
    backlog                        0   same
    capex_guidance                 0   same
    debt_maturity                  0   same
    management_guidance            0   same
    product_regulatory             0   requires a licensed news source

A killed class refuses writes. That is the point: an event in a killed class is
precisely the fabrication the gate exists to prevent, so the repository raises
rather than warning.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import psycopg

from uw_scan.storage.research_events import (
    SEVERITY_INFO,
    SEVERITY_MATERIAL,
    SEVERITY_WATCH,
    STATUS_KILLED,
    STATUS_LIVE,
    ResearchEventsRepository,
)

log = logging.getLogger(__name__)

#: Coverage below which a name's history is too thinly evidenced to replay.
#: Chosen at the measured median, not at a round number: 240 of 401 tickers sit
#: at >=90% true_pit, so a 0.5 threshold flags the genuinely thin tail rather
#: than most of the universe.
TRUE_PIT_FLOOR = 0.5

#: Days after which the newest compatible result stops being "current". Same
#: value the Radar uses, deliberately — two staleness definitions would let a
#: page call a result fresh while a risk fact called it stale.
STALE_DAYS = 45


def register_discovery_gate(
    conn: psycopg.Connection, *, schema: str = "uw_scan"
) -> dict[str, int]:
    """Measure each candidate class and persist its live/killed verdict."""
    repo = ResearchEventsRepository(conn, schema=schema)
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for key, sql in (
            ("sec_filing", f"SELECT count(*) FROM {schema}.sec_filing_index"),
            (
                "sec_amendment",
                f"SELECT count(*) FROM {schema}.sec_filing_index WHERE is_amendment",
            ),
            (
                "statement_published",
                f"""SELECT count(*) FROM {schema}.fundamental_statement_obs
                     WHERE filing_published_at IS NOT NULL""",
            ),
            (
                "segment_disclosure",
                f"""SELECT count(*) FROM {schema}.revenue_breakdown_obs
                     WHERE cardinality(axis) = 1
                       AND axis[1] LIKE '%%BusinessSegments%%'""",
            ),
            (
                "geographic_disclosure",
                f"""SELECT count(*) FROM {schema}.revenue_breakdown_obs
                     WHERE cardinality(axis) = 1
                       AND axis[1] LIKE '%%Geographical%%'""",
            ),
            (
                "input_violation",
                f"SELECT count(*) FROM {schema}.fundamental_obs_violations",
            ),
            (
                "restatement",
                f"""SELECT count(*) FROM (
                      SELECT 1 FROM {schema}.fundamental_statement_obs
                       GROUP BY source, ticker, period_end, period_type, statement
                      HAVING count(DISTINCT content_hash) > 1) x""",
            ),
        ):
            cur.execute(sql)
            counts[key] = int(cur.fetchone()[0])

    today = date.today()
    rows: list[dict[str, Any]] = [
        {
            "event_class": "sec_filing",
            "status": STATUS_LIVE,
            "source_table": "sec_filing_index",
            "rationale": "SEC EDGAR periodic filings, mirrored locally",
            "measured_rows": counts["sec_filing"],
            "measured_on": today,
        },
        {
            "event_class": "sec_amendment",
            "status": STATUS_LIVE,
            "source_table": "sec_filing_index",
            "rationale": (
                "an amendment means the period's content cannot be dated, which "
                "is a research fact in its own right"
            ),
            "measured_rows": counts["sec_amendment"],
            "measured_on": today,
        },
        {
            "event_class": "statement_published",
            "status": STATUS_LIVE,
            "source_table": "fundamental_statement_obs",
            "rationale": "a period's statements became available",
            "measured_rows": counts["statement_published"],
            "measured_on": today,
        },
        {
            "event_class": "segment_disclosure",
            "status": STATUS_LIVE,
            "source_table": "revenue_breakdown_obs",
            "rationale": "business-segment revenue broken out on an XBRL axis",
            "measured_rows": counts["segment_disclosure"],
            "measured_on": today,
        },
        {
            "event_class": "geographic_disclosure",
            "status": STATUS_LIVE,
            "source_table": "revenue_breakdown_obs",
            "rationale": "geographic revenue broken out on an XBRL axis",
            "measured_rows": counts["geographic_disclosure"],
            "measured_on": today,
        },
        {
            "event_class": "input_violation",
            "status": STATUS_LIVE,
            "source_table": "fundamental_obs_violations",
            "rationale": "an integrity check rejected a provider figure",
            "measured_rows": counts["input_violation"],
            "measured_on": today,
        },
        {
            "event_class": "restatement",
            "status": STATUS_KILLED,
            "source_table": "fundamental_statement_obs",
            "rationale": (
                f"only {counts['restatement']} multi-version identity in the "
                "whole store. A class that fires once is an anecdote, not a "
                "class. Revive if the count grows once real version history "
                "accrues."
            ),
            "measured_rows": counts["restatement"],
            "measured_on": today,
        },
    ]
    for killed in (
        "customer_concentration",
        "supplier_relationship",
        "backlog",
        "capex_guidance",
        "debt_maturity",
        "management_guidance",
    ):
        rows.append(
            {
                "event_class": killed,
                "status": STATUS_KILLED,
                "source_table": None,
                "rationale": (
                    "lives in SEC document TEXT, which Argon does not fetch. "
                    "Killed rather than represented as supported-but-empty."
                ),
                "measured_rows": 0,
                "measured_on": today,
            }
        )
    rows.append(
        {
            "event_class": "product_regulatory",
            "status": STATUS_KILLED,
            "source_table": None,
            "rationale": (
                "requires a licensed news source. No unlicensed news dependence."
            ),
            "measured_rows": 0,
            "measured_on": today,
        }
    )
    repo.register_classes(rows)
    log.info("register_discovery_gate: %s", counts)
    return counts


def derive_events(
    conn: psycopg.Connection,
    *,
    schema: str = "uw_scan",
    since: date | None = None,
    limit: int = 20000,
) -> dict[str, int]:
    """Turn ingested evidence into typed events. Idempotent on the identity key."""
    repo = ResearchEventsRepository(conn, schema=schema)
    counters: dict[str, int] = {}
    cutoff = since or date(2020, 1, 1)

    with conn.cursor() as cur:
        # --- SEC filings and amendments ---
        cur.execute(
            f"""SELECT ticker, form, report_date, filing_date, accession,
                       is_amendment
                  FROM {schema}.sec_filing_index
                 WHERE filing_date >= %s
                 ORDER BY filing_date DESC LIMIT %s""",
            (cutoff, limit),
        )
        filings = cur.fetchall()

    rows: list[dict[str, Any]] = []
    for ticker, form, report_date, filing_date, accession, amended in filings:
        rows.append(
            {
                "event_class": "sec_amendment" if amended else "sec_filing",
                "ticker": ticker,
                # The period the filing covers is when it OCCURRED; the filing
                # date is when the world could know.
                "occurred_at": report_date,
                "first_known_at": filing_date,
                "title": f"{form} for period ending {report_date.isoformat()}",
                "detail": {"form": form, "accession": accession},
                "source_kind": "sec_filing_index",
                "source_ref": accession,
            }
        )
    counters["filings"] = repo.record_events(rows)

    # --- integrity violations ---
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT o.ticker, o.period_end, v.check_name, v.field,
                       o.obs_id, o.first_observed_at::date
                  FROM {schema}.fundamental_obs_violations v
                  JOIN {schema}.fundamental_statement_obs o USING (obs_id)
                 ORDER BY v.violation_id DESC LIMIT %s""",
            (limit,),
        )
        violations = cur.fetchall()
    counters["violations"] = repo.record_events(
        [
            {
                "event_class": "input_violation",
                "ticker": ticker,
                "occurred_at": period_end,
                "first_known_at": observed,
                "title": f"{check} on {field or 'observation'}",
                "detail": {"check": check, "field": field},
                "source_kind": "fundamental_obs_violations",
                "source_ref": f"obs:{obs_id}:{check}",
            }
            for ticker, period_end, check, field, obs_id, observed in violations
        ]
    )

    log.info("derive_events: %s", counters)
    return counters


def derive_risk_facts(
    conn: psycopg.Connection,
    *,
    schema: str = "uw_scan",
    engine_version: str | None = None,
    as_of: date | None = None,
) -> dict[str, int]:
    """Compute deterministic risk facts. Every one is a number against a threshold."""
    repo = ResearchEventsRepository(conn, schema=schema)
    today = as_of or date.today()
    rows: list[dict[str, Any]] = []

    with conn.cursor() as cur:
        # --- evidence thinness: what fraction of a name's observations are PIT ---
        cur.execute(
            f"""
            SELECT o.ticker,
                   count(*)                                          AS total,
                   count(a.availability_id)                          AS pit
              FROM {schema}.fundamental_statement_obs o
              LEFT JOIN {schema}.fundamental_obs_availability a
                     ON a.obs_id = o.obs_id AND a.evidence_class = 'true_pit'
             GROUP BY o.ticker
            """
        )
        for ticker, total, pit in cur.fetchall():
            share = (pit / total) if total else 0.0
            rows.append(
                {
                    "ticker": ticker,
                    "risk_kind": "thin_pit_evidence",
                    "observed_value": round(share, 4),
                    "threshold": TRUE_PIT_FLOOR,
                    "breached": share < TRUE_PIT_FLOOR,
                    "severity": SEVERITY_WATCH if share < TRUE_PIT_FLOOR else SEVERITY_INFO,
                    "statement": (
                        f"{pit} of {total} observations carry a publication date"
                    ),
                    "invalidates": (
                        "TRUE_PIT_ONLY replays for this name"
                        if share < TRUE_PIT_FLOOR
                        else None
                    ),
                    "source_kind": "fundamental_obs_availability",
                    "as_of": today,
                }
            )

        # --- unclassified company type: the valuation method is a fallback ---
        cur.execute(
            f"""SELECT ticker, status FROM {schema}.company_identity
                 WHERE valid_to IS NULL"""
        )
        for ticker, status in cur.fetchall():
            defaulted = status == "defaulted"
            rows.append(
                {
                    "ticker": ticker,
                    "risk_kind": "unevidenced_company_type",
                    "observed_value": 0 if defaulted else 1,
                    "threshold": 1,
                    "breached": defaulted,
                    "severity": SEVERITY_WATCH if defaulted else SEVERITY_INFO,
                    "statement": (
                        "no classification rule matched; the pooled-universe "
                        "valuation default applies"
                        if defaulted
                        else "company type routed from evidence"
                    ),
                    "invalidates": (
                        "the valuation method routed for this name"
                        if defaulted
                        else None
                    ),
                    "source_kind": "company_identity",
                    "as_of": today,
                }
            )

        # --- staleness of the newest compatible result ---
        if engine_version:
            cur.execute(
                f"""SELECT ticker, max(as_of)
                      FROM {schema}.fundamental_dimensions
                     WHERE engine_version = %s
                     GROUP BY ticker""",
                (engine_version,),
            )
            for ticker, newest in cur.fetchall():
                age = (today - newest).days
                rows.append(
                    {
                        "ticker": ticker,
                        "risk_kind": "stale_result",
                        "observed_value": age,
                        "threshold": STALE_DAYS,
                        "breached": age > STALE_DAYS,
                        "severity": (
                            SEVERITY_MATERIAL if age > STALE_DAYS * 4
                            else SEVERITY_WATCH if age > STALE_DAYS
                            else SEVERITY_INFO
                        ),
                        "statement": f"newest compatible result is {age} days old",
                        "invalidates": (
                            "every dimension and priority shown for this name"
                            if age > STALE_DAYS
                            else None
                        ),
                        "source_kind": "fundamental_dimensions",
                        "as_of": today,
                    }
                )

    written = repo.record_risks(rows)
    breached = sum(1 for r in rows if r["breached"])
    counters = {"evaluated": written, "breached": breached}
    log.info("derive_risk_facts: %s", counters)
    return counters
