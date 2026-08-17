"""Every strict dataset must resolve a date AND ticker column against the schema.

When either is unresolvable the audit returns zero gaps, which reads exactly like
"fully covered" -- the silent no-op this healer exists to surface. Two datasets
shipped in that state on 2026-08-16 (pcr_history, option_chain_per_strike; both
key on `snapshot_date`, absent from _DATE_COL_PREFERENCE), so this gate exists to
catch the next one at CI time rather than after an outage.
"""

import pytest

from uw_scan.reports.data_gap_healer import (
    _DATE_COL_PREFERENCE,
    _TICKER_COL_PREFERENCE,
    REGISTRY,
    _detect_col,
)

STRICT = [e for e in REGISTRY if e.audit_mode.startswith("strict")]


def _columns(conn, schema, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s",
            (schema, table),
        )
        return {r[0] for r in cur.fetchall()}


def test_registry_has_strict_entries():
    assert STRICT, "guard is vacuous if nothing is strict"


@pytest.mark.parametrize("entry", STRICT, ids=lambda e: e.table_name)
def test_strict_entry_resolves_a_date_column(seeded_db_empty_cards, entry):
    repo = seeded_db_empty_cards
    cols = _columns(repo.conn, repo._schema, entry.table_name)
    if not cols:
        pytest.skip(f"{entry.table_name} not present in the test schema")
    resolved = entry.date_col or _detect_col(
        repo.conn, repo._schema, entry.table_name, _DATE_COL_PREFERENCE
    )
    assert resolved, (
        f"{entry.table_name} is {entry.audit_mode} but no date column resolves. "
        f"Its columns are {sorted(cols)}. Either add one to _DATE_COL_PREFERENCE "
        f"or set date_col= explicitly on its DatasetRegistryEntry -- otherwise it "
        f"audits as ZERO gaps forever."
    )
    assert resolved in cols, f"{entry.table_name}: resolved {resolved!r} is not a real column"


@pytest.mark.parametrize(
    "entry", [e for e in STRICT if e.audit_mode == "strict_ticker_date"],
    ids=lambda e: e.table_name,
)
def test_strict_ticker_date_entry_resolves_a_ticker_column(seeded_db_empty_cards, entry):
    repo = seeded_db_empty_cards
    cols = _columns(repo.conn, repo._schema, entry.table_name)
    if not cols:
        pytest.skip(f"{entry.table_name} not present in the test schema")
    resolved = entry.ticker_col or _detect_col(
        repo.conn, repo._schema, entry.table_name, _TICKER_COL_PREFERENCE
    )
    assert resolved, (
        f"{entry.table_name} is strict_ticker_date but no ticker column resolves. "
        f"Its columns are {sorted(cols)}."
    )
    assert resolved in cols
