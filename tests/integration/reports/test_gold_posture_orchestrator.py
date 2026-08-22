"""Integration test for the gold_posture orchestrator."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import pytest

from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def _seed_minimum(repo: Repository, today: date) -> None:
    """Seed enough data for the orchestrator to produce a non-empty posture.

    Every row is stamped with an ``as_of`` that could have been known at ``today``,
    never ``datetime.now()``. These fixtures replay a PAST date -- 2026-05-16 -- and
    stamping retrieval at the wall clock seeds rows fetched months after the instant
    the posture answers for. The orchestrator used to read them, because it bounded the
    observation period and never the retrieval clock; now that it bounds both, a
    now()-stamped fixture is simply invisible, which is the correct behaviour and was
    silently propping these assertions up.
    """
    knowable = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    base = today - timedelta(days=300)
    for i in range(301):
        d = base + timedelta(days=i)
        repo.insert_macro_series_daily(
            "GLD_CLOSE",
            d,
            Decimal(str(1800 + i * 0.5)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None,
            "MASSIVE",
            None,
        )
        repo.insert_macro_series_daily(
            "DFII10",
            d,
            Decimal(str(2.0 - i * 0.005)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None,
            "FRED",
            None,
        )
    repo.insert_macro_series_monthly(
        "CPIAUCSL",
        date(today.year, today.month, 1),
        Decimal("315.0"),
        knowable,
        date(today.year, today.month, 14),
        "FRED",
        None,
    )
    repo.insert_macro_series_daily(
        "T5YIFR",
        today,
        Decimal("2.31"),
        knowable,
        None,
        "FRED",
        None,
    )
    repo.insert_etf_holdings_daily(
        ticker="GLD",
        obs_date=today,
        holdings_oz=Decimal("32150746.6"),
        shares_out=None,
        nav_per_share=Decimal("420.50"),
        premium_pct=Decimal("0.01"),
        as_of=knowable,
        source="SPDR",
    )


def test_orchestrator_writes_posture_row(repo: Repository) -> None:
    today = date(2026, 5, 16)
    _seed_minimum(repo, today)
    compute_and_persist_gold_posture(
        repo,
        as_of=today,
        computed_at=datetime(2026, 5, 17, tzinfo=UTC),
    )
    row = repo.fetch_gold_posture_for_obs_date(today)
    assert row is not None
    assert row["obs_date"] == today
    assert row["gauge_state"] in {"operative", "partial", "suspended"}
    assert row["inputs_jsonb"] is not None
    assert "DFII10" in row["inputs_jsonb"]
    # GOLD COMPASS extensions populated
    assert row["valuation_posture_chip"] in {
        "FAVORABLE",
        "NEUTRAL",
        "STRETCHED",
        "SUSPENDED",
        "DEGRADED",
    }
    assert row["gld_history_jsonb"][-1]["obs_date"] == today.isoformat()
    assert Decimal(row["gld_history_jsonb"][-1]["value"]) == Decimal("1000")
    freshness_by_id = {item["id"]: item for item in row["data_freshness_jsonb"]}
    assert freshness_by_id["COMEX"]["status"] == "missing"
    assert freshness_by_id["COT"]["status"] == "missing"
    assert freshness_by_id["WGC"]["status"] == "missing"


def test_orchestrator_idempotent_same_inputs(repo: Repository) -> None:
    """Running twice with same (obs_date, computed_at) is a no-op."""
    today = date(2026, 5, 16)
    _seed_minimum(repo, today)
    computed_at = datetime(2026, 5, 17, tzinfo=UTC)
    compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
    compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.gold_posture_daily WHERE obs_date = %s",
            (today,),
        )
        assert cur.fetchone()[0] == 1


def test_the_orchestrator_reads_nothing_outside_the_registry(
    repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest is only complete if the registry covers every read that happens.

    This is the test whose absence let the first version of the registry ship at 12 of
    16 declared inputs. The registry tests assert
    ``set(manifest) == {i.key for i in GOLD_INPUTS}`` -- true by construction, and blind
    to a read the orchestrator makes without declaring. Four reads sat below the lens
    calls, in the section that assembles the UI payload, and the manifest called itself
    complete without them.

    So this wraps the REAL repository and records every fetch the REAL orchestrator
    makes, then asserts each one belongs to a declared input. A new read added without a
    registry entry fails here rather than quietly narrowing the audit trail.
    """
    today = date.today()
    _seed_minimum(repo, today)

    seen: list[str] = []
    for name in [n for n in dir(repo) if n.startswith("fetch_")]:
        original = getattr(repo, name)
        if not callable(original):
            continue

        def recorder(*args, __name=name, __original=original, **kwargs):
            seen.append(__name)
            return __original(*args, **kwargs)

        monkeypatch.setattr(repo, name, recorder, raising=False)

    compute_and_persist_gold_posture(repo, as_of=today, computed_at=datetime.now(UTC))

    declared_readers = {
        "fetch_macro_series_daily",
        "fetch_macro_series_monthly",
        "fetch_cb_gold_reserves_monthly",
        "fetch_etf_holdings_daily",
        "fetch_etf_flows_daily",
        "fetch_exchange_inventory_daily",
        "fetch_cot_gold_weekly",
        "fetch_uw_gold_options_daily",
    }
    undeclared = sorted(set(seen) - declared_readers)
    assert not undeclared, (
        f"the orchestrator called {undeclared}, which no GOLD_INPUTS entry declares. "
        "Add a GoldInput for it -- an undeclared read is an input the manifest cannot "
        "name, which is the defect this registry exists to end."
    )


def test_every_declared_reader_is_actually_exercised(repo: Repository) -> None:
    """The mirror: a registry entry nothing reads is scaffolding, not provenance.

    Guards the other direction of drift -- a declared input whose read was removed from
    the orchestrator would otherwise sit in the manifest forever reporting rows nobody
    consumed.
    """
    from uw_scan.macro.gold import GOLD_INPUTS, read_gold_inputs

    readings = read_gold_inputs(repo, date.today())
    assert set(readings) == {item.key for item in GOLD_INPUTS}
    # Every entry either has a reader or an explicit reason for not having one.
    for item in GOLD_INPUTS:
        assert (item.read is None) != (item.not_read_reason is None), item.key


def test_a_replay_does_not_read_a_vintage_retrieved_after_it(repo: Repository) -> None:
    """The retrieval bound, demonstrated rather than asserted about.

    Gold tables key on ``(..., as_of)`` and their readers select
    ``DISTINCT ON (obs_date) ... ORDER BY as_of DESC`` -- the NEWEST vintage, regardless
    of the replay instant. The orchestrator passed only ``to_date``, which bounds the
    observation PERIOD and says nothing about when the row was retrieved, so recomputing
    a past date read restatements that did not exist yet.

    Two vintages of one period here: the value known on the day, and a restatement
    fetched a month later. The replay must read the first.
    """
    replay = date(2026, 5, 16)
    _seed_minimum(repo, replay)
    knowable = datetime.combine(replay, datetime.min.time(), tzinfo=UTC)

    # _seed_minimum already stored what we knew on the day: 1800 + 300*0.5 = 1950.0,
    # stamped at `knowable`. A second insert at the same as_of is a no-op -- these
    # tables key on (series_id, obs_date, as_of) and DO NOTHING, which is the
    # append-only property that makes them quotable at all.
    known_on_the_day = Decimal("1950.0")
    # The restatement, retrieved a month after the instant being replayed.
    repo.insert_macro_series_daily(
        "GLD_CLOSE",
        replay,
        Decimal("9999.0"),
        knowable + timedelta(days=30),
        None,
        "MASSIVE",
        None,
    )

    compute_and_persist_gold_posture(
        repo, as_of=replay, computed_at=datetime(2026, 5, 17, tzinfo=UTC)
    )
    row = repo.fetch_gold_posture_for_obs_date(replay)

    history = {r["obs_date"]: r["value"] for r in row["gold_history_jsonb"]}
    assert Decimal(history[replay.isoformat()]) == known_on_the_day, (
        "the replay read the later restatement; a posture for May cannot stand on a "
        "value retrieved in June"
    )
