"""Live-quote primitives for the regime scanners (CRI / VCG live compute).

The live compute splices the latest WS quote onto the vol_index_daily
history as TODAY's provisional close, then re-runs the existing pure
run_analysis orchestrators. Symbols without a fresh quote (e.g. COR1M if
IB never ticks it, or any index while on the massive stocks-only fallback)
are carried forward from their last daily close so the inner-join
alignment doesn't drop the session entirely.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from uw_scan.storage.repository import Repository

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class LiveQuote:
    symbol: str
    price: float
    quoted_at: datetime
    source: str | None


def load_live_quotes(
    repo: Repository,
    symbols: Sequence[str],
    *,
    max_age_seconds: int,
    now: datetime | None = None,
) -> dict[str, LiveQuote]:
    """Latest intraday_quote per symbol, dropping anything older than
    ``max_age_seconds``. Deterministic: pass ``now`` in tests."""
    now = now or datetime.now(timezone.utc)
    out: dict[str, LiveQuote] = {}
    for row in repo.get_intraday_quotes([s.upper() for s in symbols]):
        if (now - row.quoted_at).total_seconds() > max_age_seconds:
            continue
        out[row.ticker] = LiveQuote(
            symbol=row.ticker,
            price=float(row.price),
            quoted_at=row.quoted_at,
            source=row.source,
        )
    return out


def live_session_date(quotes: Mapping[str, LiveQuote]) -> date | None:
    """ET trading date implied by the freshest quote, or None when empty."""
    if not quotes:
        return None
    freshest = max(q.quoted_at for q in quotes.values())
    return freshest.astimezone(_ET).date()


def splice_session_value(
    series: dict[date, float], price: float, session_date: date
) -> dict[date, float]:
    """Copy ``series`` with ``session_date`` set to the live price (replaces
    an already-synced lake close for the same date — live wins intraday)."""
    out = dict(series)
    out[session_date] = price
    return out


def carry_forward(
    series: dict[date, float], session_date: date
) -> tuple[dict[date, float], bool]:
    """If ``series`` has no value for ``session_date``, repeat its latest
    close. Returns (series, was_carried)."""
    if not series or session_date in series:
        return series, False
    out = dict(series)
    out[session_date] = series[max(series)]
    return out, True


def quotes_payload(quotes: Mapping[str, LiveQuote]) -> dict[str, dict]:
    """JSON-serializable live_quotes block persisted into snapshot payloads."""
    return {
        sym: {
            "price": q.price,
            "quoted_at": q.quoted_at.isoformat(),
            "source": q.source,
        }
        for sym, q in quotes.items()
    }
