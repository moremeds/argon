"""Market-wide discovery — surface tickers outside the watchlist with strong DCF.

Consumes the market-wide flow-alerts feed (/api/option-trades/flow-alerts with no
ticker filter), groups alerts by ticker, runs the existing DCF detector per
group at the SAME thresholds the watchlist scanner uses, and returns the top-N
non-watchlist candidates ranked by DCF score.

Only DCF is run here. Dark Pool, EIC, and GEX need per-ticker context
(dark-pool history, IV rank, GEX curve) which only exists for watchlist
tickers that have been deep-scanned. Discovery is the on-ramp: a hit here
suggests "promote to watchlist + deep scan."
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.models import DiscoveryCandidate
from uw_scan.scanner.ranking import derive_bias
from uw_scan.scanner.signals import deep_conviction_flow


def _latest_created_at(alerts: Iterable[FlowAlert]):
    times = [a.created_at for a in alerts if a.created_at is not None]
    return max(times) if times else None


def _first_sector(alerts: Iterable[FlowAlert]) -> str | None:
    for a in alerts:
        if a.sector:
            return a.sector
    return None


def discover_from_alerts(
    *,
    alerts: Iterable[FlowAlert],
    today: date,
    watchlist_tickers: set[str],
    min_premium_usd: Decimal,
    min_ask_side: Decimal,
    max_moneyness: Decimal,
    min_dte: int,
    earnings_window_days: int,
    limit: int = 20,
) -> list[DiscoveryCandidate]:
    """Group alerts by ticker, run DCF per group, filter watchlist, sort, top-N."""
    watchlist = {t.upper() for t in watchlist_tickers}
    by_ticker: dict[str, list[FlowAlert]] = defaultdict(list)
    for a in alerts:
        if not a.ticker:
            continue
        ticker = a.ticker.upper()
        if ticker in watchlist:
            continue
        by_ticker[ticker].append(a)

    out: list[DiscoveryCandidate] = []
    for ticker, group in by_ticker.items():
        hit = deep_conviction_flow.detect(
            ticker=ticker,
            alerts=group,
            today=today,
            min_premium_usd=min_premium_usd,
            min_ask_side=min_ask_side,
            max_moneyness=max_moneyness,
            min_dte=min_dte,
            earnings_window_days=earnings_window_days,
        )
        if hit is None:
            continue
        bias, strength = derive_bias([hit])
        out.append(
            DiscoveryCandidate(
                ticker=ticker,
                hit=hit,
                bias=bias,
                bias_strength=strength,
                alert_count=int(hit.evidence.get("qualifying_alerts", 0)),
                sector=_first_sector(group),
                latest_alert_at=_latest_created_at(group),
            )
        )

    out.sort(key=lambda c: (-c.hit.score, c.ticker))
    return out[:limit]
