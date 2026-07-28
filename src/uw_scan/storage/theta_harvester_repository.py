"""Theta Harvester persistence + warm-store loaders.

Standalone repository (not a Repository mixin) — new persistence domains get
their own module from method one; repository.py is not extended.

Every loader reads Postgres only. The scanner's ranking path makes zero UW
calls: option_surface_grid_daily supplies the chain, exposures_by_expiry_strike
the dealer GEX, daily_ohlc the price history, iv_rank_history the current IV.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from uw_scan.scanners.theta_harvester import OptionLeg, ThetaCandidate

_CANDIDATE_COLUMNS: tuple[str, ...] = (
    "ticker",
    "as_of",
    "expiry",
    "dte",
    "put_strike",
    "call_strike",
    "underlying_spot",
    "put_iv",
    "call_iv",
    "risk_free_rate",
    "put_mark",
    "call_mark",
    "entry_credit_theo",
    "net_delta",
    "theta",
    "gamma",
    "vega",
    "score",
    "weights_version",
    "verdict",
    "iv",
    "hv20",
    "hv60",
    "iv_rv_edge",
    "iv_rv_ratio",
    "trend_20d_pct",
    "range_score",
    "dealer_support",
    "net_gex",
    "gex_flip",
    "gate_delta_near_zero",
    "gate_iv_rich_vs_rv",
    "gate_dealer_support",
    "gate_theta_positive",
    "gate_gamma_controlled",
    "gate_range_bound",
)


class ThetaHarvesterRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    # ---------------------------------------------------------------- loaders

    def active_tickers(self) -> list[str]:
        sql = (
            f"SELECT ticker FROM {self._schema}.watchlist "
            "WHERE removed_at IS NULL ORDER BY ticker"
        )
        return [r[0] for r in self._conn.execute(sql).fetchall()]

    def load_chain(self, ticker: str, as_of: date) -> list[OptionLeg]:
        """Both sides of the grid flattened into per-right legs.

        Rows missing IV or delta on a side are skipped for that side only — a
        put-less strike still contributes its call.
        """
        sql = f"""
            SELECT expiry, strike,
                   call_iv, call_delta, call_theta, call_gamma, call_vega,
                   put_iv,  put_delta,  put_theta,  put_gamma,  put_vega
              FROM {self._schema}.option_surface_grid_daily
             WHERE ticker = %s AND market_date = %s
             ORDER BY expiry, strike
        """
        # ORDER BY is load-bearing, not cosmetic: without it Postgres may return
        # rows in any order, and the selector's tie-break would silently depend
        # on physical row layout.
        out: list[OptionLeg] = []
        with self._conn.cursor(row_factory=dict_row) as cur:
            for row in cur.execute(sql, (ticker, as_of)).fetchall():
                for right, pfx in (("C", "call"), ("P", "put")):
                    iv, delta = row[f"{pfx}_iv"], row[f"{pfx}_delta"]
                    if iv is None or delta is None:
                        continue
                    out.append(
                        OptionLeg(
                            expiry=row["expiry"],
                            strike=float(row["strike"]),
                            right=right,
                            iv=float(iv),
                            delta=float(delta),
                            theta=float(row[f"{pfx}_theta"] or 0.0),
                            gamma=float(row[f"{pfx}_gamma"] or 0.0),
                            vega=float(row[f"{pfx}_vega"] or 0.0),
                        )
                    )
        return out

    def latest_surface_date(self, *, min_tickers: int = 80) -> date | None:
        """Newest session whose IV surface capture looks COMPLETE.

        The scan anchors here, never on date.today(): the 19:45 ET cron runs
        after that evening's capture on a weekday, but on a holiday — or if the
        capture failed — today has no grid rows and a today-anchored scan would
        silently write zero candidates and look like "no signal".

        `min_tickers` guards a subtler failure. option_surface_capture commits
        per ticker, so the newest market_date appears the moment the FIRST
        ticker lands. A 19:45 scan against a 19:00 capture that is still running
        would see a partially populated session, silently skip every
        uncaptured ticker, and persist a truncated universe that looks
        identical to "those tickers had no candidate". Requiring a plausible
        ticker count before anchoring turns a silent truncation into a skipped
        run. 80 is ~75% of the current 109-ticker watchlist; the fallback to
        the previous complete session is deliberate and safe, because the
        markout re-marks from whatever as_of actually got written.
        """
        sql = f"""
            SELECT market_date
              FROM {self._schema}.option_surface_grid_daily
             GROUP BY market_date
            HAVING COUNT(DISTINCT ticker) >= %s
             ORDER BY market_date DESC
             LIMIT 1
        """
        row = self._conn.execute(sql, (min_tickers,)).fetchone()
        return row[0] if row else None

    def load_spot(self, ticker: str, as_of: date) -> float | None:
        sql = f"""
            SELECT underlying_spot FROM {self._schema}.option_surface_grid_daily
             WHERE ticker = %s AND market_date = %s AND underlying_spot IS NOT NULL
             LIMIT 1
        """
        row = self._conn.execute(sql, (ticker, as_of)).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def load_gex_rows(self, ticker: str, as_of: date) -> list[dict[str, Any]]:
        """Per-strike GEX, aggregated across expiries for that session.

        Sourced from the newest run_id on the date — exposures_by_expiry_strike
        is keyed by run_id and a session can hold more than one scan run.
        """
        sql = f"""
            SELECT strike, SUM(call_gex) AS call_gex, SUM(put_gex) AS put_gex
              FROM {self._schema}.exposures_by_expiry_strike
             WHERE ticker = %s AND market_date = %s
               AND run_id = (
                   SELECT MAX(run_id) FROM {self._schema}.exposures_by_expiry_strike
                    WHERE ticker = %s AND market_date = %s
               )
             GROUP BY strike
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (ticker, as_of, ticker, as_of)).fetchall()

    def load_closes(self, ticker: str, as_of: date, lookback: int = 90) -> list[float]:
        """Ascending closes up to and including as_of."""
        sql = f"""
            SELECT close FROM (
                SELECT date, close FROM {self._schema}.daily_ohlc
                 WHERE ticker = %s AND date <= %s AND close IS NOT NULL
                 ORDER BY date DESC LIMIT %s
            ) t ORDER BY date ASC
        """
        rows = self._conn.execute(sql, (ticker, as_of, lookback)).fetchall()
        return [float(r[0]) for r in rows]

    def load_atm_iv(self, ticker: str, as_of: date, expiry: date) -> float | None:
        """ATM IV from the SAME grid session and expiry the legs come from.

        NOT from iv_rank_history. That table carries only 4 tickers per session
        (verified on both option_wizard and option_wizard_local, 2026-07-29), and
        the obvious `market_date <= as_of ORDER BY DESC LIMIT 1` lookup silently
        returns a MONTHS-old reading for everything else: of the 114 grid tickers
        on 2026-07-24, 3 had same-day IV, 85 were stale by more than a week, and
        26 had never been captured at all. That comparison — May's IV against
        July's realised vol — passes every type check and quietly destroys the
        one gate with published empirical support.

        The grid has full coverage (114/114 on the same session) and is the same
        surface the legs are priced from, so the IV and the structure can never
        disagree about which session they describe. Cross-checked on IWM
        2026-07-24, the one ticker where both sources exist: grid 0.2059 vs
        iv_rank_history 0.208.

        ponytail: nearest strike, not an interpolation across the two straddling
        strikes. Grid strike spacing is $1 on liquid names, so the error is well
        inside the IV gate's 5-vol-point threshold. Interpolate only if a markout
        shows the ATM reading is the binding constraint.
        """
        sql = f"""
            SELECT (call_iv + put_iv) / 2.0
              FROM {self._schema}.option_surface_grid_daily
             WHERE ticker = %s AND market_date = %s AND expiry = %s
               AND call_iv IS NOT NULL AND put_iv IS NOT NULL
               AND underlying_spot > 0
             ORDER BY abs(strike - underlying_spot)
             LIMIT 1
        """
        row = self._conn.execute(sql, (ticker, as_of, expiry)).fetchone()
        if not row or row[0] is None:
            return None
        iv = float(row[0])
        return iv / 100.0 if iv > 3.0 else iv

    # ------------------------------------------------------------ persistence

    def upsert_candidates(self, rows: Sequence[ThetaCandidate]) -> int:
        """Insert or refresh candidates, deleting stale marks on identity change.

        The contract identity (expiry, put_strike, call_strike) is part of the
        row but NOT part of the key. A rescan on the same (ticker, as_of) can
        legitimately pick a different structure — the chain moved, or a strike
        appeared. Overwriting the row while leaving `theta_harvester_markouts`
        untouched would silently re-attach P&L generated by the OLD structure
        to the NEW one, which is worse than having no markout at all: the
        numbers look valid and are not.

        So: whenever identity changes, the dependent marks are deleted in the
        SAME transaction and the candidate is re-marked from scratch on the
        next markout run. Identical re-scans (the common case) touch nothing.
        """
        if not rows:
            return 0
        cols = ", ".join(_CANDIDATE_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_CANDIDATE_COLUMNS))
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in _CANDIDATE_COLUMNS
            if c not in ("ticker", "as_of")
        )
        sql = f"""
            INSERT INTO {self._schema}.theta_harvester_candidates ({cols})
            VALUES ({placeholders})
            ON CONFLICT (ticker, as_of) DO UPDATE SET {updates}
        """
        # Identity changed => the existing marks describe a different trade.
        purge = f"""
            DELETE FROM {self._schema}.theta_harvester_markouts m
             USING {self._schema}.theta_harvester_candidates c
             WHERE m.ticker = c.ticker AND m.as_of = c.as_of
               AND c.ticker = %s AND c.as_of = %s
               AND (c.expiry, c.put_strike, c.call_strike) IS DISTINCT FROM (%s, %s, %s)
        """
        with self._conn.cursor() as cur:
            for cand in rows:
                s = cand.structure
                cur.execute(
                    purge,
                    (cand.ticker, cand.as_of, s.expiry, s.put.strike, s.call.strike),
                )
            cur.executemany(sql, [self._to_params(c) for c in rows])
        self._conn.commit()
        return len(rows)

    @staticmethod
    def _to_params(c: ThetaCandidate) -> tuple[Any, ...]:
        s = c.structure
        return (
            c.ticker,
            c.as_of,
            s.expiry,
            s.dte,
            s.put.strike,
            s.call.strike,
            c.spot,
            s.put.iv,
            s.call.iv,
            # The rate actually used to price the marks — never a literal. A
            # hardcoded 0.045 here would silently diverge from the entry mark
            # the moment RISK_FREE_RATE is changed or overridden, and the
            # markout would re-price at a rate the entry never used.
            c.risk_free_rate,
            c.put_mark,
            c.call_mark,
            c.entry_credit_theo,
            s.net_delta,
            s.theta,
            s.gamma,
            s.vega,
            c.score,
            c.weights_version,
            c.verdict,
            c.iv,
            c.hv20,
            c.hv60,
            c.iv_rv_edge,
            c.iv_rv_ratio,
            c.trend_20d_pct,
            c.range_score,
            c.dealer.label,
            c.dealer.net_gex,
            c.dealer.gex_flip,
            c.gates["delta_near_zero"],
            c.gates["iv_rich_vs_rv"],
            c.gates["dealer_support"],
            c.gates["theta_positive"],
            c.gates["gamma_controlled"],
            c.gates["range_bound"],
        )

    def set_ib_credit(
        self, ticker: str, as_of: date, *, credit: float, source: str
    ) -> None:
        sql = f"""
            UPDATE {self._schema}.theta_harvester_candidates
               SET credit_ib = %s, credit_source = %s, credit_quoted_at = now()
             WHERE ticker = %s AND as_of = %s
        """
        self._conn.execute(sql, (credit, source, ticker, as_of))
        self._conn.commit()

    # ------------------------------------------------------------------ reads

    def latest_as_of(self) -> date | None:
        sql = f"SELECT MAX(as_of) FROM {self._schema}.theta_harvester_candidates"
        row = self._conn.execute(sql).fetchone()
        return row[0] if row else None

    def read_candidates(
        self, as_of: date | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        target = as_of or self.latest_as_of()
        if target is None:
            return []
        sql = f"""
            SELECT * FROM {self._schema}.theta_harvester_candidates
             WHERE as_of = %s ORDER BY score DESC, ticker ASC LIMIT %s
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (target, limit)).fetchall()
