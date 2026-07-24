"""Recurring capture for the 5 UW historical-alpha datasets.

Each ``capture_*_for(client, repo, alpha_repo, run_id, ticker, market_date)``
core function fetches the endpoint(s) for one ticker/date, aligns them as-of
``market_date`` (short interest / vol signals carry forward; FTDs and intraday
prints are exact-date), and writes the merged row(s). The core functions are
shared by the nightly wrappers AND the data_gap_healer adapters (Phase 4).

``raw_jsonb`` stores the assembled normalized snapshot (``model_dump``); the
byte-exact endpoint envelope already lives in ``raw_payloads`` via ``_fetch_json``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.uw import (
    fetch_darkpool_prints,
    fetch_ftds,
    fetch_gex_levels,
    fetch_greek_flow,
    fetch_lit_flow,
    fetch_net_prem_ticks,
    fetch_short_interest_history,
    fetch_volatility_anomaly,
    fetch_volatility_character,
    fetch_volatility_vrp,
    fetch_volumes_by_exchange,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository

logger = logging.getLogger(__name__)

_EXPIRY_SENTINEL = date(
    1, 1, 1
)  # matches migration-108 default for non-per-expiry bars
_PRINT_LIMIT = 500  # matches the fetcher default; capture logs when a response hits it

GEX_LEVELS_CAPTURE_LOCK = 10801  # migration 108 + slot 01
VOLATILITY_CAPTURE_LOCK = 10802
SHORT_PRESSURE_CAPTURE_LOCK = 10803
INTRADAY_FLOW_CAPTURE_LOCK = 10804
DARK_LIT_CAPTURE_LOCK = 10805


def _pick_asof(rows: Sequence, target: date, attr: str = "date"):
    """Row with the greatest date <= target (carry-forward), else None."""
    best = None
    best_d = None
    for r in rows:
        d = getattr(r, attr, None)
        if d is None or d > target:
            continue
        if best_d is None or d > best_d:
            best, best_d = r, d
    return best


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Per-ticker/date capture cores (shared by nightly wrappers + heal adapters)
# --------------------------------------------------------------------------- #
def capture_gex_levels_for(
    client: UwClient,
    repo: Repository,
    alpha_repo: UwHistoricalAlphaRepository,
    run_id: int,
    ticker: str,
    market_date: date,
) -> int:
    row = fetch_gex_levels(client, repo, run_id, ticker, market_date)
    if row is None:
        return 0
    d = row.model_dump()
    alpha_repo.upsert_gex_levels([{**d, "raw_jsonb": row.model_dump(mode="json")}])
    return 1


def capture_volatility_signal_for(
    client: UwClient,
    repo: Repository,
    alpha_repo: UwHistoricalAlphaRepository,
    run_id: int,
    ticker: str,
    market_date: date,
) -> int:
    anomaly = _pick_asof(
        fetch_volatility_anomaly(client, repo, run_id, ticker, market_date), market_date
    )
    character = _pick_asof(
        fetch_volatility_character(client, repo, run_id, ticker, market_date),
        market_date,
    )
    vrp = _pick_asof(
        fetch_volatility_vrp(client, repo, run_id, ticker, market_date), market_date
    )
    if anomaly is None and character is None and vrp is None:
        return 0
    mask = [
        name
        for name, obj in (("anomaly", anomaly), ("character", character), ("vrp", vrp))
        if obj is not None
    ]
    raw = {
        "anomaly": anomaly.model_dump(mode="json") if anomaly else None,
        "character": character.model_dump(mode="json") if character else None,
        "vrp": vrp.model_dump(mode="json") if vrp else None,
    }
    alpha_repo.upsert_volatility_signal(
        [
            {
                "ticker": ticker,
                "market_date": market_date,
                "anomaly_direction": anomaly.direction if anomaly else None,
                "anomaly_score": anomaly.score if anomaly else None,
                "vol_character": character.character if character else None,
                "half_life_days": character.half_life_days if character else None,
                "hurst_rv": character.hurst_rv if character else None,
                "vrp_rank": vrp.rank if vrp else None,
                "risk_premium": vrp.risk_premium if vrp else None,
                "source_mask": mask,
                "raw_jsonb": raw,
            }
        ]
    )
    return 1


def capture_short_pressure_for(
    client: UwClient,
    repo: Repository,
    alpha_repo: UwHistoricalAlphaRepository,
    run_id: int,
    ticker: str,
    market_date: date,
) -> int:
    # short interest carries forward (bi-monthly settlements) -> as-of <= target
    si_hist = fetch_short_interest_history(client, repo, run_id, ticker)
    si_row = None
    si_date = None
    for r in si_hist:
        d = r.get("market_date")
        d = date.fromisoformat(d[:10]) if isinstance(d, str) else None
        if d is None or d > market_date:
            continue
        if si_date is None or d > si_date:
            si_row, si_date = r, d
    # FTDs are point-in-time events -> exact date only
    ftd_qty = next(
        (
            f.quantity
            for f in fetch_ftds(client, repo, run_id, ticker)
            if f.date == market_date
        ),
        None,
    )
    # short volume is per-exchange for the day -> sum across exchanges
    vol_rows = [
        v
        for v in fetch_volumes_by_exchange(client, repo, run_id, ticker)
        if v.date == market_date
    ]
    short_vol = (
        sum((v.short_volume or Decimal(0) for v in vol_rows), Decimal(0))
        if vol_rows
        else None
    )
    total_vol = (
        sum((v.total_volume or Decimal(0) for v in vol_rows), Decimal(0))
        if vol_rows
        else None
    )
    ratio = (short_vol / total_vol) if (short_vol is not None and total_vol) else None
    if si_row is None and ftd_qty is None and not vol_rows:
        return 0
    si = si_row or {}
    alpha_repo.upsert_short_pressure(
        [
            {
                "ticker": ticker,
                "market_date": market_date,
                "short_interest": _dec(si.get("short_interest")),
                "si_float": _dec(si.get("si_float")),
                "si_float_with_synth_long_pct_of_total_shares": _dec(
                    si.get("si_float_with_synth_long_pct_of_total_shares")
                ),
                "days_to_cover": _dec(si.get("days_to_cover")),
                "fee_rate": _dec(si.get("fee_rate")),
                "rebate_rate": _dec(si.get("rebate_rate")),
                "short_shares_available": _dec(si.get("short_shares_available")),
                "total_float": _dec(si.get("total_float")),
                "ftd_quantity": ftd_qty,
                "short_volume": short_vol,
                "total_volume": total_vol,
                "short_volume_ratio": ratio,
                "raw_jsonb": {
                    "interest": si_row,
                    "ftd_quantity": str(ftd_qty) if ftd_qty is not None else None,
                    "volume_rows": len(vol_rows),
                },
            }
        ]
    )
    return 1


def capture_intraday_flow_for(
    client: UwClient,
    repo: Repository,
    alpha_repo: UwHistoricalAlphaRepository,
    run_id: int,
    ticker: str,
    market_date: date,
) -> int:
    net = fetch_net_prem_ticks(
        client, repo, run_id, ticker, market_date, limit=_PRINT_LIMIT
    )
    greek = fetch_greek_flow(client, repo, run_id, ticker, market_date)
    if len(net) >= _PRINT_LIMIT:
        logger.warning(
            "uw_alpha intraday net-prem-ticks %s %s hit limit=%d (truncated)",
            ticker,
            market_date,
            _PRINT_LIMIT,
        )
    rows = []
    for r in net:
        rows.append(
            {
                **r.model_dump(),
                "ticker": ticker,
                "market_date": market_date,
                "source": "net_prem_ticks",
                "expiry": _EXPIRY_SENTINEL,
                "raw_jsonb": r.model_dump(mode="json"),
            }
        )
    for r in greek:
        rows.append(
            {
                **r.model_dump(),
                "ticker": ticker,
                "market_date": market_date,
                "source": "greek_flow",
                "expiry": _EXPIRY_SENTINEL,
                "raw_jsonb": r.model_dump(mode="json"),
            }
        )
    return alpha_repo.insert_intraday_flow_bars(rows)


def capture_dark_lit_for(
    client: UwClient,
    repo: Repository,
    alpha_repo: UwHistoricalAlphaRepository,
    run_id: int,
    ticker: str,
    market_date: date,
) -> int:
    dark = fetch_darkpool_prints(
        client, repo, run_id, ticker, market_date, limit=_PRINT_LIMIT
    )
    lit = fetch_lit_flow(client, repo, run_id, ticker, market_date, limit=_PRINT_LIMIT)
    for name, prints in (("darkpool", dark), ("lit_flow", lit)):
        if len(prints) >= _PRINT_LIMIT:
            logger.warning(
                "uw_alpha %s prints %s %s hit limit=%d (truncated)",
                name,
                ticker,
                market_date,
                _PRINT_LIMIT,
            )
    rows = []
    for source, prints in (("darkpool", dark), ("lit_flow", lit)):
        for r in prints:
            rows.append(
                {
                    **r.model_dump(),
                    "source": source,
                    "market_date": market_date,
                    "raw_jsonb": r.model_dump(mode="json"),
                }
            )
    return alpha_repo.insert_dark_lit_prints(rows)


# --------------------------------------------------------------------------- #
# Nightly wrappers (one per table) — advisory-locked watchlist sweep.
# --------------------------------------------------------------------------- #
_CaptureFn = Callable[
    [UwClient, Repository, UwHistoricalAlphaRepository, int, str, date], int
]


def _run_capture(
    name: str,
    capture_fn: _CaptureFn,
    lock_key: int,
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None,
    market_date: date | None = None,
) -> dict[str, int]:
    if not repo.try_advisory_lock(lock_key):
        logger.info("%s: lock held; skipping this tick", name)
        return {"tickers": 0, "rows": 0, "errors": 0}
    alpha = UwHistoricalAlphaRepository(repo.conn, schema=settings.db_schema)
    if market_date is None:
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
    tickers_done = rows_written = errors = 0
    try:
        for card in repo.list_watchlist_cards():
            ticker = card.ticker.upper()
            if ticker_filter is not None and not ticker_filter(ticker):
                continue
            run_id = repo.insert_scan_run(ticker, notes=name)
            try:
                n = capture_fn(client, repo, alpha, run_id, ticker, market_date)
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
                rows_written += n
                tickers_done += 1
            except Exception as exc:  # noqa: BLE001
                repo.conn.rollback()
                errors += 1
                logger.warning("%s %s failed: %s", name, ticker, repr(exc))
    finally:
        repo.release_advisory_lock(lock_key)
    summary = {"tickers": tickers_done, "rows": rows_written, "errors": errors}
    logger.info("%s complete %s", name, summary)
    return summary


def gex_levels_capture(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None = None,
    lock_key: int = GEX_LEVELS_CAPTURE_LOCK,
    market_date: date | None = None,
) -> dict[str, int]:
    return _run_capture(
        "uw_alpha_gex_capture",
        capture_gex_levels_for,
        lock_key,
        repo=repo,
        client=client,
        settings=settings,
        ticker_filter=ticker_filter,
        market_date=market_date,
    )


def volatility_signal_capture(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None = None,
    lock_key: int = VOLATILITY_CAPTURE_LOCK,
    market_date: date | None = None,
) -> dict[str, int]:
    return _run_capture(
        "uw_alpha_volatility_capture",
        capture_volatility_signal_for,
        lock_key,
        repo=repo,
        client=client,
        settings=settings,
        ticker_filter=ticker_filter,
        market_date=market_date,
    )


def short_pressure_capture(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None = None,
    lock_key: int = SHORT_PRESSURE_CAPTURE_LOCK,
    market_date: date | None = None,
) -> dict[str, int]:
    return _run_capture(
        "uw_alpha_short_pressure_capture",
        capture_short_pressure_for,
        lock_key,
        repo=repo,
        client=client,
        settings=settings,
        ticker_filter=ticker_filter,
        market_date=market_date,
    )


def intraday_flow_capture(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None = None,
    lock_key: int = INTRADAY_FLOW_CAPTURE_LOCK,
    market_date: date | None = None,
) -> dict[str, int]:
    return _run_capture(
        "uw_alpha_intraday_flow_capture",
        capture_intraday_flow_for,
        lock_key,
        repo=repo,
        client=client,
        settings=settings,
        ticker_filter=ticker_filter,
        market_date=market_date,
    )


def dark_lit_capture(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None = None,
    lock_key: int = DARK_LIT_CAPTURE_LOCK,
    market_date: date | None = None,
) -> dict[str, int]:
    return _run_capture(
        "uw_alpha_dark_lit_capture",
        capture_dark_lit_for,
        lock_key,
        repo=repo,
        client=client,
        settings=settings,
        ticker_filter=ticker_filter,
        market_date=market_date,
    )
