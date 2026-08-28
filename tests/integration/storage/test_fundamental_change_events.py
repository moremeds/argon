"""Five change-event classes for the delta rail (spec §5-iv, Task 8):
`band_entry`, `band_exit`, `implied_move_shift`, `coverage_change`,
`bucket_flip`. All five read tables Argon already ingests, all five must
pass through the discovery gate (`register_discovery_gate`), and every
class's identity key must make a rerun a true no-op.

Uses a PRIVATE database (`option_wizard_test_changeevents`), not the shared
`option_wizard_test` the rest of the integration suite resets per-fixture —
mirrors `test_implied_move.py`'s private-DB shape exactly (other sessions run
integration tests against the shared DB concurrently).

FIXTURE PROVENANCE (queried live, 2026-08-28, dev warm store
postgresql://argon_app@127.0.0.1/option_wizard_local)
------------------------------------------------------------------------
`valuation_anchors` (ticker A, engine `fundamentals-v1:77aea364`, real row):

    SELECT ticker, as_of, method, buy_below, observe_low, observe_mid,
           observe_high, risk_above, spot, spot_percentile, history_quarters,
           confidence, confidence_reasons_jsonb, inputs_hash, company_type
      FROM uw_scan.valuation_anchors
     WHERE ticker = 'A' AND engine_version = 'fundamentals-v1:77aea364';

    -> as_of=2026-05-15, method=sales_to_ev, buy_below=129.833274501128,
       observe_low=144.043685789822, observe_mid=149.353852575318,
       observe_high=156.783699803719, risk_above=162.817745030498,
       spot=111.7, spot_percentile=1, history_quarters=20,
       confidence=medium, company_type=unclassified,
       confidence_reasons_jsonb=["no sector on file for this name, so the
       band uses the pooled-universe default (revenue / enterprise value)
       rather than a method chosen for its business"],
       inputs_hash=7f8416c30695589169bc15c5d03f2079eade0c88a750f3c7858dd96b6656a7fe

    This real row (spot <= buy_below -> IN zone) is used UNMODIFIED as the
    "current" snapshot in the band_entry/band_exit tests below.

`daily_ohlc` (ticker A, real close, used for the "previous" snapshot):

    SELECT date, close FROM uw_scan.daily_ohlc WHERE ticker = 'A'
     AND close > 129.833274501128 ORDER BY date DESC LIMIT 1;
    -> date=2026-08-12, close=148.1200

DEVIATION -- the band_entry/band_exit tests need TWO valuation_anchors
snapshots for the SAME ticker, one in-zone and one not, within the 30-day
lookback. No such natural pair exists in this dev store (checked: 0 rows
where a ticker's in-zone status flips between two as_of dates for one
engine_version). Per the accepted ruling that "valuation_anchors pairings...
may carry transparently documented test constructions" (test_implied_move.py
precedent), the PAIRING here is constructed: A's real 148.1200 close (a real,
independently-verified market price, just observed on a different real date)
is relabeled as A's spot on a constructed earlier `as_of`
(2026-04-25, inside the 30-day lookback of the real 2026-05-15 row), paired
with A's real buy_below/band levels reused unchanged. No spot, IV, buy_below,
or band level is invented -- only the (as_of, spot) attachment for the
"previous" snapshot is a test construct, disclosed per-test.

`implied_move_daily` (AVGO, real, frozen 2026-08-26 grid -- same fixture
already verified real in test_implied_move.py):

    Too-early expiry 2026-08-26 (same-day, extreme IV), strike 357.5:
        call_iv=13.1136232997271, put_iv=12.6423544768043
    Covering expiry 2026-09-04, strike 357.5:
        call_iv=0.736661443735852, put_iv=0.706997006724508
    spot=358.3500 for both (real, AVGO's 2026-08-26 underlying_spot).

    implied_move_pct is recomputed here via the SAME Brenner-Subrahmanyam
    formula/constant `implied_move_snapshot.py` uses (imported, not
    reproduced by hand), applied to these real, frozen IVs -- so both nights'
    pct values are genuine formula outputs over real quotes, not invented
    numbers. The two real expiries' IVs differ by roughly an order of
    magnitude, which is what produces a large, unambiguous shift.

`fundamental_statement_obs` (NVDA, real, frozen 2026-04-30 balance sheet --
same NVDA_BALANCE fixture already verified real in test_fundamental_obs.py,
imported rather than retyped so the two files cannot silently drift).

`fundamental_scores` / `fundamental_dimensions` -- these are Argon's OWN
derived research tables (an `as_of` here is a knowledge-quarter bucket id,
per storage/fundamental_scores.py, never a market observable), so per the
same accepted ruling their bucket dates and composite/dimension VALUES are
constructed test values, disclosed as such; no market price, IV, or anchor
figure appears in these rows.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from datetime import date, timedelta

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.fundamentals.features import FEATURES
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_dimensions import FundamentalDimensionsRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.implied_move import ImpliedMoveRepository
from uw_scan.storage.migrate_runner import apply_migrations
from uw_scan.storage.research_events import ResearchEventsRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.fundamental_change_events import (
    IMPLIED_MOVE_SHIFT_PP,
    derive_change_events,
)
from uw_scan.worker.jobs.implied_move_snapshot import BRENNER_SUBRAHMANYAM_CONSTANT
from uw_scan.worker.jobs.research_events_derive import (
    STALE_DAYS,
    register_discovery_gate,
)

_TEST_DB_NAME = "option_wizard_test_changeevents"

ENGINE = "test-v1:aaaaaaaa"

# Real, frozen ticker-A anchor row (see module docstring).
A_METHOD = "sales_to_ev"
A_BUY_BELOW = "129.833274501128"
A_OBSERVE_LOW = "144.043685789822"
A_OBSERVE_MID = "149.353852575318"
A_OBSERVE_HIGH = "156.783699803719"
A_RISK_ABOVE = "162.817745030498"
A_SPOT_IN_ZONE = "111.7"  # real 2026-05-15 spot: <= buy_below -> in zone
A_SPOT_OUT_OF_ZONE = "148.1200"  # real 2026-08-12 close: > buy_below
A_INPUTS_HASH = "7f8416c30695589169bc15c5d03f2079eade0c88a750f3c7858dd96b6656a7fe"
A_CONFIDENCE_REASONS = [
    "no sector on file for this name, so the band uses the pooled-universe "
    "default (revenue / enterprise value) rather than a method chosen for "
    "its business"
]


def _maint_settings() -> Settings:
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": "postgres"})


@pytest.fixture(scope="module")
def _change_events_settings() -> Iterator[Settings]:
    maint = _maint_settings()
    with psycopg.connect(maint.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB_NAME,)
            )
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')

    settings = maint.model_copy(update={"db_name": _TEST_DB_NAME})
    yield settings

    with psycopg.connect(maint.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}"')


@pytest.fixture
def conn(_change_events_settings: Settings) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_change_events_settings.db_dsn(), autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
        apply_migrations(admin, log=lambda _msg: None)

    connection = psycopg.connect(_change_events_settings.db_dsn())
    try:
        yield connection
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _register_engine(
    conn: psycopg.Connection, engine: str = ENGINE
) -> FundamentalScoresRepository:
    repo = FundamentalScoresRepository(conn, schema="uw_scan")
    repo.register_version(
        engine_version=engine,
        code_version="test-v1",
        param_hash=engine.split(":")[1],
        params=dict.fromkeys(FEATURES, 1.0),
        note="test",
    )
    repo.activate(engine)
    return repo


def _anchor_row(*, as_of: date, spot: str, inputs_hash: str) -> dict:
    return {
        "ticker": "A",
        "as_of": as_of,
        "engine_version": ENGINE,
        "inputs_hash": inputs_hash,
        "company_type": "unclassified",
        "method": A_METHOD,
        "buy_below": A_BUY_BELOW,
        "observe_low": A_OBSERVE_LOW,
        "observe_mid": A_OBSERVE_MID,
        "observe_high": A_OBSERVE_HIGH,
        "risk_above": A_RISK_ABOVE,
        "spot": spot,
        "spot_percentile": "1",
        "history_quarters": 20,
        "confidence": "medium",
        "confidence_reasons_jsonb": A_CONFIDENCE_REASONS,
        "inputs_jsonb": {},
        "source_obs_ids": [],
    }


def _score_row(*, ticker: str, as_of: date, engine: str = ENGINE, ihash: str) -> dict:
    return {
        "ticker": ticker,
        "as_of": as_of,
        "engine_version": engine,
        "inputs_hash": ihash,
        "period_end": as_of,
        "knowledge_date": as_of,
        "filing_date_known": True,
        "composite": 0.15,
        **dict.fromkeys(FEATURES, 0.1),
        "features_present": len(FEATURES),
        "source_obs_ids": [],
    }


def _seed_chain_member(conn: psycopg.Connection, ticker: str) -> None:
    taxonomy = ResearchTaxonomyRepository(conn, schema="uw_scan")
    version = "test-taxonomy-v1"
    taxonomy.publish_version(version, note="test", activate=True)
    taxonomy.define_chains(
        version,
        [
            {
                "domain": "test_domain",
                "chain": "test_chain",
                "layer": "L1",
                "layer_rank": 1,
                "description": "test",
            }
        ],
    )
    taxonomy.add_membership(
        version,
        chain="test_chain",
        layer="L1",
        ticker=ticker,
        evidence_class="analyst",
        approved_by="test-harness",
    )


def _nvda_statement_row(
    *, filing_published_at: date | None = date(2026, 5, 21)
) -> dict:
    """NVDA's real 2026-04-30 quarterly balance sheet, frozen -- the exact
    figures verified in tests/integration/storage/test_fundamental_obs.py."""
    raw = {
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
    payload = normalize(raw)
    return {
        "source": "uw",
        "ticker": "NVDA",
        "period_end": date(2026, 4, 30),
        "period_type": "quarterly",
        "statement": "balance",
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": filing_published_at,
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _avgo_implied_move_pair(conn: psycopg.Connection) -> None:
    """Two real, frozen AVGO IV quotes (2026-08-26 grid, verified in
    test_implied_move.py) run through the real Brenner-Subrahmanyam formula
    to produce two genuinely different implied_move_pct values ~45pp apart
    -- see the module docstring."""
    repo = ImpliedMoveRepository(conn, schema="uw_scan")
    spot = 358.3500
    report_date = date(2026, 9, 2)

    def _pct_usd(call_iv: float, put_iv: float, t_days: int) -> tuple[float, float]:
        atm_iv = (call_iv + put_iv) / 2
        pct = BRENNER_SUBRAHMANYAM_CONSTANT * atm_iv * math.sqrt(t_days / 365.0)
        return pct, pct * spot

    prior_pct, prior_usd = _pct_usd(13.1136232997271, 12.6423544768043, 1)
    today_pct, today_usd = _pct_usd(0.736661443735852, 0.706997006724508, 9)

    repo.upsert_rows(
        [
            {
                "ticker": "AVGO",
                "market_date": date(2026, 8, 25),
                "report_date": report_date,
                "expiry": date(2026, 8, 26),
                "strike": 357.5,
                "atm_iv": (13.1136232997271 + 12.6423544768043) / 2,
                "iv_basis": "both",
                "spot": spot,
                "implied_move_pct": prior_pct,
                "implied_move_usd": prior_usd,
            },
            {
                "ticker": "AVGO",
                "market_date": date(2026, 8, 26),
                "report_date": report_date,
                "expiry": date(2026, 9, 4),
                "strike": 357.5,
                "atm_iv": (0.736661443735852 + 0.706997006724508) / 2,
                "iv_basis": "both",
                "spot": spot,
                "implied_move_pct": today_pct,
                "implied_move_usd": today_usd,
            },
        ]
    )
    assert abs(today_pct - prior_pct) >= IMPLIED_MOVE_SHIFT_PP


# ---------------------------------------------------------------------------
# The registry production actually had
# ---------------------------------------------------------------------------


def test_the_job_seeds_the_class_registry_it_needs(conn):
    """The one test in this file that does NOT call `register_discovery_gate`.

    Every other test here calls it as setup, and that is exactly how this got
    to production broken: measured 2026-08-28 on the mini,
    `research_event_classes` held ZERO rows, because `register_discovery_gate`
    had no caller anywhere in the codebase — it appeared only in docstrings.
    So `record_events` refused every write, the typed ledger was inert, and
    the nightly job would raise `event classes not live: [...]` on its first
    real event. The suite was green throughout, because the FIXTURE supplied
    what the environment did not.

    This test therefore starts from prod's real state — a migrated schema with
    an unseeded registry — and asserts the job makes itself work.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.research_event_classes")
        assert cur.fetchone()[0] == 0, "the point of this test is an EMPTY registry"

    scores = _register_engine(conn)
    scores.insert_scores(
        [
            _score_row(ticker="PLTR", as_of=date(2026, 3, 31), ihash="h1"),
            _score_row(ticker="PLTR", as_of=date(2026, 6, 30), ihash="h2"),
        ]
    )

    result = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")

    # It wrote, rather than raising ValueError("event classes not live").
    assert result["bucket_flip"] == 1
    events = ResearchEventsRepository(conn, schema="uw_scan")
    assert len(events.events_for("PLTR")) == 1

    # And seeding is not a bypass of the discovery gate: the killed classes
    # come back KILLED and keep refusing writes. A seed that quietly turned
    # every class live would pass the assertions above and destroy the gate.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM uw_scan.research_event_classes"
            " WHERE event_class = 'restatement'"
        )
        assert cur.fetchone()[0] == "killed"


# ---------------------------------------------------------------------------
# Step 1: band_entry + implied_move_shift + bucket_flip, in one run + idempotency
# ---------------------------------------------------------------------------


def test_combined_run_emits_one_of_each_and_is_idempotent(conn):
    register_discovery_gate(conn, schema="uw_scan")
    _register_engine(conn)
    anchors = FundamentalAnchorsRepository(conn, schema="uw_scan")
    anchors.insert_anchors(
        [
            _anchor_row(
                as_of=date(2026, 4, 25), spot=A_SPOT_OUT_OF_ZONE, inputs_hash="h-prev"
            ),
            _anchor_row(
                as_of=date(2026, 5, 15),
                spot=A_SPOT_IN_ZONE,
                inputs_hash=A_INPUTS_HASH,
            ),
        ]
    )
    _avgo_implied_move_pair(conn)
    scores = _register_engine(conn)
    scores.insert_scores(
        [
            _score_row(ticker="PLTR", as_of=date(2026, 3, 31), ihash="h1"),
            _score_row(ticker="PLTR", as_of=date(2026, 6, 30), ihash="h2"),
        ]
    )

    result = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert result["band_entry"] == 1
    assert result["implied_move_shift"] == 1
    assert result["bucket_flip"] == 1

    events = ResearchEventsRepository(conn, schema="uw_scan")
    assert len(events.events_for("A")) == 1
    assert events.events_for("A")[0]["event_class"] == "band_entry"
    assert len(events.events_for("AVGO")) == 1
    assert len(events.events_for("PLTR")) == 1

    # I3: `implied_move_shift`'s detail must carry both nights' covering
    # expiry/atm_iv/iv_basis, not just the pct — `_avgo_implied_move_pair`
    # seeds a genuine covering-expiry CHANGE (2026-08-26 -> 2026-09-04)
    # alongside the IV move, and a reader of the event ledger must be able
    # to tell the two apart without re-querying `implied_move_daily`.
    avgo_detail = events.events_for("AVGO")[0]["detail_jsonb"]
    assert avgo_detail["expiry"] == "2026-09-04"
    assert avgo_detail["prev_expiry"] == "2026-08-26"
    assert avgo_detail["iv_basis"] == "both"
    assert avgo_detail["prev_iv_basis"] == "both"
    assert avgo_detail["atm_iv"] == pytest.approx(
        (0.736661443735852 + 0.706997006724508) / 2
    )
    assert avgo_detail["prev_atm_iv"] == pytest.approx(
        (13.1136232997271 + 12.6423544768043) / 2
    )

    rerun = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert rerun == {
        "band_entry": 0,
        "band_exit": 0,
        "implied_move_shift": 0,
        "coverage_change": 0,
        "bucket_flip": 0,
    }


# ---------------------------------------------------------------------------
# band_entry
# ---------------------------------------------------------------------------


def test_band_entry_emits_nothing_when_entered_is_none(conn):
    """A single anchor snapshot with no prior row in the 30-day lookback ->
    `in_buy_zone` reports `entered=None`. NULL is not NEW: this must emit
    zero band_entry events, not one."""
    register_discovery_gate(conn, schema="uw_scan")
    _register_engine(conn)
    FundamentalAnchorsRepository(conn, schema="uw_scan").insert_anchors(
        [
            _anchor_row(
                as_of=date(2026, 5, 15), spot=A_SPOT_IN_ZONE, inputs_hash=A_INPUTS_HASH
            )
        ]
    )

    result = derive_change_events(conn, as_of=date(2026, 5, 15), schema="uw_scan")
    assert result["band_entry"] == 0
    assert ResearchEventsRepository(conn, schema="uw_scan").events_for("A") == []


# ---------------------------------------------------------------------------
# band_exit
# ---------------------------------------------------------------------------


def test_band_exit_fires_when_zone_is_left_and_is_idempotent(conn):
    register_discovery_gate(conn, schema="uw_scan")
    _register_engine(conn)
    FundamentalAnchorsRepository(conn, schema="uw_scan").insert_anchors(
        [
            # In zone on the earlier date (real row, unmodified).
            _anchor_row(
                as_of=date(2026, 5, 15), spot=A_SPOT_IN_ZONE, inputs_hash=A_INPUTS_HASH
            ),
            # Left the zone on a later date within the lookback (constructed
            # pairing: A's real 2026-08-12 close relabeled here).
            _anchor_row(
                as_of=date(2026, 6, 1), spot=A_SPOT_OUT_OF_ZONE, inputs_hash="h-exit"
            ),
        ]
    )

    result = derive_change_events(conn, as_of=date(2026, 6, 1), schema="uw_scan")
    assert result["band_exit"] == 1
    assert result["band_entry"] == 0

    events = [
        e
        for e in ResearchEventsRepository(conn, schema="uw_scan").events_for("A")
        if e["event_class"] == "band_exit"
    ]
    assert len(events) == 1
    assert events[0]["occurred_at"] == date(2026, 6, 1)

    rerun = derive_change_events(conn, as_of=date(2026, 6, 1), schema="uw_scan")
    assert rerun["band_exit"] == 0


def test_band_exit_emits_nothing_when_never_in_zone(conn):
    """Out of zone at BOTH snapshots -> never entered, so leaving is not
    possible either. Zero band_exit events, not a false exit."""
    register_discovery_gate(conn, schema="uw_scan")
    _register_engine(conn)
    FundamentalAnchorsRepository(conn, schema="uw_scan").insert_anchors(
        [
            _anchor_row(
                as_of=date(2026, 4, 25), spot=A_SPOT_OUT_OF_ZONE, inputs_hash="h1"
            ),
            _anchor_row(
                as_of=date(2026, 5, 15), spot=A_SPOT_OUT_OF_ZONE, inputs_hash="h2"
            ),
        ]
    )
    result = derive_change_events(conn, as_of=date(2026, 5, 15), schema="uw_scan")
    assert result["band_exit"] == 0
    assert result["band_entry"] == 0


def test_band_exit_emits_nothing_when_still_in_zone(conn):
    """In zone at BOTH snapshots -> nothing was left. This is the
    discriminating case for the `AND NOT in_zone` half of the exit
    condition: a mutant that dropped it would fire a band_exit for every
    ticker that was EVER in zone, whether or not it left."""
    register_discovery_gate(conn, schema="uw_scan")
    _register_engine(conn)
    FundamentalAnchorsRepository(conn, schema="uw_scan").insert_anchors(
        [
            _anchor_row(as_of=date(2026, 4, 25), spot=A_SPOT_IN_ZONE, inputs_hash="h1"),
            _anchor_row(
                as_of=date(2026, 5, 15), spot=A_SPOT_IN_ZONE, inputs_hash=A_INPUTS_HASH
            ),
        ]
    )
    result = derive_change_events(conn, as_of=date(2026, 5, 15), schema="uw_scan")
    assert result["band_exit"] == 0


# ---------------------------------------------------------------------------
# implied_move_shift
# ---------------------------------------------------------------------------


def test_implied_move_shift_exact_boundary_fires(conn):
    """Sharpest possible test of the `>=` in the shift comparison: shift ==
    IMPLIED_MOVE_SHIFT_PP exactly (0.10 -> 0.11). A `>` mutant would miss
    this. Strike/spot/atm_iv are AVGO's real frozen values (see module
    docstring); the pct pair is a deliberately chosen boundary construction,
    disclosed here rather than derived from the real IVs (which do not
    naturally land on an exact 1.00pp gap)."""
    register_discovery_gate(conn, schema="uw_scan")
    repo = ImpliedMoveRepository(conn, schema="uw_scan")
    report_date = date(2026, 9, 2)
    repo.upsert_rows(
        [
            {
                "ticker": "AVGO",
                "market_date": date(2026, 8, 25),
                "report_date": report_date,
                "expiry": date(2026, 9, 4),
                "strike": 357.5,
                "atm_iv": 0.7218,
                "iv_basis": "both",
                "spot": 358.3500,
                "implied_move_pct": 0.10,
                "implied_move_usd": 0.10 * 358.3500,
            },
            {
                "ticker": "AVGO",
                "market_date": date(2026, 8, 26),
                "report_date": report_date,
                "expiry": date(2026, 9, 4),
                "strike": 357.5,
                "atm_iv": 0.7218,
                "iv_basis": "both",
                "spot": 358.3500,
                "implied_move_pct": 0.11,
                "implied_move_usd": 0.11 * 358.3500,
            },
        ]
    )
    result = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert result["implied_move_shift"] == 1


def test_implied_move_shift_just_under_threshold_emits_nothing(conn):
    register_discovery_gate(conn, schema="uw_scan")
    repo = ImpliedMoveRepository(conn, schema="uw_scan")
    report_date = date(2026, 9, 2)
    repo.upsert_rows(
        [
            {
                "ticker": "AVGO",
                "market_date": date(2026, 8, 25),
                "report_date": report_date,
                "expiry": date(2026, 9, 4),
                "strike": 357.5,
                "atm_iv": 0.7218,
                "iv_basis": "both",
                "spot": 358.3500,
                "implied_move_pct": 0.10,
                "implied_move_usd": 0.10 * 358.3500,
            },
            {
                "ticker": "AVGO",
                "market_date": date(2026, 8, 26),
                "report_date": report_date,
                "expiry": date(2026, 9, 4),
                "strike": 357.5,
                "atm_iv": 0.7218,
                "iv_basis": "both",
                "spot": 358.3500,
                "implied_move_pct": 0.1099,
                "implied_move_usd": 0.1099 * 358.3500,
            },
        ]
    )
    result = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert result["implied_move_shift"] == 0


# ---------------------------------------------------------------------------
# coverage_change
# ---------------------------------------------------------------------------


def test_coverage_change_gained_first_statement_and_is_idempotent(conn):
    register_discovery_gate(conn, schema="uw_scan")
    _seed_chain_member(conn, "NVDA")
    FundamentalObsRepository(conn, schema="uw_scan").record_statements(
        [_nvda_statement_row()]
    )

    as_of = date(2026, 8, 26)
    result = derive_change_events(conn, as_of=as_of, schema="uw_scan")
    assert result["coverage_change"] == 1

    events = [
        e
        for e in ResearchEventsRepository(conn, schema="uw_scan").events_for("NVDA")
        if e["event_class"] == "coverage_change"
    ]
    assert len(events) == 1
    assert events[0]["detail_jsonb"]["direction"] == "gained_coverage"
    assert events[0]["occurred_at"] == date(2026, 5, 21)  # filing_published_at
    assert events[0]["first_known_at"] >= events[0]["occurred_at"]

    rerun = derive_change_events(conn, as_of=as_of, schema="uw_scan")
    assert rerun["coverage_change"] == 0


def test_coverage_change_gained_coverage_needs_no_filing_date(conn):
    """A statement with no filing_published_at falls back to
    first_observed_at's own date for BOTH clocks, not a crash."""
    register_discovery_gate(conn, schema="uw_scan")
    _seed_chain_member(conn, "NVDA")
    FundamentalObsRepository(conn, schema="uw_scan").record_statements(
        [_nvda_statement_row(filing_published_at=None)]
    )
    result = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert result["coverage_change"] == 1


def test_coverage_change_ignores_non_chain_member_tickers(conn):
    """A statement for a ticker NOT in any chain is not chain-scoped
    coverage -- must emit nothing (coverage_change is deliberately scoped to
    chain members only, per the module docstring)."""
    register_discovery_gate(conn, schema="uw_scan")
    FundamentalObsRepository(conn, schema="uw_scan").record_statements(
        [_nvda_statement_row()]
    )
    result = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert result["coverage_change"] == 0


def test_discovery_gate_coverage_change_count_scopes_to_the_active_taxonomy_version(
    conn,
):
    """M7 — `register_discovery_gate`'s own `coverage_change_tickers` count
    must be scoped to the ACTIVE taxonomy version, matching
    `_chain_member_tickers` (`fundamental_change_events.py`). A member
    registered under a taxonomy version that was never activated must not
    inflate the gate's `measured_rows` — a gate whose entire purpose is
    that its numbers are honest cannot over-count relative to what the
    class can actually fire on."""
    taxonomy = ResearchTaxonomyRepository(conn, schema="uw_scan")
    taxonomy.publish_version("v-inactive", note="never activated", activate=False)
    taxonomy.define_chains(
        "v-inactive",
        [
            {
                "domain": "test_domain",
                "chain": "test_chain",
                "layer": "L1",
                "layer_rank": 1,
                "description": "test",
            }
        ],
    )
    taxonomy.add_membership(
        "v-inactive",
        chain="test_chain",
        layer="L1",
        ticker="NVDA",
        evidence_class="analyst",
        approved_by="test",
    )
    FundamentalObsRepository(conn, schema="uw_scan").record_statements(
        [_nvda_statement_row()]
    )
    # No taxonomy version is active at all — the gate must count zero.
    assert taxonomy.active_version() is None

    counts = register_discovery_gate(conn, schema="uw_scan")
    coverage_change_class = next(
        c
        for c in ResearchEventsRepository(conn, schema="uw_scan").classes()
        if c["event_class"] == "coverage_change"
    )
    assert coverage_change_class["measured_rows"] == 0
    assert counts["coverage_change_tickers"] == 0


def test_coverage_change_ignores_a_retired_chain_member(conn):
    """M3 — the hollow test the branch review found: `_chain_member_tickers`
    scopes to `valid_to IS NULL`, but no fixture ever retired a membership to
    prove the predicate does anything. Retire NVDA's membership BEFORE it
    gets its first statement -- a retired member must not re-enter the
    `coverage_change` candidate set, or a name the desk has explicitly
    dropped from a chain would silently keep generating chain-scoped events
    for it."""
    register_discovery_gate(conn, schema="uw_scan")
    _seed_chain_member(conn, "NVDA")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE uw_scan.chain_membership
                  SET valid_to = now()
                WHERE ticker = 'NVDA' AND valid_to IS NULL"""
        )
    conn.commit()
    FundamentalObsRepository(conn, schema="uw_scan").record_statements(
        [_nvda_statement_row()]
    )

    result = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert result["coverage_change"] == 0


def test_coverage_change_went_stale_boundary(conn):
    """age == STALE_DAYS exactly must NOT fire; age == STALE_DAYS + 1 must."""
    register_discovery_gate(conn, schema="uw_scan")
    _seed_chain_member(conn, "MSFT")
    scores = _register_engine(conn)
    old_as_of = date(2025, 1, 1)
    row = _score_row(ticker="MSFT", as_of=old_as_of, ihash="h-stale")
    scores.insert_scores([row])
    result_id = scores.result_ids([row])[("MSFT", old_as_of)]
    FundamentalDimensionsRepository(conn, schema="uw_scan").record(
        [
            {
                "result_id": result_id,
                "ticker": "MSFT",
                "as_of": old_as_of,
                "engine_version": ENGINE,
                "dimension": "growth",
                "value": "0.1",
                "inputs_present": 1,
                "inputs_expected": 1,
                "authority": "descriptive",
            }
        ]
    )

    at_boundary = old_as_of + timedelta(days=STALE_DAYS)
    assert (
        derive_change_events(conn, as_of=at_boundary, schema="uw_scan")[
            "coverage_change"
        ]
        == 0
    )

    just_past = old_as_of + timedelta(days=STALE_DAYS + 1)
    result = derive_change_events(conn, as_of=just_past, schema="uw_scan")
    assert result["coverage_change"] == 1

    events = [
        e
        for e in ResearchEventsRepository(conn, schema="uw_scan").events_for("MSFT")
        if e["event_class"] == "coverage_change"
    ]
    assert len(events) == 1
    assert events[0]["detail_jsonb"]["direction"] == "went_stale"
    assert events[0]["occurred_at"] == old_as_of

    rerun = derive_change_events(conn, as_of=just_past, schema="uw_scan")
    assert rerun["coverage_change"] == 0


def test_coverage_change_went_stale_is_idempotent_at_a_later_as_of(conn):
    """Fix round 1, I3: the boundary test above only reran at the SAME
    as_of. This proves the property the docstring actually claims -- a
    rerun at a LATER as_of, with the underlying stale result unchanged, is
    still a no-op (not merely "the identical night is a no-op"). A
    source_ref keyed on the run clock instead of the result's own as_of
    would double-write here."""
    register_discovery_gate(conn, schema="uw_scan")
    _seed_chain_member(conn, "MSFT")
    scores = _register_engine(conn)
    old_as_of = date(2025, 1, 1)
    row = _score_row(ticker="MSFT", as_of=old_as_of, ihash="h-stale2")
    scores.insert_scores([row])
    result_id = scores.result_ids([row])[("MSFT", old_as_of)]
    FundamentalDimensionsRepository(conn, schema="uw_scan").record(
        [
            {
                "result_id": result_id,
                "ticker": "MSFT",
                "as_of": old_as_of,
                "engine_version": ENGINE,
                "dimension": "growth",
                "value": "0.1",
                "inputs_present": 1,
                "inputs_expected": 1,
                "authority": "descriptive",
            }
        ]
    )

    just_past = old_as_of + timedelta(days=STALE_DAYS + 1)
    first = derive_change_events(conn, as_of=just_past, schema="uw_scan")
    assert first["coverage_change"] == 1

    much_later = just_past + timedelta(days=30)
    rerun = derive_change_events(conn, as_of=much_later, schema="uw_scan")
    assert rerun["coverage_change"] == 0


def test_coverage_change_gained_coverage_survives_a_late_filing_date_backfill(conn):
    """M1 regression: `record_statements`' COALESCE fills a previously-NULL
    `filing_published_at` on a later re-pull (CLAUDE.md documents this
    happening for real), which changes what `occurred` would recompute to
    while the ticker still has exactly one statement. Once gained_coverage
    has fired for a ticker, it must never fire again for it -- regardless of
    any later `occurred_at` drift."""
    register_discovery_gate(conn, schema="uw_scan")
    _seed_chain_member(conn, "NVDA")
    obs = FundamentalObsRepository(conn, schema="uw_scan")
    obs.record_statements([_nvda_statement_row(filing_published_at=None)])

    first = derive_change_events(conn, as_of=date(2026, 8, 26), schema="uw_scan")
    assert first["coverage_change"] == 1

    # Late back-fill of the real filing date, same content_hash (payload is
    # unchanged) -- occurred_at would recompute to an EARLIER date on a
    # re-derive if this class trusted it as identity.
    obs.record_statements([_nvda_statement_row()])
    rerun = derive_change_events(conn, as_of=date(2026, 8, 27), schema="uw_scan")
    assert rerun["coverage_change"] == 0

    events = [
        e
        for e in ResearchEventsRepository(conn, schema="uw_scan").events_for("NVDA")
        if e["event_class"] == "coverage_change"
    ]
    assert len(events) == 1


# ---------------------------------------------------------------------------
# bucket_flip
# ---------------------------------------------------------------------------


def test_bucket_flip_first_appearance_is_not_a_flip(conn):
    """A ticker's very first bucket has nothing to have moved FROM -- must
    emit zero bucket_flip events, however new the bucket is."""
    register_discovery_gate(conn, schema="uw_scan")
    _register_engine(conn)
    FundamentalScoresRepository(conn, schema="uw_scan").insert_scores(
        [_score_row(ticker="PLTR", as_of=date(2026, 6, 30), ihash="h1")]
    )
    result = derive_change_events(conn, as_of=date(2026, 7, 1), schema="uw_scan")
    assert result["bucket_flip"] == 0


def test_bucket_flip_fires_only_for_a_strictly_newer_bucket(conn):
    """Three buckets seeded in one run: the middle-to-newest transition is
    the only genuine flip (PLTR's second bucket already flipped it once; a
    THIRD, even-newer bucket must flip it again with a NEW source_ref, not
    collide with the first flip's identity)."""
    register_discovery_gate(conn, schema="uw_scan")
    scores = _register_engine(conn)
    scores.insert_scores(
        [
            _score_row(ticker="PLTR", as_of=date(2026, 3, 31), ihash="h1"),
            _score_row(ticker="PLTR", as_of=date(2026, 6, 30), ihash="h2"),
        ]
    )
    first = derive_change_events(conn, as_of=date(2026, 7, 1), schema="uw_scan")
    assert first["bucket_flip"] == 1

    scores.insert_scores(
        [_score_row(ticker="PLTR", as_of=date(2026, 9, 30), ihash="h3")]
    )
    second = derive_change_events(conn, as_of=date(2026, 10, 1), schema="uw_scan")
    assert second["bucket_flip"] == 1

    events = [
        e
        for e in ResearchEventsRepository(conn, schema="uw_scan").events_for("PLTR")
        if e["event_class"] == "bucket_flip"
    ]
    assert {e["occurred_at"] for e in events} == {date(2026, 6, 30), date(2026, 9, 30)}


def test_bucket_flip_first_known_at_never_precedes_occurred_at(conn):
    """I1 regression: without a max() guard, a run whose `as_of` precedes
    the flip's own `occurred_at` (the newest bucket's date) raised
    `CheckViolation: research_events_known_after_occurred`. Reviewer probe
    reproduced verbatim: PLTR buckets 2026-03-31/2026-06-30, derive
    `as_of=2026-05-01` -- strictly BEFORE the newest bucket. This is not
    theoretical: the committed runner accepts any `--as-of`, and migration
    129 records 371 real prod rows landing with a FUTURE `as_of` relative to
    the night they were computed."""
    register_discovery_gate(conn, schema="uw_scan")
    scores = _register_engine(conn)
    scores.insert_scores(
        [
            _score_row(ticker="PLTR", as_of=date(2026, 3, 31), ihash="h1"),
            _score_row(ticker="PLTR", as_of=date(2026, 6, 30), ihash="h2"),
        ]
    )
    result = derive_change_events(conn, as_of=date(2026, 5, 1), schema="uw_scan")
    assert result["bucket_flip"] == 1

    events = [
        e
        for e in ResearchEventsRepository(conn, schema="uw_scan").events_for("PLTR")
        if e["event_class"] == "bucket_flip"
    ]
    assert events[0]["occurred_at"] == date(2026, 6, 30)
    # max(newest_as_of, as_of) clamps first_known_at UP to occurred_at
    # rather than raising the CHECK.
    assert events[0]["first_known_at"] == date(2026, 6, 30)


def test_bucket_flip_scoped_to_active_engine_does_not_collide(conn):
    """I2 regression: two engine versions sharing an identical newest
    `as_of` for one ticker used to emit two candidate rows colliding on the
    same `(event_class, ticker, occurred_at, source_ref)` tuple -- one
    silently discarded by `ON CONFLICT DO NOTHING`, with whichever engine's
    `detail_jsonb.engine_version` survived being an accident of cursor
    order. Scoping the query to `active_version()` removes the retired
    engine from consideration entirely, so only ONE event is even
    candidate, and it is unambiguously the active engine's."""
    register_discovery_gate(conn, schema="uw_scan")
    scores = FundamentalScoresRepository(conn, schema="uw_scan")
    retired = "test-v0:bbbbbbbb"
    scores.register_version(
        engine_version=retired,
        code_version="test-v0",
        param_hash="bbbbbbbb",
        params=dict.fromkeys(FEATURES, 1.0),
        note="retired, never activated",
    )
    scores.insert_scores(
        [
            _score_row(
                ticker="IBM", as_of=date(2026, 3, 31), engine=retired, ihash="o1"
            ),
            _score_row(
                ticker="IBM", as_of=date(2026, 6, 30), engine=retired, ihash="o2"
            ),
        ]
    )
    _register_engine(conn)  # registers + activates ENGINE
    scores.insert_scores(
        [
            _score_row(ticker="IBM", as_of=date(2026, 3, 31), ihash="e1"),
            _score_row(ticker="IBM", as_of=date(2026, 6, 30), ihash="e2"),
        ]
    )

    result = derive_change_events(conn, as_of=date(2026, 7, 1), schema="uw_scan")
    assert result["bucket_flip"] == 1  # not 2 -- the retired engine never contributes

    events = [
        e
        for e in ResearchEventsRepository(conn, schema="uw_scan").events_for("IBM")
        if e["event_class"] == "bucket_flip"
    ]
    assert len(events) == 1
    assert events[0]["detail_jsonb"]["engine_version"] == ENGINE
    assert events[0]["source_ref"] == f"IBM:2026-06-30:{ENGINE}"


def test_bucket_flip_is_idempotent_at_a_later_as_of(conn):
    """I3: a rerun at a LATER as_of (not the same night) with no new bucket
    must still write zero -- the property `test_bucket_flip_fires_only_
    for_a_strictly_newer_bucket` never isolated on its own, since its second
    run also introduced a genuinely new bucket."""
    register_discovery_gate(conn, schema="uw_scan")
    scores = _register_engine(conn)
    scores.insert_scores(
        [
            _score_row(ticker="ORCL", as_of=date(2026, 3, 31), ihash="orcl1"),
            _score_row(ticker="ORCL", as_of=date(2026, 6, 30), ihash="orcl2"),
        ]
    )
    first = derive_change_events(conn, as_of=date(2026, 7, 1), schema="uw_scan")
    assert first["bucket_flip"] == 1

    rerun = derive_change_events(conn, as_of=date(2026, 8, 15), schema="uw_scan")
    assert rerun["bucket_flip"] == 0


# ---------------------------------------------------------------------------
# The discovery gate must still hold
# ---------------------------------------------------------------------------


def test_the_gate_binds_the_five_new_classes_with_an_explicit_status(conn):
    """The five new classes are subject to the discovery gate, not exempt from it.

    THIS TEST'S PREMISE CHANGED, deliberately. It used to assert that
    `derive_change_events` RAISES when `register_discovery_gate` has not been
    run by hand. That property was real, but its cost was found in production:
    nothing called `register_discovery_gate` anywhere, `research_event_classes`
    held zero rows on the mini, and so the nightly job was not "correctly
    refusing" — it was permanently dead, and the desk's delta rail rendered
    the refusal as "Argon learned nothing new".

    The job now seeds the registry itself. What the gate actually guarantees —
    that a class nobody registered cannot write — is unchanged and is pinned by
    `test_gate_refuses_a_class_it_never_registered` below, which still raises.
    What this test now pins is the other half: each of the five carries an
    EXPLICIT recorded verdict rather than being waved through.
    """
    _register_engine(conn)
    FundamentalAnchorsRepository(conn, schema="uw_scan").insert_anchors(
        [
            _anchor_row(
                as_of=date(2026, 4, 25), spot=A_SPOT_OUT_OF_ZONE, inputs_hash="h-prev"
            ),
            _anchor_row(
                as_of=date(2026, 5, 15), spot=A_SPOT_IN_ZONE, inputs_hash=A_INPUTS_HASH
            ),
        ]
    )
    derive_change_events(conn, as_of=date(2026, 5, 15), schema="uw_scan")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_class, status FROM uw_scan.research_event_classes"
            " WHERE event_class = ANY(%s)",
            (
                [
                    "band_entry",
                    "band_exit",
                    "implied_move_shift",
                    "coverage_change",
                    "bucket_flip",
                ],
            ),
        )
        verdicts = dict(cur.fetchall())
    # All five present, each with a status the gate recorded on purpose.
    assert len(verdicts) == 5, verdicts
    assert set(verdicts.values()) <= {"live", "killed"}


def test_gate_refuses_a_class_it_never_registered(conn):
    register_discovery_gate(conn, schema="uw_scan")
    repo = ResearchEventsRepository(conn, schema="uw_scan")
    with pytest.raises(ValueError, match="not live"):
        repo.record_events(
            [
                {
                    "event_class": "not_a_real_class",
                    "ticker": "NVDA",
                    "occurred_at": date(2026, 1, 1),
                    "title": "should never write",
                    "source_kind": "test",
                }
            ]
        )
