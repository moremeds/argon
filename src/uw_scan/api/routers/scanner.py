"""GET /api/scanner - read-only assembler over warm store.

GET /api/scanner/discover - live read-through of the market-wide flow-alerts
feed. One UW request per call (or zero, if a successful run finished within
the freshness window — see ``scanner_discover_freshness_seconds``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings, get_uw_client
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.api.models.scanner import (
    DiscoveryCandidate as RespDiscoveryCandidate,
)
from uw_scan.api.models.scanner import (
    DiscoveryResponse,
    ScannerCandidate,
    ScannerContextFlag,
    ScannerGatedTicker,
    ScannerGatesStatus,
    ScannerResponse,
    ScannerSignalHit,
)
from uw_scan.config import Settings
from uw_scan.normalize import normalize_flow_alerts
from uw_scan.scanner.discovery import discover_from_alerts
from uw_scan.scanner.models import (
    ContextFlag as DCContextFlag,
)
from uw_scan.scanner.models import (
    ScanCandidate as DCScanCandidate,
)
from uw_scan.scanner.models import (
    SignalHit as DCSignalHit,
)
from uw_scan.scanner.ranking import build_candidate, rank_candidates
from uw_scan.sources.uw import fetch_market_flow_alerts
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["scanner"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _latest_scanner_runs_per_ticker(
    repo: Repository, *, freshness_hours: int
) -> list[dict[str, Any]]:
    """One row per watchlist ticker for the latest scanner-producing run."""
    sql = """
        SELECT DISTINCT ON (w.ticker)
          w.ticker,
          r.run_id,
          r.finished_at AS scanned_at,
          c.spot
        FROM uw_scan.watchlist w
        LEFT JOIN uw_scan.scan_runs r
          ON r.ticker = w.ticker
         AND r.status = 'ok'
         AND r.finished_at >= NOW() - %s::interval
         AND EXISTS (
           SELECT 1 FROM uw_scan.signal_gates g
           WHERE g.run_id = r.run_id
         )
        LEFT JOIN uw_scan.watchlist_card c ON c.ticker = w.ticker
        WHERE w.removed_at IS NULL
        ORDER BY w.ticker, r.finished_at DESC NULLS LAST
    """
    with repo.conn.cursor() as cur:
        cur.execute(sql, (f"{freshness_hours} hours",))
        rows = cur.fetchall()
        cols = [c.name for c in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _hits_to_dc(rows: list[dict[str, Any]], ticker: str) -> list[DCSignalHit]:
    return [
        DCSignalHit(
            ticker=ticker,
            signal_type=r["signal_type"],
            tier=int(r["tier"]),
            score=Decimal(str(r["score"])),
            evidence=dict(r["evidence"]) if r["evidence"] else {},
            freshness=r["freshness"],
        )
        for r in rows
    ]


def _flags_to_dc(rows: list[dict[str, Any]], ticker: str) -> list[DCContextFlag]:
    return [
        DCContextFlag(
            ticker=ticker,
            layer=r["layer"],
            label=r["label"],
            value=Decimal(str(r["value"])) if r["value"] is not None else None,
        )
        for r in rows
    ]


def _dc_to_response_hit(h: DCSignalHit) -> ScannerSignalHit:
    return ScannerSignalHit(
        signal_type=h.signal_type,  # type: ignore[arg-type]
        tier=h.tier,
        score=h.score,
        evidence=h.evidence,
        freshness=h.freshness,
    )


def _dc_to_response_flag(f: DCContextFlag) -> ScannerContextFlag:
    return ScannerContextFlag(
        layer=f.layer,  # type: ignore[arg-type]
        label=f.label,
        value=f.value,
    )


@router.get("", response_model=ScannerResponse)
def get_scanner(
    tier_1_only: bool = Query(False),
    type_f_only: bool = Query(False),
    sector: str | None = Query(None),
    freshness_hours: int | None = Query(None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ScannerResponse:
    sigs = SignalsRepository(repo.conn, schema=settings.db_schema)
    fh = (
        freshness_hours
        if freshness_hours is not None
        else settings.scanner_freshness_hours
    )

    latest = _latest_scanner_runs_per_ticker(repo, freshness_hours=fh)

    with repo.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM uw_scan.watchlist WHERE removed_at IS NULL")
        scanned_universe_size = int(cur.fetchone()[0])

    candidates: list[DCScanCandidate] = []
    # Kept for response compatibility; regime no longer suppresses scanner rows.
    gated: list[ScannerGatedTicker] = []

    for row in latest:
        ticker = row["ticker"]
        run_id = row.get("run_id")
        if run_id is None:
            continue

        gate = dict(
            sigs.fetch_gate_for_run(run_id, ticker)
            or {
                "earnings": "pass",
                "liquidity": "pass",
                "regime": "pass",
            }
        )
        # Force pass even if a stale regime=block row was persisted by old code.
        gate["regime"] = "pass"

        hit_rows = sigs.fetch_hits_for_run(run_id, ticker)
        flag_rows = sigs.fetch_context_flags_for_run(run_id, ticker)
        cand = build_candidate(
            ticker=ticker,
            hits=_hits_to_dc(hit_rows, ticker),
            context_flags=_flags_to_dc(flag_rows, ticker),
            gates=gate,
        )
        if cand is None:
            continue
        candidates.append(cand)

    ranked = rank_candidates(candidates)

    if tier_1_only:
        ranked = [c for c in ranked if any(h.tier == 1 for h in c.hits)]
    if type_f_only:
        ranked = [c for c in ranked if c.is_type_f]

    if sector:
        with repo.conn.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM uw_scan.watchlist WHERE sector = %s",
                (sector,),
            )
            ok = {row[0] for row in cur.fetchall()}
        ranked = [c for c in ranked if c.ticker in ok]

    spot_map = {row["ticker"]: row.get("spot") for row in latest}
    scanned_at_map = {row["ticker"]: row.get("scanned_at") for row in latest}

    response_candidates = [
        ScannerCandidate(
            ticker=c.ticker,
            spot=spot_map.get(c.ticker),
            is_type_f=c.is_type_f,
            raw_score=c.raw_score,
            confluence_score=c.confluence_score,
            final_score=c.final_score,
            hits=[_dc_to_response_hit(h) for h in c.hits],
            context_flags=[_dc_to_response_flag(f) for f in c.context_flags],
            gates=ScannerGatesStatus(
                earnings=c.gates["earnings"],  # type: ignore[arg-type]
                liquidity=c.gates["liquidity"],  # type: ignore[arg-type]
                regime=c.gates["regime"],  # type: ignore[arg-type]
            ),
            bias=c.bias,
            bias_strength=c.bias_strength,
            setup=c.setup,
            setup_reason=c.setup_reason,
            scanned_at=scanned_at_map.get(c.ticker) or _now_utc(),
        )
        for c in ranked
    ]

    return ScannerResponse(
        scanned_universe_size=scanned_universe_size,
        candidates_with_hits=len(response_candidates),
        candidates=response_candidates,
        gated=gated,
        generated_at=_now_utc(),
    )


_DISCOVER_SENTINEL_TICKER = "_DISCOVER"


def _recent_discover_payload(
    repo: Repository, *, freshness_seconds: int
) -> dict | None:
    """Return the raw flow-alerts payload from the most recent successful
    _DISCOVER run within the freshness window, or None.

    Lets concurrent /discover requests share one UW call — burst clients see
    the same cached response until the window expires. Querying raw_payloads
    keeps the cache derivation pure (re-runs discover_from_alerts) so threshold
    knobs apply immediately when changed without waiting for the window.
    """
    if freshness_seconds <= 0:
        return None
    sql = """
        SELECT p.payload_jsonb
        FROM uw_scan.scan_runs r
        JOIN uw_scan.api_request_audit a ON a.run_id = r.run_id
        JOIN uw_scan.raw_payloads p ON p.audit_id = a.audit_id
        WHERE r.ticker = %s
          AND r.status = 'ok'
          AND r.finished_at >= NOW() - %s::interval
          AND a.endpoint_slug = %s
        ORDER BY r.finished_at DESC, a.audit_id DESC
        LIMIT 1
    """
    with repo.conn.cursor() as cur:
        cur.execute(
            sql,
            (
                _DISCOVER_SENTINEL_TICKER,
                f"{freshness_seconds} seconds",
                EndpointSlug.FLOW_ALERTS.value,
            ),
        )
        row = cur.fetchone()
    return row[0] if row else None


@router.get("/discover", response_model=DiscoveryResponse)
def get_scanner_discover(
    limit: int = Query(20, ge=1, le=50),
    alerts_limit: int = Query(200, ge=50, le=500),
    repo: Repository = Depends(get_repo),
    client: UwClient = Depends(get_uw_client),
    settings: Settings = Depends(get_settings),
) -> DiscoveryResponse:
    """Pull market-wide flow alerts, run DCF per ticker, exclude watchlist, top-N."""
    today = datetime.now(timezone.utc).date()

    # Cache: serve a re-derived response from the most recent successful run
    # within the freshness window. Skips the UW call entirely so concurrent
    # page loads / auto-refresh don't burst the rate budget.
    cached_payload = _recent_discover_payload(
        repo, freshness_seconds=settings.scanner_discover_freshness_seconds
    )
    if cached_payload is not None:
        alerts = normalize_flow_alerts(cached_payload)
        watchlist_tickers = {r.ticker for r in repo.list_active_watchlist()}
        candidates, earnings_unknown_dropped = discover_from_alerts(
            alerts=alerts,
            today=today,
            watchlist_tickers=watchlist_tickers,
            min_premium_usd=settings.scanner_discover_min_premium_usd,
            min_ask_side=settings.scanner_discover_min_ask_side,
            max_moneyness=settings.scanner_dcf_max_moneyness,
            min_dte=settings.scanner_dcf_min_dte,
            earnings_window_days=settings.scanner_earnings_window_days,
            limit=limit,
        )
        return _build_discover_response(
            candidates=candidates,
            alerts_pulled=len(alerts),
            earnings_unknown_dropped=earnings_unknown_dropped,
        )

    # Sentinel ticker for the scan_runs row — discover is market-wide, not per-ticker,
    # but the audit-first rule (sources/CLAUDE.md) requires a run_id.
    run_id = repo.insert_scan_run(_DISCOVER_SENTINEL_TICKER, notes="scanner_discover")
    try:
        try:
            alerts = fetch_market_flow_alerts(client, repo, run_id, limit=alerts_limit)
        except Exception as exc:
            logger.exception("scanner_discover fetch failed: %r", exc)
            _safe_finish_run(repo, run_id, status="fail")
            raise HTTPException(
                status_code=502, detail=f"market-wide flow-alerts fetch failed: {exc}"
            ) from exc

        watchlist_tickers = {r.ticker for r in repo.list_active_watchlist()}
        # Discovery uses LOOSER premium + ask thresholds than the watchlist
        # DCF — see config.py comment on scanner_discover_*. Moneyness/DTE/
        # earnings stay the same: those filter for valid options, not conviction.
        candidates, earnings_unknown_dropped = discover_from_alerts(
            alerts=alerts,
            today=today,
            watchlist_tickers=watchlist_tickers,
            min_premium_usd=settings.scanner_discover_min_premium_usd,
            min_ask_side=settings.scanner_discover_min_ask_side,
            max_moneyness=settings.scanner_dcf_max_moneyness,
            min_dte=settings.scanner_dcf_min_dte,
            earnings_window_days=settings.scanner_earnings_window_days,
            limit=limit,
        )

        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
    except HTTPException:
        raise
    except Exception:
        _safe_finish_run(repo, run_id, status="fail")
        raise

    return _build_discover_response(
        candidates=candidates,
        alerts_pulled=len(alerts),
        earnings_unknown_dropped=earnings_unknown_dropped,
    )


def _build_discover_response(
    *,
    candidates: list,
    alerts_pulled: int,
    earnings_unknown_dropped: int,
) -> DiscoveryResponse:
    return DiscoveryResponse(
        candidates=[
            RespDiscoveryCandidate(
                ticker=c.ticker,
                hit=ScannerSignalHit(
                    signal_type=c.hit.signal_type,  # type: ignore[arg-type]
                    tier=c.hit.tier,
                    score=c.hit.score,
                    evidence=c.hit.evidence,
                    freshness=c.hit.freshness,
                ),
                bias=c.bias,
                bias_strength=c.bias_strength,
                alert_count=c.alert_count,
                sector=c.sector,
                latest_alert_at=c.latest_alert_at,
            )
            for c in candidates
        ],
        fetched_at=_now_utc(),
        alerts_pulled=alerts_pulled,
        earnings_unknown_dropped=earnings_unknown_dropped,
    )


def _safe_finish_run(repo: Repository, run_id: int, *, status: str) -> None:
    """Mark a scan_run finished and commit; never let cleanup mask the
    original exception (MINOR-3 in 2026-05-18 self-review)."""
    try:
        repo.finish_scan_run(run_id, status=status)
        repo.conn.commit()
    except Exception as cleanup_exc:
        logger.exception(
            "scanner_discover cleanup failed for run_id=%d: %r",
            run_id,
            cleanup_exc,
        )
