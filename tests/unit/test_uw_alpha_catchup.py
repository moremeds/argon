"""Arg-surface + guard tests for the event-log catch-up CLI. No DB/network:
these exercise the real parser and the pre-DB validation gate only.
"""

from __future__ import annotations

import scripts.backfill.uw_alpha_catchup as cat


def _parse(argv):
    return cat._build_parser().parse_args(argv)


def test_backfill_eventlog_defaults_parse():
    ns = _parse(["backfill-eventlog"])
    assert ns.func is cat.cmd_backfill_eventlog
    assert ns.confirm is False  # dry-run by default
    assert ns.max_uw_calls == cat.DEFAULT_MAX_UW_CALLS
    assert ns.start == "2026-07-02"
    # default datasets are exactly the 2 event logs
    assert set(ns.datasets.split(",")) == set(cat._EVENTLOG)


def test_coverage_defaults_parse():
    ns = _parse(["coverage", "--end", "2026-07-24"])
    assert ns.func is cat.cmd_coverage
    assert ns.end == "2026-07-24"


def test_backfill_eventlog_rejects_daily_table_before_db(monkeypatch):
    # A daily table (healer-owned) must be rejected by the guard BEFORE any DB
    # connection — proves the CLI won't event-log-backfill a strict daily table.
    def _boom(*a, **k):
        raise AssertionError("must not connect to DB when dataset is invalid")

    monkeypatch.setattr(cat.psycopg, "connect", _boom)
    ns = _parse(["backfill-eventlog", "--datasets", "uw_gex_levels_daily"])
    settings = object()  # never used: guard returns before touching settings
    assert cat.cmd_backfill_eventlog(ns, settings) == 2


def test_eventlog_registry_excludes_daily_tables():
    # the event-log map must never contain a daily/healer-owned table
    assert set(cat._EVENTLOG) == {
        "uw_intraday_option_flow_bars",
        "uw_dark_lit_flow_prints",
    }
