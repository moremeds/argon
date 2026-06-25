"""Forward entry-capture markout persistence (header + per-leg quote series).

Records the SPX bull-put-spread the Macro Short-Vol signal would place, tracked
to expiry: one idempotent "auto" cohort/day plus on-demand one-shot "button"
cohorts, each snapshotted 8x/day. See migration 085 + the entry-capture plan.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta
from typing import Any

import psycopg

_QUOTE_COLS = (
    "entry_id",
    "as_of",
    "session",
    "leg",
    "strike",
    "opt_right",
    "nbbo_bid",
    "nbbo_ask",
    "iv",
    "delta",
    "gamma",
    "vega",
    "theta",
    "und_spot",
    "source",
    "greeks_source",
    "source_asof",
)


class _VrpMacroEntryMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_vrp_macro_entry(
        self,
        *,
        name: str,
        birth_date: _date,
        born_at: Any,
        origin: str,
        expiry: _date,
        hold_days: int,
        spot_at_birth: Any,
        iv_at_birth: Any,
        vrp_z_at_birth: Any,
        weight_at_birth: Any,
        action_at_birth: str | None,
        short_delta: Any,
        wing_delta: Any,
        short_above: Any,
        short_below: Any,
        wing_above: Any,
        wing_below: Any,
    ) -> int:
        """Insert (or, for auto, reuse) a cohort header; return entry_id.

        ``auto`` is idempotent per (name, birth_date) via the partial unique
        index — a restart double-fire reuses the original row (born_at/strikes
        untouched). ``button`` is a plain insert: each click is its own
        one-shot point-in-time capture, never deduped.
        """
        cols = (
            "name, birth_date, born_at, origin, expiry, hold_days, "
            "spot_at_birth, iv_at_birth, vrp_z_at_birth, weight_at_birth, "
            "action_at_birth, short_delta, wing_delta, "
            "short_strike_above, short_strike_below, wing_strike_above, wing_strike_below"
        )
        values = (
            name,
            birth_date,
            born_at,
            origin,
            expiry,
            hold_days,
            spot_at_birth,
            iv_at_birth,
            vrp_z_at_birth,
            weight_at_birth,
            action_at_birth,
            short_delta,
            wing_delta,
            short_above,
            short_below,
            wing_above,
            wing_below,
        )
        placeholders = ", ".join(["%s"] * len(values))
        if origin == "auto":
            # DO UPDATE on a key column is a deliberate no-op that fires
            # RETURNING on the partial-index conflict, leaving the original
            # born_at/strikes in place.
            sql = (
                f"INSERT INTO {self._schema}.vrp_macro_entry ({cols}) "
                f"VALUES ({placeholders}) "
                "ON CONFLICT (name, birth_date) WHERE origin = 'auto' "
                "DO UPDATE SET name = EXCLUDED.name "
                "RETURNING entry_id"
            )
        else:
            sql = (
                f"INSERT INTO {self._schema}.vrp_macro_entry ({cols}) "
                f"VALUES ({placeholders}) RETURNING entry_id"
            )
        with self._conn.cursor() as cur:
            cur.execute(sql, values)
            return int(cur.fetchone()[0])

    def fetch_open_vrp_macro_entries(
        self, name: str, on_date: _date
    ) -> list[dict[str, Any]]:
        """Open ``auto`` cohorts (expiry >= on_date). Button cohorts are
        one-shot and never re-snapshotted, so they are excluded here. The 4
        strikes surface under the short leg-names the snapshot job consumes."""
        sql = (
            "SELECT entry_id, name, birth_date, born_at, expiry, hold_days, "
            "spot_at_birth, iv_at_birth, vrp_z_at_birth, weight_at_birth, "
            "action_at_birth, short_delta, wing_delta, "
            "short_strike_above AS short_above, short_strike_below AS short_below, "
            "wing_strike_above AS wing_above, wing_strike_below AS wing_below "
            f"FROM {self._schema}.vrp_macro_entry "
            "WHERE origin = 'auto' AND name = %s AND expiry >= %s "
            "ORDER BY birth_date"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (name, on_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def insert_vrp_macro_entry_quotes(self, rows: list[dict[str, Any]]) -> None:
        """Batch upsert leg quotes keyed on (entry_id, as_of, leg). The caller
        freezes one ``as_of`` per mark for all 4 legs so they reconstruct."""
        if not rows:
            return
        collist = ", ".join(_QUOTE_COLS)
        placeholders = ", ".join(["%s"] * len(_QUOTE_COLS))
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in _QUOTE_COLS
            if c not in ("entry_id", "as_of", "leg")
        )
        sql = (
            f"INSERT INTO {self._schema}.vrp_macro_entry_quote ({collist}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (entry_id, as_of, leg) DO UPDATE SET "
            f"{updates}, captured_at = now()"
        )
        params = [tuple(r.get(c) for c in _QUOTE_COLS) for r in rows]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)

    def upsert_vrp_macro_entry_grid(
        self,
        *,
        name: str,
        for_date: _date,
        chosen_expiry: _date,
        strikes: list[float],
    ) -> None:
        """Cache the day's real UW-listed strike grid for the ~43-DTE expiry.

        The RTH birth path reads this instead of calling UW, which 429s once the
        daily budget is spent (reliably before the 10:00 ET birth cron). Idempotent
        upsert on (name, for_date) — a restart re-fetch overwrites in place."""
        sql = (
            f"INSERT INTO {self._schema}.vrp_macro_entry_grid "
            "(name, for_date, chosen_expiry, strikes) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (name, for_date) DO UPDATE SET "
            "chosen_expiry = EXCLUDED.chosen_expiry, strikes = EXCLUDED.strikes, "
            "fetched_at = now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (name, for_date, chosen_expiry, list(strikes)))

    def fetch_vrp_macro_entry_grid(
        self, name: str, for_date: _date, *, max_staleness_days: int = 4
    ) -> dict[str, Any] | None:
        """Most-recent cached grid in the window [for_date - max_staleness_days,
        for_date] whose chosen expiry is still in the future. Returns
        {for_date, chosen_expiry, strikes, fetched_at} (strikes = list[Decimal])
        or None if the cache is cold / only holds too-old or expired grids.

        Why the staleness bound: the strategy births at ~43 calendar DTE. A single
        missed nightly refresh should reuse yesterday's REAL grid (its chosen expiry
        is only ~1 day nearer — fine), but a grid many days old would birth a
        materially-nearer-DTE cohort (e.g. a 43-DTE grid reused at 5 DTE). Beyond
        the bound we'd rather skip birth (logged) than persist an off-strategy
        cohort. ``chosen_expiry > for_date`` additionally rejects an already-expired
        cached expiry within the window."""
        sql = (
            "SELECT for_date, chosen_expiry, strikes, fetched_at "
            f"FROM {self._schema}.vrp_macro_entry_grid "
            "WHERE name = %s AND for_date BETWEEN %s AND %s AND chosen_expiry > %s "
            "ORDER BY for_date DESC LIMIT 1"
        )
        oldest = for_date - timedelta(days=max_staleness_days)
        with self._conn.cursor() as cur:
            cur.execute(sql, (name, oldest, for_date, for_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_vrp_macro_entry(self, entry_id: int) -> dict[str, Any] | None:
        """One cohort header by id (any origin) — the 4 strikes surface under the
        short leg-names. Used by the capture endpoint to read back a button cohort
        (which fetch_open_vrp_macro_entries excludes)."""
        sql = (
            "SELECT entry_id, name, birth_date, born_at, origin, expiry, hold_days, "
            "spot_at_birth, iv_at_birth, vrp_z_at_birth, weight_at_birth, "
            "action_at_birth, short_delta, wing_delta, "
            "short_strike_above AS short_above, short_strike_below AS short_below, "
            "wing_strike_above AS wing_above, wing_strike_below AS wing_below "
            f"FROM {self._schema}.vrp_macro_entry WHERE entry_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (entry_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_vrp_macro_entry_quotes(self, entry_id: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT {', '.join(_QUOTE_COLS)}, captured_at "
            f"FROM {self._schema}.vrp_macro_entry_quote "
            "WHERE entry_id = %s ORDER BY as_of, leg"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (entry_id,))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def list_vrp_macro_entries(
        self, name: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Newest-first cohort headers (research history)."""
        sql = (
            "SELECT entry_id, name, birth_date, born_at, origin, expiry, "
            "hold_days, spot_at_birth, iv_at_birth, vrp_z_at_birth, "
            "weight_at_birth, action_at_birth, short_delta, wing_delta, "
            "short_strike_above, short_strike_below, wing_strike_above, "
            "wing_strike_below, created_at "
            f"FROM {self._schema}.vrp_macro_entry "
            "WHERE name = %s ORDER BY born_at DESC LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (name, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
