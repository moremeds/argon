"""sector_rs_daily persistence (migration 152).

Its own module and not a `Repository` mixin: repository.py is closed to new
query methods (root CLAUDE.md module-size rule). The shape follows
storage/company_sector.py: a standalone class over one connection that
commits its own writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from uw_scan.reports.sector_rs import WINDOWS, SectorRsRow

_LABELS = tuple(WINDOWS)  # ('1m', '3m', '6m', '12m')
_KEY = ("as_of", "group_kind", "group_key")
_COLS = (
    *_KEY,
    "weighting",
    "rs_symbol",
    "n_members",
    "n_classified",
    "n_priced",
    *(f"rs_{w}" for w in _LABELS),
    *(f"breadth_{w}" for w in _LABELS),
    "degraded",
    "source",
)


def _params(r: SectorRsRow) -> tuple[Any, ...]:
    return (
        r.as_of,
        r.group_kind,
        r.group_key,
        r.weighting,
        r.rs_symbol,
        r.n_members,
        r.n_classified,
        r.n_priced,
        *(r.rs.get(w) for w in _LABELS),
        *(r.breadth.get(w) for w in _LABELS),
        r.degraded,
        r.source,
    )


def _row(t: Sequence[Any]) -> SectorRsRow:
    k = len(_LABELS)
    rs_vals = t[8 : 8 + k]
    breadth_vals = t[8 + k : 8 + 2 * k]
    return SectorRsRow(
        as_of=t[0],
        group_kind=t[1],
        group_key=t[2],
        weighting=t[3],
        rs_symbol=t[4],
        n_members=t[5],
        n_classified=t[6],
        n_priced=t[7],
        rs=dict(zip(_LABELS, rs_vals, strict=True)),
        breadth=dict(zip(_LABELS, breadth_vals, strict=True)),
        degraded=t[8 + 2 * k],
        source=t[9 + 2 * k],
    )


class SectorRsRepository:
    def __init__(self, conn: psycopg.Connection, *, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[SectorRsRow]) -> int:
        """Insert or overwrite every column, keyed (as_of, group_kind, group_key).

        DO UPDATE on every column, not DO NOTHING: a nightly re-run after a
        late bar, or a backfill with --force, must converge on the recomputed
        row. `computed_at` is bumped so the table says when a row was last derived.
        """
        if not rows:
            return 0
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS if c not in _KEY)
        sql = (
            f"INSERT INTO {self._schema}.sector_rs_daily ({', '.join(_COLS)}) "
            f"VALUES ({', '.join(['%s'] * len(_COLS))}) "
            f"ON CONFLICT ({', '.join(_KEY)}) DO UPDATE SET {updates}, computed_at = now()"
        )
        with self.conn.cursor() as cur:
            cur.executemany(sql, [_params(r) for r in rows])
        self.conn.commit()
        return len(rows)

    def latest(self, as_of: date, group_kind: str) -> list[SectorRsRow]:
        """Every group's row on the last as_of ≤ `as_of` for this kind."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT {", ".join(_COLS)} FROM {self._schema}.sector_rs_daily
                     WHERE group_kind = %s
                       AND as_of = (SELECT max(as_of) FROM {self._schema}.sector_rs_daily
                                     WHERE group_kind = %s AND as_of <= %s)
                     ORDER BY group_key""",
                (group_kind, group_kind, as_of),
            )
            return [_row(t) for t in cur.fetchall()]

    def history(
        self, group_kind: str, group_key: str, since: date
    ) -> list[SectorRsRow]:
        """One group's rows from `since`, ascending by as_of."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT {", ".join(_COLS)} FROM {self._schema}.sector_rs_daily
                     WHERE group_kind = %s AND group_key = %s AND as_of >= %s
                     ORDER BY as_of""",
                (group_kind, group_key, since),
            )
            return [_row(t) for t in cur.fetchall()]

    def dates_present(self, group_kind: str, start: date, end: date) -> set[date]:
        """Sessions already holding at least one row of this kind (backfill resume)."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT as_of FROM {self._schema}.sector_rs_daily
                     WHERE group_kind = %s AND as_of BETWEEN %s AND %s""",
                (group_kind, start, end),
            )
            return {r[0] for r in cur.fetchall()}
