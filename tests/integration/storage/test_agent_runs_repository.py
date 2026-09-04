"""The generic agent-run store (migration 148) — behaviour, not implementation.

Everything here is about the guarantees a blind writer depends on: a retry does
not publish a second run, a re-render publishes a version beside the old one
rather than over it, and one tenant cannot see another's rows by accident.
"""

from __future__ import annotations

from datetime import date

from uw_scan.storage.agent_runs import AgentRunsRepository, iso_week_key

# Frozen from the recorded option-wizard run of 2026-09-03. No invented numbers.
VIEW_A = {
    "date": "2026-09-03",
    "tape": [
        {"label": "SPY", "value": "772.80"},
        {"label": "QQQ", "value": "717.47"},
        {"label": "VIX", "value": "16.34", "source": "VIXCLS, 2026-09-01"},
    ],
}
VIEW_B = {
    "date": "2026-09-03",
    "tape": [
        {"label": "NVDA", "value": "227.60"},
        {"label": "MSFT", "value": "510.53"},
        {"label": "AVGO", "value": "355.90"},
    ],
}


def _repo(seeded) -> AgentRunsRepository:
    return AgentRunsRepository(seeded.conn, schema=seeded._schema)


def _ingest(repo: AgentRunsRepository, **over):
    args = dict(
        tenant="option-wizard",
        kind="premarket",
        run_day=date(2026, 9, 3),
        run_id="ow-2026-09-03-premarket-1",
        code_sha="a1b2c3d",
        schema_version=1,
        outcome="completed",
        headline="SPY 772.80, one sentence.",
        view=VIEW_A,
        report={},
    )
    args.update(over)
    return repo.ingest(**args)


def test_iso_week_key_uses_the_iso_year():
    """2026-09-03 is a Thursday in ISO week 36."""
    assert iso_week_key(date(2026, 9, 3)) == "2026-W36"
    # ISO YEAR, not calendar year: 2025-12-29 is a Monday in 2026-W01.
    assert iso_week_key(date(2025, 12, 29)) == "2026-W01"


def test_a_re_render_publishes_a_version_beside_the_old_one(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    assert _ingest(repo) == (1, True)
    assert _ingest(repo, run_id="ow-2026-09-03-premarket-2", view=VIEW_B) == (2, True)


def test_the_same_run_id_twice_is_the_same_run(seeded_db_empty_cards):
    """A blind retry must return the stored version, never publish a duplicate."""
    repo = _repo(seeded_db_empty_cards)
    assert _ingest(repo) == (1, True)
    assert _ingest(repo) == (1, False)


def test_an_omitted_week_key_falls_back_to_the_iso_week_of_the_run_day(
    seeded_db_empty_cards,
):
    repo = _repo(seeded_db_empty_cards)
    _ingest(repo)
    weeks = repo.weeks(tenant="option-wizard")
    assert [w["week_key"] for w in weeks] == ["2026-W36"]
    assert weeks[0]["run_count"] == 1
    assert weeks[0]["day_count"] == 1
    assert weeks[0]["first_day"] == date(2026, 9, 3)
    assert weeks[0]["last_day"] == date(2026, 9, 3)


def test_a_backward_looking_run_is_filed_under_the_week_the_writer_named(
    seeded_db_empty_cards,
):
    """The Monday review of last week belongs to LAST week."""
    repo = _repo(seeded_db_empty_cards)
    _ingest(repo)
    _ingest(
        repo,
        kind="frank",
        run_day=date(2026, 9, 7),
        run_id="ow-2026-09-07-frank-1",
        week_key="2026-W36",
        view=VIEW_B,
    )
    kinds = [r["kind"] for r in repo.week(tenant="option-wizard", week_key="2026-W36")]
    assert sorted(kinds) == ["frank", "premarket"]


def test_the_week_index_carries_the_newest_version_and_no_documents(
    seeded_db_empty_cards,
):
    repo = _repo(seeded_db_empty_cards)
    _ingest(repo)
    _ingest(
        repo,
        run_id="ow-2026-09-03-premarket-2",
        code_sha="9f9f9f9",
        view=VIEW_B,
    )
    rows = repo.week(tenant="option-wizard", week_key="2026-W36")
    assert len(rows) == 1
    assert rows[0]["version_no"] == 2
    assert rows[0]["code_sha"] == "9f9f9f9"
    assert "view_jsonb" not in rows[0]
    assert "view" not in rows[0]


def test_a_run_reads_back_the_newest_view_and_an_explicit_older_one(
    seeded_db_empty_cards,
):
    repo = _repo(seeded_db_empty_cards)
    _ingest(repo)
    _ingest(repo, run_id="ow-2026-09-03-premarket-2", view=VIEW_B)

    newest = repo.run(tenant="option-wizard", kind="premarket", run_day=date(2026, 9, 3))
    assert newest is not None
    assert newest["version_no"] == 2
    assert newest["view"] == VIEW_B

    older = repo.run(
        tenant="option-wizard",
        kind="premarket",
        run_day=date(2026, 9, 3),
        version_no=1,
    )
    assert older is not None
    assert older["view"] == VIEW_A


def test_a_day_with_nothing_recorded_is_none_not_an_empty_shape(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    assert (
        repo.run(tenant="option-wizard", kind="premarket", run_day=date(2026, 9, 2))
        is None
    )


def test_latest_crosses_kinds_unless_a_kind_is_named(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    _ingest(repo)
    _ingest(
        repo,
        kind="close",
        run_day=date(2026, 9, 4),
        run_id="ow-2026-09-04-close-1",
        view=VIEW_B,
    )
    assert repo.latest(tenant="option-wizard")["kind"] == "close"
    assert (
        repo.latest(tenant="option-wizard", kind="premarket")["run_day"]
        == date(2026, 9, 3)
    )


def test_one_tenants_rows_are_invisible_to_another(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    _ingest(repo)
    _ingest(
        repo,
        tenant="livewire-shepherd",
        kind="heal",
        run_id="ls-2026-09-03-heal-1",
        view=VIEW_B,
    )
    assert repo.weeks(tenant="option-wizard")[0]["run_count"] == 1
    assert [r["kind"] for r in repo.week(tenant="option-wizard", week_key="2026-W36")] == [
        "premarket"
    ]
    assert repo.latest(tenant="option-wizard")["kind"] == "premarket"
    assert repo.latest(tenant="livewire-shepherd")["kind"] == "heal"
    assert (
        repo.run(tenant="option-wizard", kind="heal", run_day=date(2026, 9, 3)) is None
    )
