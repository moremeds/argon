"""Every MONITORED_TABLES entry must resolve a real data-date column.

When it does not, compute_freshness emits date_col='?' with zero counts and a
False `frozen` — a row that reads "measured, nothing wrong" while measuring
nothing. That is the same silent no-op the strict-entry gate catches on the
healer side; this is its freshness-monitor twin.
"""

import pytest

from uw_scan.reports.data_freshness import MONITORED_TABLES, _detect_date_col


def _columns(conn, schema, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s",
            (schema, table),
        )
        return {r[0] for r in cur.fetchall()}


def test_gate_is_not_vacuous():
    assert MONITORED_TABLES


@pytest.mark.parametrize("mt", MONITORED_TABLES, ids=lambda m: m.name)
def test_monitored_table_resolves_a_date_column(seeded_db_empty_cards, mt):
    repo = seeded_db_empty_cards
    cols = _columns(repo.conn, repo._schema, mt.name)
    if not cols:
        pytest.skip(f"{mt.name} not present in the test schema")
    resolved = mt.date_col_override or _detect_date_col(
        repo.conn, repo._schema, mt.name
    )
    assert resolved, (
        f"{mt.name} resolves no data-date column. Its columns are {sorted(cols)}. "
        f"Add one to _DATE_COL_PREFERENCE or set date_col_override= on its "
        f"MonitoredTable — otherwise its freshness row is a permanent no-op."
    )
    assert resolved in cols, f"{mt.name}: resolved {resolved!r} is not a real column"
