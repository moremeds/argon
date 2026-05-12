"""Assemble a ScanReport from persisted scan_universe + scan_results rows.

Pure: reads from Repository only. Never touches the live API.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from ..models import ScanReport, ScanTickerResult
from ..storage.repository import Repository

logger = logging.getLogger(__name__)


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError) as exc:
        logger.debug("decimal coerce failed for %r: %s", value, repr(exc))
        return None


def _row_to_result(row: dict) -> ScanTickerResult:
    return ScanTickerResult(
        ticker=row["ticker"],
        setup_type=row.get("setup_type"),
        direction=row.get("direction"),
        score=_to_decimal(row.get("score")) or Decimal("0"),
        net_premium=_to_decimal(row.get("net_premium")),
        net_call_premium=_to_decimal(row.get("net_call_premium")),
        net_put_premium=_to_decimal(row.get("net_put_premium")),
        iv_rank=_to_decimal(row.get("iv_rank")),
        sector=row.get("sector"),
        relative_volume=_to_decimal(row.get("relative_volume")),
        gex_net_change=_to_decimal(row.get("gex_net_change")),
        variance_risk_premium=_to_decimal(row.get("variance_risk_premium")),
        total_open_interest=row.get("total_open_interest"),
        next_earnings_date=row.get("next_earnings_date"),
        signals_present=list(row.get("signals_present") or []),
        confirmations=list(row.get("confirmations") or []),
        warnings=list(row.get("warnings") or []),
        notes=row.get("notes") or "",
    )


def assemble_scan_report(run_id: int, repo: Repository) -> ScanReport:
    """Build a ScanReport from persisted scan_universe + scan_results."""
    universe = repo.fetch_scan_universe(run_id)
    rows = repo.fetch_scan_results(run_id)

    results = [_row_to_result(r) for r in rows]
    # fetch_scan_results already orders by score DESC, ticker ASC.
    top_pick = results[0].ticker if results else None
    universe_tickers = {u["ticker"] for u in universe}
    returned_tickers = {r.ticker for r in results}
    dropped = sorted(universe_tickers - returned_tickers)

    scan_date = None
    if rows:
        scan_date = rows[0].get("market_date")

    return ScanReport(
        run_id=run_id,
        generated_at=datetime.now(UTC),
        scan_date=scan_date,
        universe_size=len(universe_tickers),
        universe_returned=len(returned_tickers),
        results=results,
        dropped_tickers=dropped,
        top_pick=top_pick,
    )
