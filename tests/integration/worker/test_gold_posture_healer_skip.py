"""The nightly healer fills a MISSING posture day; it does not add a second row (I-112).

Readers take the first active row per obs_date, so the healer's 20:05 recompute beside
the 19:10 row was never read -- it only made a 4th row a day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS, HealContext, RequestBudget

DAY = date(2026, 9, 30)


def _ctx(repo) -> HealContext:
    return HealContext(
        repo=repo,
        gap=None,
        schema=repo._schema,
        today=DAY,
        budget=RequestBudget(uw_cap=None),
        settings=Settings.from_env(),
    )


def _seed_gld_close(repo) -> None:
    repo.insert_macro_series_daily_rows(
        [
            {
                "series_id": "GLD_CLOSE",
                "obs_date": DAY,
                "value": Decimal("300"),
                "release_date": None,
                "source_url": None,
            }
        ],
        as_of=datetime(2026, 9, 30, 21, tzinfo=UTC),
        source="MASSIVE",
    )
    repo.conn.commit()


def _record_calls(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(
        "uw_scan.worker.jobs.gold_jobs.gold_posture_compute_job",
        lambda **kw: calls.append(kw),
    )
    return calls


def test_healer_skips_a_day_that_already_has_a_posture_row(
    seeded_db_empty_cards, monkeypatch
) -> None:
    repo = seeded_db_empty_cards
    _seed_gld_close(repo)
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.gold_posture_daily "
            "(obs_date, computed_at, gauge_state, inputs_jsonb) "
            "VALUES (%s, '2026-09-30 19:10-04', 'neutral', '{}')",
            (DAY,),
        )
    repo.conn.commit()
    calls = _record_calls(monkeypatch)

    HEAL_SPECS["gold_posture"].run(_ctx(repo))

    assert calls == []


def test_healer_fills_a_missing_posture_day(seeded_db_empty_cards, monkeypatch) -> None:
    repo = seeded_db_empty_cards
    _seed_gld_close(repo)
    calls = _record_calls(monkeypatch)

    HEAL_SPECS["gold_posture"].run(_ctx(repo))

    assert [c["as_of"] for c in calls] == [DAY]
