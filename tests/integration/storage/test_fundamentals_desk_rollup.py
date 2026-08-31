"""Nightly desk matrix rollup (Task 12, spec §3c): per-name revenue YoY and
gross-margin trajectory, persisted from the UW statement store.

Reuses the SAME frozen NVDA ten-quarter fixture `test_feature_details.py`
built for `build_features` -- real figures, frozen 2026-08-12 from
`uw_scan.fundamental_statement_obs` -- rather than inventing a second copy.
Ten quarters, not fewer: `rev_growth` needs a TTM window compared against the
TTM window ending four quarters earlier, so the newest quarter is the first
with enough history to produce a number at all.

The DB-persisted rollup is checked against an INDEPENDENT call to
`build_features` over the panel actually read back from Postgres -- not a
hand-recomputed ratio -- so the test pins the job's plumbing (DB round-trip,
period keying, per-period violation suppression) without re-deriving math
`test_feature_details.py` already owns.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.unit.fundamentals.test_feature_details import _BS, _CF, _INC, _RAW
from uw_scan.fundamentals.features import FALLBACK_LAG_DAYS, build_features
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_panels import current_statement_panel
from uw_scan.storage.fundamentals_desk import FundamentalsDeskRepository
from uw_scan.worker.jobs.fundamentals_desk_rollup import fundamentals_desk_rollup

NEWEST_PERIOD = _RAW[-1][0]  # "2026-04-30"
OLDEST_PERIOD = _RAW[0][0]  # "2024-01-31"
# NVDA's real filing date for the 2026-04-30 10-Q (same frozen fact
# `test_fundamental_obs.py`'s NVDA_BALANCE fixture carries).
NEWEST_FILING_DATE = date(2026, 5, 21)


def _obs_repo(seeded) -> FundamentalObsRepository:
    return FundamentalObsRepository(seeded.conn, schema=seeded._schema)


def _desk_repo(seeded) -> FundamentalsDeskRepository:
    return FundamentalsDeskRepository(seeded.conn, schema=seeded._schema)


def _stmt_row(period: str, statement: str, raw: dict, *, filing_published_at=None):
    payload = normalize(
        {
            **raw,
            "ticker": "NVDA",
            "fiscal_date_ending": period,
            "report_type": "quarterly",
        }
    )
    return {
        "source": "uw",
        "ticker": "NVDA",
        "period_end": date.fromisoformat(period),
        "period_type": "quarterly",
        "statement": statement,
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": filing_published_at,
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _seed_nvda(seeded, *, corrupt_newest_gross_profit: bool = False) -> None:
    """Ten real NVDA quarters (income/balance/cash-flow). Only the newest
    quarter carries a real filing date -- the rest exercise the
    `FALLBACK_LAG_DAYS` knowledge-date fallback deliberately.
    """
    repo = _obs_repo(seeded)
    rows = []
    for period in _INC:
        inc = dict(_INC[period])
        if corrupt_newest_gross_profit and period == NEWEST_PERIOD:
            # Trips `gross_profit_equals_revenue_despite_costs`: UW echoing
            # revenue into gross profit while cost_of_revenue stays positive
            # (real total_revenue/cost_of_revenue untouched, so rev_growth's
            # TTM math is unaffected -- only gross_profit/gross_margin should
            # go None for this one period).
            inc["gross_profit"] = inc["total_revenue"]
        filed = NEWEST_FILING_DATE if period == NEWEST_PERIOD else None
        rows.append(_stmt_row(period, "income", inc, filing_published_at=filed))
        rows.append(_stmt_row(period, "balance", _BS[period]))
        rows.append(_stmt_row(period, "cash_flow", _CF[period]))
    inserted, touched = repo.record_statements(rows)
    assert inserted == len(rows)
    assert touched == 0
    if corrupt_newest_gross_profit:
        _scanned, new = repo.recheck_violations()
        assert new == 1


def _oracle_features(seeded) -> dict[str, dict[str, float | None]]:
    """The same panel the job reads, fed straight to `build_features` --
    independent of the job's own internals, so the DB-persisted rows are
    checked against a second derivation, not restated."""
    panel = current_statement_panel(seeded.conn, ["NVDA"], schema=seeded._schema)
    return build_features(panel)["NVDA"]


def test_rollup_matches_build_features_on_real_figures(seeded_db_empty_cards):
    _seed_nvda(seeded_db_empty_cards)
    oracle = _oracle_features(seeded_db_empty_cards)

    result = fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert result["tickers"] == 1
    assert result["rows"] == len(_INC)
    assert result["written"] == len(_INC)

    desk = _desk_repo(seeded_db_empty_cards)
    traj = {
        r["period_end"].isoformat(): r for r in desk.trajectory("NVDA", quarters=20)
    }
    assert set(traj) == set(_INC)

    newest = traj[NEWEST_PERIOD]
    assert oracle[NEWEST_PERIOD]["rev_growth"] is not None  # 8 quarters of history
    # NUMERIC round-trips through Postgres at a different precision than the
    # Python float the oracle computed in-process, so the last digit can
    # differ -- approx, not exact equality.
    assert float(newest["rev_yoy"]) == pytest.approx(
        oracle[NEWEST_PERIOD]["rev_growth"]
    )
    assert float(newest["gross_margin"]) == pytest.approx(
        oracle[NEWEST_PERIOD]["gross_margin"]
    )
    assert float(newest["gross_profit"]) == pytest.approx(
        float(_INC[NEWEST_PERIOD]["gross_profit"])
    )
    # Real filing date wins over the fallback.
    assert newest["knowledge_date"] == NEWEST_FILING_DATE

    oldest = traj[OLDEST_PERIOD]
    # First quarter on file: no TTM history at all, so rev_growth is None --
    # gross_margin needs only the one quarter and is still computed.
    assert oracle[OLDEST_PERIOD]["rev_growth"] is None
    assert oldest["rev_yoy"] is None
    assert float(oldest["gross_margin"]) == pytest.approx(
        oracle[OLDEST_PERIOD]["gross_margin"]
    )
    # No filing date recorded for this period -> the FALLBACK_LAG_DAYS estimate.
    assert oldest["knowledge_date"] == date.fromisoformat(OLDEST_PERIOD) + timedelta(
        days=FALLBACK_LAG_DAYS
    )


def test_a_fallback_knowledge_date_is_stored_as_a_fallback(seeded_db_empty_cards):
    """The look-ahead marker survives the write.

    The fallback errs EARLY for late filers, which manufactures look-ahead --
    measured cost is composite IC 0.059 with it against 0.039 without (see
    `fundamental_scoring._knowledge_date`). Stored in the same column, in the
    same shape, as a real filing date, the two are indistinguishable and the
    distinction is destroyed at write time -- no later reader can recover it.
    `knowledge_date_known` is what lets a leak-free consumer filter the
    estimated rows out.
    """
    _seed_nvda(seeded_db_empty_cards)
    fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )

    desk = _desk_repo(seeded_db_empty_cards)
    traj = {
        r["period_end"].isoformat(): r for r in desk.trajectory("NVDA", quarters=20)
    }
    # NVDA's real 10-Q filing date for 2026-04-30 -- a fact, flagged as one.
    assert traj[NEWEST_PERIOD]["knowledge_date"] == NEWEST_FILING_DATE
    assert traj[NEWEST_PERIOD]["knowledge_date_known"] is True
    # No filing date on file for the oldest quarter: period_end + the lag, and
    # the row says so.
    assert traj[OLDEST_PERIOD]["knowledge_date"] == date.fromisoformat(
        OLDEST_PERIOD
    ) + timedelta(days=FALLBACK_LAG_DAYS)
    assert traj[OLDEST_PERIOD]["knowledge_date_known"] is False

    # `latest_per_ticker` is the matrix-cell read path and must carry the flag
    # too -- a marker only one of two readers can see is not a marker.
    assert desk.latest_per_ticker(["NVDA"])["NVDA"]["knowledge_date_known"] is True


def test_a_late_filing_date_flips_the_knowledge_date_marker_on_replay(
    seeded_db_empty_cards,
):
    """`knowledge_date_known` must be in `upsert_rows`' `ON CONFLICT ... DO
    UPDATE SET` list, the same as every other non-key column -- a column left
    out of that list is write-once: the first run's value sticks and no
    rerun can ever correct it.

    Night 1 the oldest quarter has no filing date, so its row is written
    `knowledge_date_known = False` against the `FALLBACK_LAG_DAYS` estimate.
    The monthly `fundamental_ingest` full re-pull later fills that NULL
    `filing_published_at` via `record_statements`' documented
    COALESCE-on-conflict -- a real fact arrives without changing the
    statement's `content_hash`. A later rollup must then flip BOTH the
    knowledge date and its marker; if `knowledge_date_known` were missing
    from the SET list, `knowledge_date` would silently advance to the real
    filing date while the marker kept claiming it was still an estimate -- a
    row whose date is real but which a leak-free consumer would filter out
    as an estimate.
    """
    _seed_nvda(seeded_db_empty_cards)
    fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )

    desk = _desk_repo(seeded_db_empty_cards)
    before = {
        r["period_end"].isoformat(): r for r in desk.trajectory("NVDA", quarters=20)
    }[OLDEST_PERIOD]
    assert before["knowledge_date_known"] is False

    # NVDA's real 10-K filing date for the 2024-01-31 (fiscal-Q4/FY2024)
    # period -- SEC EDGAR accession 0001045810-24-000029, filed 2024-02-21 --
    # arriving the way the monthly full re-pull's COALESCE-on-conflict fill
    # does: same content_hash, filing_published_at newly populated.
    real_filing_date = date(2024, 2, 21)
    obs = _obs_repo(seeded_db_empty_cards)
    inserted, touched = obs.record_statements(
        [
            _stmt_row(
                OLDEST_PERIOD,
                "income",
                _INC[OLDEST_PERIOD],
                filing_published_at=real_filing_date,
            )
        ]
    )
    assert inserted == 0
    assert touched == 1

    fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )

    after = {
        r["period_end"].isoformat(): r for r in desk.trajectory("NVDA", quarters=20)
    }[OLDEST_PERIOD]
    assert after["knowledge_date_known"] is True
    assert after["knowledge_date"] == real_filing_date


def test_a_violated_field_nulls_only_its_own_metric(seeded_db_empty_cards):
    """Honest absence, scoped to the metric, not the ticker: gross_profit and
    gross_margin go None for the corrupted quarter, while rev_yoy -- which
    depends only on the untouched total_revenue -- still reads the real
    computed value. The row is still produced; nothing is skipped."""
    _seed_nvda(seeded_db_empty_cards, corrupt_newest_gross_profit=True)
    oracle = _oracle_features(seeded_db_empty_cards)

    result = fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert result["rows"] == len(_INC)

    desk = _desk_repo(seeded_db_empty_cards)
    latest = desk.latest_per_ticker(["NVDA"])["NVDA"]
    assert latest["period_end"] == date.fromisoformat(NEWEST_PERIOD)

    # Suppressed: gross_profit was flagged on this exact observation.
    assert latest["gross_margin"] is None
    assert latest["gross_profit"] is None
    # Not suppressed: rev_growth's only input (total_revenue) was never
    # touched, and this is a DIFFERENT ticker-period row than the field the
    # violation fired on -- a violated field must not blank an unrelated
    # metric.
    assert latest["rev_yoy"] is not None
    assert float(latest["rev_yoy"]) == pytest.approx(
        oracle[NEWEST_PERIOD]["rev_growth"]
    )

    # The suppression is scoped to the flagged PERIOD, not the ticker. Without
    # this, a bug that nulls gross_margin on every period of a ticker with one
    # bad quarter passes every assertion above.
    traj = {
        r["period_end"].isoformat(): r for r in desk.trajectory("NVDA", quarters=20)
    }
    assert traj[OLDEST_PERIOD]["gross_margin"] is not None


def test_a_replay_overwrites_rather_than_duplicates(seeded_db_empty_cards):
    """The rollup is a recompute, not an immutable fact -- a second run over
    unchanged data must report zero newly-inserted rows, not len(rows) again,
    and must not leave a second row per (ticker, period_end)."""
    _seed_nvda(seeded_db_empty_cards)
    first = fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert first["written"] == len(_INC)

    second = fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert second["rows"] == len(_INC)
    assert second["written"] == 0

    desk = _desk_repo(seeded_db_empty_cards)
    assert len(desk.trajectory("NVDA", quarters=20)) == len(_INC)


def test_dry_run_computes_without_persisting(seeded_db_empty_cards):
    _seed_nvda(seeded_db_empty_cards)
    result = fundamentals_desk_rollup(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema, dry_run=True
    )
    assert result["rows"] == len(_INC)
    assert result["written"] == 0

    desk = _desk_repo(seeded_db_empty_cards)
    assert desk.trajectory("NVDA", quarters=20) == []
