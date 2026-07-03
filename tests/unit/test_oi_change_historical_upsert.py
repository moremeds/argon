from __future__ import annotations

from datetime import date

from uw_scan.models import OiChangeRow
from uw_scan.storage.options import _OptionsMixin


class _Cursor:
    def __init__(self) -> None:
        self.sql: str | None = None
        self.params: list[tuple] | None = None
        self.statements: list[tuple[str, list[tuple]]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def executemany(self, sql: str, params: list[tuple]) -> None:
        self.sql = sql
        self.params = params
        self.statements.append((sql, params))


class _Conn:
    def __init__(self) -> None:
        self.cursor_obj = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_obj


class _Repo(_OptionsMixin):
    def __init__(self) -> None:
        self._conn = _Conn()
        self._schema = "uw_scan"


def test_historical_oi_change_replace_deletes_date_slice_before_insert():
    repo = _Repo()
    row = OiChangeRow(
        underlying_symbol="AAPL",
        option_symbol="AAPL250718C00200000",
        curr_date=date(2025, 7, 3),
        last_date=date(2025, 7, 2),
        curr_oi=120,
        last_oi=80,
    )

    count = repo.replace_oi_change_rows_for_date(run_id=456, rows=[row])

    assert count == 1
    statements = repo._conn.cursor_obj.statements
    assert "DELETE FROM uw_scan.oi_change_events" in statements[0][0]
    assert "underlying_symbol = %s AND curr_date = %s" in statements[0][0]
    assert statements[0][1] == [("AAPL", date(2025, 7, 3))]
    assert "ON CONFLICT (run_id, option_symbol) DO NOTHING" in statements[1][0]
    assert statements[1][1][0][:5] == (
        456,
        "AAPL",
        "AAPL250718C00200000",
        date(2025, 7, 3),
        date(2025, 7, 2),
    )
