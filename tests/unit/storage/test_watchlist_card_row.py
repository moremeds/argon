"""N5 from backend code review: WatchlistCardRow.from_list_row must validate
that the row's column names match the canonical SELECT projection. Catches
SELECT-alias typos at construction time instead of silently surfacing as
missing FE fields.

The lenient from_db() is preserved for get_watchlist_card (SELECT *), which
returns a different column shape (no watchlist fields, no active_job_*).
"""

from __future__ import annotations

import pytest

from uw_scan.storage.repository import WatchlistCardRow


class _StubCol:
    def __init__(self, name: str) -> None:
        self.name = name


def _desc(*names: str) -> list[_StubCol]:
    return [_StubCol(n) for n in names]


def test_from_list_row_rejects_unknown_column() -> None:
    """The whole point of the strict constructor: typos must fail loudly."""
    cols = list(WatchlistCardRow._LIST_FIELDS) + ["setup_typ"]  # typo
    with pytest.raises(ValueError, match="unknown column"):
        WatchlistCardRow.from_list_row(
            row=tuple(None for _ in cols),
            description=_desc(*cols),
        )


def test_from_list_row_rejects_missing_required_column() -> None:
    """Drift the other way: a known column dropped from SELECT must also fail."""
    cols = [c for c in WatchlistCardRow._LIST_FIELDS if c != "ticker"]
    with pytest.raises(ValueError, match="missing column"):
        WatchlistCardRow.from_list_row(
            row=tuple(None for _ in cols),
            description=_desc(*cols),
        )


def test_from_list_row_rejects_duplicate_columns() -> None:
    """Codex ISSUE-10: a duplicate alias must not silently collapse via set()."""
    cols = list(WatchlistCardRow._LIST_FIELDS) + ["ticker"]
    with pytest.raises(ValueError, match="duplicate column"):
        WatchlistCardRow.from_list_row(
            row=tuple(None for _ in cols),
            description=_desc(*cols),
        )


def test_from_list_row_accepts_full_column_set() -> None:
    """Smoke: the canonical projection constructs cleanly."""
    cols = list(WatchlistCardRow._LIST_FIELDS)
    row = tuple(None for _ in cols)
    out = WatchlistCardRow.from_list_row(row, _desc(*cols))
    assert out.ticker is None


def test_from_db_still_accepts_lenient_shape() -> None:
    """Codex ISSUE-2: get_watchlist_card uses SELECT *, which has a different
    column set (no watchlist fields, has updated_at). The lenient from_db
    must keep working — only from_list_row is strict."""
    cols = ["ticker", "run_id", "spot", "iv_atm", "updated_at"]
    row = ("AAPL", 1, None, None, None)
    out = WatchlistCardRow.from_db(row, _desc(*cols))
    assert out.ticker == "AAPL"
    assert out.updated_at is None
