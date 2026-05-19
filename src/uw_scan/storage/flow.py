"""Flow events + flow_alerts_daily_rollup writes.

Module-level helpers (_flow_footprint_label, _aggressor_label_confidence)
are used by insert_flow_events AND by scripts/backfill_flow_footprint.py
(which imports them via `from uw_scan.storage.repository import …`). The
script's import path must keep working, so repository.py re-exports both
helpers from this module.

_flow_alert_trade_date is module-level here because it doesn't use self —
upsert_flow_alerts_daily_rollup calls it as a plain function."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from .. import models


def _flow_footprint_label(row: models.FlowAlert) -> str:
    ask = row.total_ask_side_prem or Decimal(0)
    bid = row.total_bid_side_prem or Decimal(0)
    total = row.total_premium or ask + bid
    ask_ratio = ask / total if total and total > 0 else None
    if row.has_sweep and ask_ratio is not None and ask_ratio >= Decimal("0.65"):
        return "directional_whale"
    if row.has_multileg:
        return "hedge_flow"
    if row.has_floor:
        return "dealer_hedge"
    if ask_ratio is not None and Decimal("0.40") <= ask_ratio <= Decimal("0.60"):
        return "gamma_scalper"
    return "unclassified"


def _aggressor_label_confidence(row: models.FlowAlert) -> Decimal | None:
    ask = row.total_ask_side_prem or Decimal(0)
    bid = row.total_bid_side_prem or Decimal(0)
    total = row.total_premium or ask + bid
    if total is None or total <= 0:
        return None
    dominant_side_ratio = max(ask, bid) / total
    structure_penalty = Decimal("0.05") if row.has_multileg else Decimal(0)
    confidence = min(
        Decimal("1"), max(Decimal("0"), dominant_side_ratio - structure_penalty)
    )
    return confidence.quantize(Decimal("0.01"))


def _flow_alert_trade_date(rows: list[models.FlowAlert]) -> _date:
    """Pick the trade date for a batch of flow alerts. Was a Repository method
    in pre-split repository.py but didn't use self — moved to module-level."""
    market_tz = ZoneInfo("America/New_York")
    for row in rows:
        if row.created_at is None:
            continue
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=market_tz)
        return created_at.astimezone(market_tz).date()
    return datetime.now(market_tz).date()


def _flow_event_params(
    run_id: int, rows: Iterable[models.FlowAlert]
) -> list[tuple[Any, ...]]:
    return [
        (
            run_id,
            r.id,
            r.ticker,
            r.option_chain,
            r.expiry,
            r.strike,
            r.type,
            r.price,
            r.underlying_price,
            r.total_size,
            r.total_premium,
            r.total_ask_side_prem,
            r.total_bid_side_prem,
            r.volume,
            r.open_interest,
            r.volume_oi_ratio,
            r.has_sweep,
            r.has_floor,
            r.has_multileg,
            r.all_opening_trades,
            r.iv_start,
            r.iv_end,
            r.alert_rule,
            r.flow_footprint_label or _flow_footprint_label(r),
            r.aggressor_label_confidence
            if r.aggressor_label_confidence is not None
            else _aggressor_label_confidence(r),
            r.rule_id,
            r.sector,
            r.issue_type,
            r.next_earnings_date,
            r.created_at,
        )
        for r in rows
    ]


class _FlowMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_flow_events(
        self, run_id: int, ticker: str, alerts: Iterable[models.FlowAlert]
    ) -> int:
        rows = list(alerts)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.flow_events ("
            "run_id, alert_id, ticker, option_chain, expiry, strike, option_type, "
            "price, underlying_price, total_size, total_premium, "
            "total_ask_side_prem, total_bid_side_prem, volume, open_interest, "
            "volume_oi_ratio, has_sweep, has_floor, has_multileg, "
            "all_opening_trades, iv_start, iv_end, alert_rule, "
            "flow_footprint_label, aggressor_label_confidence, "
            "rule_id, sector, issue_type, next_earnings_date, created_at) VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, alert_id) DO NOTHING"
        )
        params = _flow_event_params(run_id, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def upsert_flow_alerts_daily_rollup(
        self,
        *,
        run_id: int,
        ticker: str,
        alerts: Iterable[models.FlowAlert],
        alert_limit: int,
        trade_date: _date | None = None,
    ) -> None:
        rows = list(alerts)
        if trade_date is None:
            trade_date = _flow_alert_trade_date(rows)

        bull_premium = Decimal("0")
        bear_premium = Decimal("0")
        ask_side_premium = Decimal("0")
        bid_side_premium = Decimal("0")
        total_premium = Decimal("0")
        rules: Counter[str] = Counter()

        for row in rows:
            premium = row.total_premium or Decimal("0")
            total_premium += premium
            opt_type = (row.type or "").lower()
            if opt_type == "call":
                bull_premium += premium
            elif opt_type == "put":
                bear_premium += premium
            ask_side_premium += row.total_ask_side_prem or Decimal("0")
            bid_side_premium += row.total_bid_side_prem or Decimal("0")
            if row.alert_rule:
                rules[row.alert_rule] += 1

        top_alert_rule = rules.most_common(1)[0][0] if rules else None

        sql = (
            f"INSERT INTO {self._schema}.flow_alerts_daily_rollup ("
            "ticker, trade_date, run_id, alert_count, alert_count_is_limited, "
            "total_premium, bull_premium, bear_premium, ask_side_premium, "
            "bid_side_premium, top_alert_rule) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, trade_date) DO UPDATE SET "
            "run_id=EXCLUDED.run_id, alert_count=EXCLUDED.alert_count, "
            "alert_count_is_limited=EXCLUDED.alert_count_is_limited, "
            "total_premium=EXCLUDED.total_premium, "
            "bull_premium=EXCLUDED.bull_premium, "
            "bear_premium=EXCLUDED.bear_premium, "
            "ask_side_premium=EXCLUDED.ask_side_premium, "
            "bid_side_premium=EXCLUDED.bid_side_premium, "
            "top_alert_rule=EXCLUDED.top_alert_rule, updated_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ticker.upper(),
                    trade_date,
                    run_id,
                    len(rows),
                    len(rows) >= alert_limit,
                    total_premium,
                    bull_premium,
                    bear_premium,
                    ask_side_premium,
                    bid_side_premium,
                    top_alert_rule,
                ),
            )
