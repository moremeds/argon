"""Persistence for UW per-minute option-contract intraday bars. New domain — own file.

Mirrors the standalone-class pattern used by greek_exposure_repository.py and
vcg_snapshot_repository.py. Does not extend Repository (per repo policy on the
5,000-line repository.py — new domains stay out of it).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date

from psycopg import Connection

from ..models import OptionContractIntradayBucket


class OptionIntradayBucketRepository:
    """One bucket row per (option_symbol, trade_date, start_time).

    Upserts overwrite OHLC/volume/premium values — UW occasionally restates
    minute bars when late prints clear, and the freshest call wins.
    """

    _conn: Connection
    _schema: str

    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_buckets(
        self,
        option_symbol: str,
        trade_date: _date,
        buckets: Iterable[OptionContractIntradayBucket],
    ) -> int:
        rows = list(buckets)
        if not rows:
            return 0
        params = [
            {
                "option_symbol": option_symbol,
                "trade_date": trade_date,
                "start_time": b.start_time,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "avg_price": b.avg_price,
                "iv_high": b.iv_high,
                "iv_low": b.iv_low,
                "volume_ask_side": b.volume_ask_side,
                "volume_bid_side": b.volume_bid_side,
                "volume_mid_side": b.volume_mid_side,
                "volume_multi": b.volume_multi,
                "premium_ask_side": b.premium_ask_side,
                "premium_bid_side": b.premium_bid_side,
                "premium_mid_side": b.premium_mid_side,
                "premium_no_side": b.premium_no_side,
            }
            for b in rows
        ]
        sql = """
            INSERT INTO option_intraday_buckets
                (option_symbol, trade_date, start_time,
                 open, high, low, close, avg_price,
                 iv_high, iv_low,
                 volume_ask_side, volume_bid_side, volume_mid_side, volume_multi,
                 premium_ask_side, premium_bid_side, premium_mid_side, premium_no_side)
            VALUES
                (%(option_symbol)s, %(trade_date)s, %(start_time)s,
                 %(open)s, %(high)s, %(low)s, %(close)s, %(avg_price)s,
                 %(iv_high)s, %(iv_low)s,
                 %(volume_ask_side)s, %(volume_bid_side)s,
                 %(volume_mid_side)s, %(volume_multi)s,
                 %(premium_ask_side)s, %(premium_bid_side)s,
                 %(premium_mid_side)s, %(premium_no_side)s)
            ON CONFLICT (option_symbol, trade_date, start_time) DO UPDATE SET
                open             = EXCLUDED.open,
                high             = EXCLUDED.high,
                low              = EXCLUDED.low,
                close            = EXCLUDED.close,
                avg_price        = EXCLUDED.avg_price,
                iv_high          = EXCLUDED.iv_high,
                iv_low           = EXCLUDED.iv_low,
                volume_ask_side  = EXCLUDED.volume_ask_side,
                volume_bid_side  = EXCLUDED.volume_bid_side,
                volume_mid_side  = EXCLUDED.volume_mid_side,
                volume_multi     = EXCLUDED.volume_multi,
                premium_ask_side = EXCLUDED.premium_ask_side,
                premium_bid_side = EXCLUDED.premium_bid_side,
                premium_mid_side = EXCLUDED.premium_mid_side,
                premium_no_side  = EXCLUDED.premium_no_side
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def fetch_buckets(
        self,
        option_symbol: str,
        trade_date: _date,
    ) -> list[dict]:
        """All buckets for one contract on one session, ordered by start_time."""
        sql = """
            SELECT option_symbol, trade_date, start_time,
                   open, high, low, close, avg_price,
                   iv_high, iv_low,
                   volume_ask_side, volume_bid_side,
                   volume_mid_side, volume_multi,
                   premium_ask_side, premium_bid_side,
                   premium_mid_side, premium_no_side
              FROM option_intraday_buckets
             WHERE option_symbol = %s AND trade_date = %s
             ORDER BY start_time ASC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (option_symbol, trade_date))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
