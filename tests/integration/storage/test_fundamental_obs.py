"""Insert-or-touch semantics for tier-1 fundamental observations (migration 114).

The immutability contract is the thing under test: an unchanged refetch must bump
one timestamp and write no fact, while a restatement must land beside the old row
rather than replacing it. Both halves have to hold or the point-in-time history is
either bloated with phantoms or silently rewritten.

Figures are NVDA's real 2026-04-30 quarterly balance sheet, frozen.
"""

from __future__ import annotations

from datetime import date

from uw_scan.fundamentals.statements import (
    FIELD_MAP_VERSION,
    Violation,
    check_violations,
    content_hash,
    normalize,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository

NVDA_BALANCE = {
    "ticker": "NVDA",
    "fiscal_date_ending": "2026-04-30",
    "report_type": "quarterly",
    "total_assets": "259474000000",
    "total_liabilities": "64000000000",
    "total_shareholder_equity": "195474000000",
    "common_stock_shares_outstanding": "24391000000",
    "inserted_at": "2026-05-21T06:58:08Z",
    "updated_at": "2026-08-11T03:58:32Z",
}

PERIOD = date(2026, 4, 30)


def _row(raw: dict) -> dict:
    payload = normalize(raw)
    return {
        "source": "uw",
        "ticker": "NVDA",
        "period_end": PERIOD,
        "period_type": "quarterly",
        "statement": "balance",
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": date(2026, 5, 21),
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _repo(seeded) -> FundamentalObsRepository:
    return FundamentalObsRepository(seeded.conn, schema=seeded._schema)


def test_unchanged_refetch_writes_no_fact(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    row = _row(NVDA_BALANCE)

    assert repo.record_statements([row]) == (1, 0)
    # Same payload, provider timestamps moved — exactly what a daily refetch
    # looks like. Must touch, never insert.
    moved = _row(dict(NVDA_BALANCE, updated_at="2027-01-01T00:00:00Z"))
    assert repo.record_statements([moved]) == (0, 1)


def test_restatement_lands_beside_the_original(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    original = _row(NVDA_BALANCE)
    repo.record_statements([original])

    restated = _row(dict(NVDA_BALANCE, total_assets="259999000000"))
    assert repo.record_statements([restated]) == (1, 0)

    # Both survive: the old observation is never edited away.
    assert repo.obs_id(**{k: original[k] for k in _KEY}) is not None
    assert repo.obs_id(**{k: restated[k] for k in _KEY}) is not None
    assert original["content_hash"] != restated["content_hash"]


_KEY = (
    "source",
    "ticker",
    "period_end",
    "period_type",
    "statement",
    "content_hash",
)


def test_a_filing_date_that_arrives_later_is_stored(seeded_db_empty_cards):
    """UW publishes the statement before it publishes the filing date.

    `fundamental-breakdown`'s frontier trails the statement endpoints for 7 of a random
    40 names (INFY by 91 days, GFS by 181), so the first ingest of a fresh quarter
    stores NULL and a later re-pull is the only thing that can fill it. `content_hash`
    excludes the filing date by design, so that re-pull collides — and before this
    behaviour existed the ON CONFLICT clause touched only `last_seen_at` and the date
    was discarded permanently.
    """
    repo = _repo(seeded_db_empty_cards)
    undated = dict(_row(NVDA_BALANCE), filing_published_at=None)
    assert repo.record_statements([undated]) == (1, 0)

    dated = _row(NVDA_BALANCE)  # same payload, same hash, now carrying a date
    assert dated["content_hash"] == undated["content_hash"]
    assert repo.record_statements([dated]) == (0, 1)

    assert _filing_date_of(seeded_db_empty_cards, undated) == date(2026, 5, 21)


def test_a_recorded_filing_date_is_never_overwritten(seeded_db_empty_cards):
    """Fill NULL, never revise. The column is a fact about an immutable observation;
    letting a re-pull rewrite it would make it mean 'whatever the provider said most
    recently', which is not something a point-in-time consumer can use."""
    repo = _repo(seeded_db_empty_cards)
    original = _row(NVDA_BALANCE)
    repo.record_statements([original])

    moved = dict(original, filing_published_at=date(2027, 1, 1))
    assert repo.record_statements([moved]) == (0, 1)

    assert _filing_date_of(seeded_db_empty_cards, original) == date(2026, 5, 21)


def _filing_date_of(seeded, row: dict):
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT filing_published_at FROM {seeded._schema}.fundamental_statement_obs"
            " WHERE ticker = %s AND period_end = %s AND statement = %s"
            "   AND content_hash = %s",
            (row["ticker"], row["period_end"], row["statement"], row["content_hash"]),
        )
        return cur.fetchone()[0]


def test_violations_are_idempotent_per_check(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    bad_raw = dict(NVDA_BALANCE, common_stock_shares_outstanding="15393")
    row = _row(bad_raw)
    repo.record_statements([row])
    obs_id = repo.obs_id(**{k: row[k] for k in _KEY})
    assert obs_id is not None

    violations = check_violations("balance", normalize(bad_raw))
    assert [v.check_name for v in violations] == ["implausible_share_count"]

    repo.record_violations(obs_id, violations)
    repo.record_violations(obs_id, violations)  # re-audit of an immutable payload
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {seeded_db_empty_cards._schema}"
            ".fundamental_obs_violations WHERE obs_id = %s",
            (obs_id,),
        )
        assert cur.fetchone()[0] == 1


def test_empty_batch_is_a_noop(seeded_db_empty_cards):
    """The ingest job calls this per ticker; a ticker whose statements all 404
    must not raise."""
    assert _repo(seeded_db_empty_cards).record_statements([]) == (0, 0)


def test_unknown_tier_reads_as_nothing_to_do(seeded_db_empty_cards):
    """The job gates on this being non-empty, so an unseeded tier must spend zero
    UW calls rather than crash."""
    assert _repo(seeded_db_empty_cards).list_universe("no_such_tier") == []


def test_seed_universe_is_idempotent_and_reactivates(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.seed_universe("core", [("NVDA", "L1", "core chain coverage")])
    repo.seed_universe("core", [("NVDA", "L1", "core chain coverage")])
    assert repo.list_universe("core") == ["NVDA"]

    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {seeded_db_empty_cards._schema}.fundamental_universe "
            "SET removed_at = now() WHERE ticker = 'NVDA'"
        )
    seeded_db_empty_cards.conn.commit()
    assert repo.list_universe("core") == []

    # Re-seeding is a statement of intended membership, so it un-removes.
    repo.seed_universe("core", [("NVDA", "L1", "core chain coverage")])
    assert repo.list_universe("core") == ["NVDA"]


def test_violations_on_empty_list_writes_nothing(seeded_db_empty_cards):
    assert _repo(seeded_db_empty_cards).record_violations(1, []) == 0


def test_recheck_applies_a_newly_added_check_retroactively(seeded_db_empty_cards):
    """Payloads are immutable, so a check added after rows land only ever sees
    future ingests unless it is replayed. This is how the gross-profit check
    reached the 580 rows already stored."""
    repo = _repo(seeded_db_empty_cards)
    bad = {
        "ticker": "CEG",
        "fiscal_date_ending": "2026-06-30",
        "report_type": "quarterly",
        "total_revenue": "7506000000",
        "cost_of_revenue": "6276000000",
        "gross_profit": "7506000000",
    }
    payload = normalize(bad)
    row = _row(NVDA_BALANCE) | {
        "ticker": "CEG",
        "statement": "income",
        "content_hash": content_hash(payload),
        "raw_jsonb": payload,
    }
    repo.record_statements([row])

    scanned, new = repo.recheck_violations()
    assert scanned >= 1 and new == 1
    # Idempotent: replaying finds nothing further to record.
    assert repo.recheck_violations()[1] == 0


def test_violated_fields_lets_the_card_suppress_a_bad_figure(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    bad = {
        "ticker": "CEG",
        "fiscal_date_ending": "2026-06-30",
        "report_type": "quarterly",
        "total_revenue": "7506000000",
        "cost_of_revenue": "6276000000",
        "gross_profit": "7506000000",
    }
    payload = normalize(bad)
    row = _row(NVDA_BALANCE) | {
        "ticker": "CEG",
        "statement": "income",
        "content_hash": content_hash(payload),
        "raw_jsonb": payload,
    }
    repo.record_statements([row])
    repo.recheck_violations()
    obs_id = repo.obs_id(**{k: row[k] for k in _KEY})
    assert repo.violated_fields([obs_id]) == {
        "gross_profit": ["gross_profit_equals_revenue_despite_costs"]
    }


def test_violated_fields_is_empty_for_clean_observations(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    row = _row(NVDA_BALANCE)
    repo.record_statements([row])
    assert repo.violated_fields([repo.obs_id(**{k: row[k] for k in _KEY})]) == {}
    assert repo.violated_fields([]) == {}


def test_violation_detail_is_optional(seeded_db_empty_cards):
    """`Violation.detail` defaults to None (it cannot use a default_factory —
    the dataclass has a field literally named `field`), so the writer must
    accept None rather than assuming a dict."""
    repo = _repo(seeded_db_empty_cards)
    row = _row(NVDA_BALANCE)
    repo.record_statements([row])
    obs_id = repo.obs_id(**{k: row[k] for k in _KEY})
    assert repo.record_violations(obs_id, [Violation("synthetic_check")]) == 1
