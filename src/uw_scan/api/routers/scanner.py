"""GET /api/scanner - read-only assembler over warm store.

GET /api/scanner/discover - thin read of the latest persisted discovery
snapshot. The market-wide edge-quality compute runs in the scheduled
``worker.jobs.discovery_scan`` job; this endpoint never calls UW.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from uw_scan.api.deps import get_repo, get_settings
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
from uw_scan.api.models.theta_harvester import (
    ThetaHarvesterCandidate,
    ThetaHarvesterQuoteResult,
    ThetaHarvesterResponse,
    ThetaHarvesterScanResult,
)
from uw_scan.config import Settings
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
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository

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
    # Deprecated-empty response key retained for compatibility. Regime no
    # longer suppresses scanner rows, and stale rows are silently dropped.
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
        # Force pass even if a legacy regime=block row was persisted by old code.
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


def _coerce_decimal(v) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


@router.get("/discover", response_model=DiscoveryResponse)
def get_scanner_discover(
    limit: int = Query(20, ge=1, le=50),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> DiscoveryResponse:
    """Thin read of the latest persisted discovery snapshot (compute is the job)."""
    sigs = SignalsRepository(repo.conn, schema=settings.db_schema)
    snap = sigs.fetch_latest_discovery_snapshot(limit=limit)
    if snap is None:
        return DiscoveryResponse(
            candidates=[],
            fetched_at=_now_utc(),
            scored_at=None,
            alerts_pulled=0,
            earnings_unknown_dropped=0,
        )

    candidates: list[RespDiscoveryCandidate] = []
    for r in snap["candidates"]:
        ev = r.get("evidence") or {}
        latest = ev.get("latest_alert_at")
        candidates.append(
            RespDiscoveryCandidate(
                ticker=r["ticker"],
                bias=r.get("bias") or "neutral",
                bias_strength=None,
                direction=r.get("direction"),
                score=_coerce_decimal(r.get("score")) or Decimal("0"),
                score_model=r["score_model"],
                score_breakdown=r.get("score_breakdown") or {},
                dp_direction=ev.get("dp_direction"),
                dp_strength=_coerce_decimal(ev.get("dp_strength")),
                dp_sustained_days=int(ev.get("dp_sustained_days", 0) or 0),
                confluence=bool(ev.get("confluence", False)),
                vol_oi=_coerce_decimal(ev.get("vol_oi")),
                sweeps=int(ev.get("sweeps", 0) or 0),
                alert_count=int(ev.get("alert_count", 0) or 0),
                spot=_coerce_decimal(r.get("spot_at_signal")),
                dp_status=ev.get("dp_status"),
                sector=ev.get("sector"),
                scored_at=r.get("scored_at"),
                latest_alert_at=datetime.fromisoformat(latest) if latest else None,
            )
        )

    return DiscoveryResponse(
        candidates=candidates,
        fetched_at=_now_utc(),
        scored_at=snap["scored_at"],
        alerts_pulled=snap["alerts_pulled"],
        earnings_unknown_dropped=snap["earnings_unknown_dropped"],
    )


# ---------------------------------------------------------------- theta harvester

# Session advisory locks, same md5 shape as routers/volatility.py and
# routers/stock.py. No parameter: both locks are global rather than per-ticker,
# because both operations sweep the whole watchlist.
_THETA_SCAN_LOCK_SQL = (
    "('x' || substr(md5('theta_harvester_scan'), 1, 16))::bit(64)::bigint"
)
_THETA_QUOTE_LOCK_SQL = (
    "('x' || substr(md5('theta_harvester_quote'), 1, 16))::bit(64)::bigint"
)

# Hard ceiling: 8 candidates x 2 legs = 16 SERIAL IB subprocess calls against a
# ~100-line market-data cap shared with xenon and the spot WS feed. Over-large
# requests are rejected rather than silently truncated — a caller who asked for
# 50 and got 8 would think it had quoted 50.
_QUOTE_MAX = 8

# Per-leg IB timeout. The default 8.0s would put the 16-call worst case at
# ~128s, past most proxy and browser timeouts; 4.0s bounds it at ~64s. If that
# is still slow in practice, move the quote to /jobs with polling rather than
# raising the cap or parallelising — the shared IB line budget is the real
# constraint, not the latency.
_QUOTE_TIMEOUT_S = 4.0


def _release(repo: Repository, lock_sql: str) -> None:
    """Release a session advisory lock, even from an aborted transaction.

    These are SESSION-scoped locks, which a ROLLBACK does not release. If the
    body failed mid-write the transaction is aborted, so the bare unlock would
    itself error with InFailedSqlTransaction and propagate out of `finally` —
    leaving the lock held on a connection that api/deps.py then rolls back and
    returns to the pool. Every later scan or quote 409s until that physical
    connection is recycled. Rolling back FIRST clears the aborted state so the
    unlock can actually run.
    """
    try:
        repo.conn.rollback()
        with repo.conn.cursor() as cur:
            cur.execute(f"SELECT pg_advisory_unlock({lock_sql})")
    except Exception as exc:  # never mask the original failure
        logger.warning("theta lock release failed: %r", exc)


class ThetaQuoteRequest(BaseModel):
    # ge=1: a negative limit reaches read_candidates as a bare SQL LIMIT and
    # 500s on a driver error rather than being rejected at the boundary.
    limit: int = Field(default=_QUOTE_MAX, ge=1)
    as_of: _date | None = None


@router.get("/theta-harvester", response_model=ThetaHarvesterResponse)
def theta_harvester(
    as_of: _date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ThetaHarvesterResponse:
    """Read persisted candidates. Pure warm-store read — no UW call, no IB call.

    RESEARCH ARTIFACT. These are naked short strangles, which argon's standing
    "defined-risk only / no naked shorts" rule forbids trading. The rows exist
    to measure whether the score orders anything; the sweep says it ranks but
    does not by itself pay (docs/research/2026-07-28-theta-harvester-weight-sweep.md).
    The UI must keep saying so.
    """
    th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
    target = as_of or th.latest_as_of()
    rows = th.read_candidates(as_of=target, limit=limit) if target else []
    return ThetaHarvesterResponse(
        as_of=target,
        generated_at=_now_utc(),
        candidates=[ThetaHarvesterCandidate(**dict(r)) for r in rows],
    )


@router.post("/theta-harvester/rescan", response_model=ThetaHarvesterScanResult)
def theta_harvester_rescan(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ThetaHarvesterScanResult:
    """Recompute candidates synchronously.

    A deliberate write on an otherwise read-only router — the same exception
    already made for POST /stock/{ticker}/technicals/refresh. Safe inline
    because the ranking path is pure warm-store SQL with no network call.

    Single-flight per api/CLAUDE.md: without the lock two clicks race two full
    watchlist sweeps writing the same (ticker, as_of) rows.
    """
    from uw_scan.worker.jobs.theta_harvester import theta_harvester_scan

    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT pg_try_advisory_lock({_THETA_SCAN_LOCK_SQL})")
        acquired = bool(cur.fetchone()[0])
    if not acquired:
        raise HTTPException(status_code=409, detail="a theta scan is already running")
    try:
        return ThetaHarvesterScanResult(
            **theta_harvester_scan(repo=repo, settings=settings)
        )
    finally:
        _release(repo, _THETA_SCAN_LOCK_SQL)


@router.post("/theta-harvester/quote", response_model=ThetaHarvesterQuoteResult)
def theta_harvester_quote(
    payload: ThetaQuoteRequest | None = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ThetaHarvesterQuoteResult:
    """Fetch live IB NBBO for the top-N candidates' legs, serially.

    Never called from a scheduled job. Each leg spawns an IB snapshot
    subprocess (~2-5s) and consumes one of the shared ~100-line market-data
    lines, so this is bounded at _QUOTE_MAX candidates and single-flighted.

    The quote NEVER becomes the markout basis — it lands in credit_ib, beside
    the untouched entry_credit_theo. A basis that exists for quoted rows and
    not for the rest would make the panel incomparable with itself.
    """
    from uw_scan.sources.xenon_query import fetch_ib_option_quote

    req = payload or ThetaQuoteRequest()
    if req.limit > _QUOTE_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"limit exceeds the IB line budget; max {_QUOTE_MAX} candidates",
        )

    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT pg_try_advisory_lock({_THETA_QUOTE_LOCK_SQL})")
        if not bool(cur.fetchone()[0]):
            raise HTTPException(
                status_code=409, detail="a theta quote request is already running"
            )
    try:
        th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
        target = req.as_of or th.latest_as_of()
        if target is None:
            return ThetaHarvesterQuoteResult(quoted=0, failed=0)

        api_key = (
            settings.xenon_query_api_key.get_secret_value()
            if settings.xenon_query_api_key is not None
            else None
        )
        quoted = failed = 0
        for row in th.read_candidates(as_of=target, limit=req.limit):
            expiry = row["expiry"].strftime("%Y%m%d")
            mids: list[float] = []
            for strike, right in (
                (float(row["put_strike"]), "P"),
                (float(row["call_strike"]), "C"),
            ):
                leg = fetch_ib_option_quote(
                    base_url=settings.xenon_query_api_url,
                    api_key=api_key,
                    symbol=row["ticker"],
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    timeout_s=_QUOTE_TIMEOUT_S,
                )
                if not leg or leg.get("bid") is None or leg.get("ask") is None:
                    mids = []
                    break
                mids.append((float(leg["bid"]) + float(leg["ask"])) / 2.0)
            if len(mids) == 2:
                th.set_ib_credit(
                    row["ticker"], target, credit=sum(mids), source="xenon_ib"
                )
                quoted += 1
            else:
                failed += 1
        return ThetaHarvesterQuoteResult(quoted=quoted, failed=failed)
    finally:
        # fetch_ib_option_quote never raises, but set_ib_credit can fail on a DB
        # error and a leaked session lock would block every later quote until
        # the connection is recycled.
        _release(repo, _THETA_QUOTE_LOCK_SQL)
