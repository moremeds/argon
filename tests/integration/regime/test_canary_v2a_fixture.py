from __future__ import annotations

from datetime import date

from tests.integration.regime._canary_v2a_fixture import seed_vol_index_full_history


class _CountingCursor:
    def __init__(self, cursor, counter: dict[str, int]) -> None:
        self._cursor = cursor
        self._counter = counter

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def execute(self, *args, **kwargs):
        self._counter["execute"] += 1
        return self._cursor.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _CountingConnection:
    """Transparent instrumentation over the real Postgres connection."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self.counter = {"execute": 0}

    def cursor(self, *args, **kwargs):
        return _CountingCursor(
            self._connection.cursor(*args, **kwargs),
            self.counter,
        )

    def __getattr__(self, name):
        return getattr(self._connection, name)


def test_vol_index_seed_is_value_preserving_idempotent_and_batched(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    conn = _CountingConnection(repo.conn)
    start = date(2026, 1, 2)
    end = date(2026, 1, 30)

    dates = seed_vol_index_full_history(
        conn,
        schema=repo._schema,
        start=start,
        end=end,
        seed=42,
    )

    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*), MIN(trade_date), MAX(trade_date), "
            f"COUNT(DISTINCT symbol) FROM {repo._schema}.vol_index_daily"
        )
        count, minimum, maximum, symbols = cur.fetchone()
        cur.execute(
            f"SELECT close FROM {repo._schema}.vol_index_daily "
            "WHERE symbol='SPX' AND trade_date=%s",
            (dates[0],),
        )
        first_spx = float(cur.fetchone()[0])

    assert count == len(dates) * 5
    assert (minimum, maximum, symbols) == (dates[0], dates[-1], 5)
    assert first_spx == 1000.0

    seed_vol_index_full_history(
        conn,
        schema=repo._schema,
        start=start,
        end=end,
        seed=42,
    )
    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {repo._schema}.vol_index_daily")
        assert cur.fetchone()[0] == count

    # Two calls may create a staging table and merge it, but must not execute one
    # INSERT per date/symbol row (the old path performs >200 executes here).
    assert conn.counter["execute"] <= 4
