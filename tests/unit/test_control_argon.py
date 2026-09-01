"""Pure-logic checks for the control-argon CLI. No DB, no network."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.control_argon import (
    DENY,
    LOCAL_DB,
    MINI_DB,
    MINI_HOST,
    Table,
    build_parser,
    mini_dsn,
    require_sync_direction,
)


def _table(**kw) -> Table:
    base = dict(name="t", columns=("a",), date_columns=(), size_bytes=0)
    return Table(**{**base, **kw})


def test_date_column_prefers_the_observation_date_over_the_write_date():
    # inserted_at dates the WRITE; a backfilled row would look fresh under it.
    t = _table(date_columns=("inserted_at", "market_date", "expiry"))
    assert t.date_column() == "market_date"


def test_date_column_falls_back_to_a_write_stamp_when_that_is_all_there_is():
    assert _table(date_columns=("inserted_at",)).date_column() == "inserted_at"


def test_date_column_is_none_when_the_table_has_no_date_at_all():
    assert _table().date_column() is None


def test_deny_list_covers_the_raw_and_audit_tables():
    # These are the ones worth nothing on a browse box and cost ~11 GB.
    assert {"raw_payloads", "external_api_requests", "api_request_audit"} <= DENY


def _settings(**kw) -> Settings:
    base = dict(
        api_key=SecretStr("test"),
        db_host="127.0.0.1",
        db_name=LOCAL_DB,
        db_user="argon_app",
        db_password=SecretStr("pw"),
    )
    return Settings(**{**base, **kw})


def test_sync_refuses_the_test_tier():
    # option_wizard_test is TRUNCATEd per test — synced data dies in one case.
    with pytest.raises(SystemExit, match="option_wizard_test"):
        require_sync_direction(_settings(db_name="option_wizard_test"))


def test_sync_refuses_when_this_box_is_pointed_at_the_mini():
    with pytest.raises(SystemExit, match="pointed at the mini"):
        require_sync_direction(_settings(db_host=MINI_HOST, db_name=MINI_DB))


def test_sync_accepts_the_one_supported_direction():
    require_sync_direction(_settings())


def test_mini_dsn_targets_the_mini_and_carries_the_password():
    dsn = mini_dsn(_settings())
    assert f"host={MINI_HOST}" in dsn and f"dbname={MINI_DB}" in dsn
    assert "password=pw" in dsn


def test_ports_are_parsed_after_the_subcommand():
    args = build_parser().parse_args(["doctor", "--api-port", "8402"])
    assert (args.api_port, args.web_port) == (8402, 3001)
    assert (
        build_parser().parse_args(["smoke", "AAPL", "--web-port", "3003"]).web_port
        == 3003
    )
