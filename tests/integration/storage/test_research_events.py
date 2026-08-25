"""Typed events and deterministic risk facts (migration 140).

The gate is the point. Argon ingests no source containing customer
concentration, supplier relationships, backlog, capex guidance, debt maturity,
or management guidance — those live in SEC document TEXT, which is not fetched.
Representing them as supported-but-empty would make a timeline look complete;
killing them and refusing writes makes the absence a fact.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from uw_scan.storage.research_events import (
    STATUS_KILLED,
    STATUS_LIVE,
    ResearchEventsRepository,
)


def _repo(seeded) -> ResearchEventsRepository:
    r = ResearchEventsRepository(seeded.conn, schema=seeded._schema)
    r.register_classes(
        [
            {
                "event_class": "sec_filing",
                "status": STATUS_LIVE,
                "source_table": "sec_filing_index",
                "rationale": "mirrored EDGAR filings",
                "measured_rows": 37510,
                "measured_on": date(2026, 8, 25),
            },
            {
                "event_class": "customer_concentration",
                "status": STATUS_KILLED,
                "source_table": None,
                "rationale": "lives in SEC document text, not ingested",
                "measured_rows": 0,
                "measured_on": date(2026, 8, 25),
            },
        ]
    )
    return r


def _event(**over):
    base = {
        "event_class": "sec_filing",
        "ticker": "NVDA",
        "occurred_at": date(2026, 4, 26),
        "first_known_at": date(2026, 5, 20),
        "title": "10-Q",
        "source_kind": "sec_filing_index",
        "source_ref": "0001045810-26-000052",
    }
    base.update(over)
    return base


def test_a_killed_class_refuses_writes(seeded_db_empty_cards):
    """An event in a killed class is the fabrication the gate exists to prevent."""
    r = _repo(seeded_db_empty_cards)
    with pytest.raises(ValueError, match="not live"):
        r.record_events([_event(event_class="customer_concentration")])


def test_an_unregistered_class_refuses_too(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    with pytest.raises(ValueError, match="not live"):
        r.record_events([_event(event_class="something_invented")])


def test_an_event_cannot_be_known_before_it_happened(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    _repo(seeded)
    with pytest.raises(psycopg.errors.CheckViolation):
        with seeded.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {seeded._schema}.research_events
                            (event_class, ticker, occurred_at, first_known_at,
                             title, source_kind)
                     VALUES ('sec_filing','NVDA','2026-05-20','2026-04-26',
                             'impossible','x')"""
            )
    seeded.conn.rollback()


def test_a_historical_read_uses_first_known_not_occurred(seeded_db_empty_cards):
    """A replay filtering on when things HAPPENED sees them before it could."""
    r = _repo(seeded_db_empty_cards)
    r.record_events([_event()])

    # The period ended 04-26 but the filing published 05-20. On 05-01 Argon
    # could not know it.
    assert r.events_for("NVDA", known_by=date(2026, 5, 1)) == []
    assert len(r.events_for("NVDA", known_by=date(2026, 5, 20))) == 1


def test_a_replay_writes_nothing_and_does_not_duplicate(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    assert r.record_events([_event()]) == 1
    assert r.record_events([_event()]) == 0


def test_an_amendment_supersedes_and_the_original_survives(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    r = _repo(seeded)
    r.register_classes(
        [
            {
                "event_class": "sec_amendment",
                "status": STATUS_LIVE,
                "rationale": "an amendment means the period cannot be dated",
                "measured_rows": 1806,
                "measured_on": date(2026, 8, 25),
            }
        ]
    )
    r.record_events([_event()])
    r.record_events(
        [
            _event(
                event_class="sec_amendment",
                first_known_at=date(2026, 8, 1),
                source_ref="0001045810-26-000099",
                title="10-Q/A",
            )
        ]
    )
    rows = r.events_for("NVDA")
    original = next(e for e in rows if e["event_class"] == "sec_filing")
    amendment = next(e for e in rows if e["event_class"] == "sec_amendment")
    r.supersede(original["event_id"], amendment["event_id"])

    after = r.events_for("NVDA")
    # The predecessor stays READABLE — that is what makes it a ledger.
    assert len(after) == 2
    superseded = next(e for e in after if e["event_class"] == "sec_filing")
    assert superseded["superseded_by"] == amendment["event_id"]


def test_a_risk_fact_is_a_number_against_a_threshold(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.record_risks(
        [
            {
                "ticker": "NVDA",
                "risk_kind": "thin_pit_evidence",
                "observed_value": 0.31,
                "threshold": 0.5,
                "breached": True,
                "severity": "watch",
                "statement": "31 of 100 observations carry a publication date",
                "invalidates": "TRUE_PIT_ONLY replays for this name",
                "source_kind": "fundamental_obs_availability",
                "as_of": date(2026, 8, 25),
            }
        ]
    )
    got = r.risks_for("NVDA")[0]
    assert got["breached"] is True
    assert float(got["observed_value"]) == 0.31
    # And it names what a breach makes untrustworthy — otherwise it is trivia.
    assert got["invalidates"] == "TRUE_PIT_ONLY replays for this name"


def test_risk_summary_counts_every_row_not_only_the_last_severity(
    seeded_db_empty_cards,
):
    """Keyed by kind while grouped by (kind, severity) drops all but one group."""
    r = _repo(seeded_db_empty_cards)
    r.record_risks(
        [
            {
                "ticker": "NVDA", "risk_kind": "stale_result", "observed_value": 61,
                "threshold": 45, "breached": True, "severity": "watch",
                "statement": "stale", "source_kind": "x", "as_of": date(2026, 8, 25),
            },
            {
                "ticker": "AAPL", "risk_kind": "stale_result", "observed_value": 3,
                "threshold": 45, "breached": False, "severity": "info",
                "statement": "fresh", "source_kind": "x", "as_of": date(2026, 8, 25),
            },
        ]
    )
    assert r.risk_summary()["stale_result"] == {
        "breached": 1,
        "evaluated": 2,
        "material": 0,
    }
