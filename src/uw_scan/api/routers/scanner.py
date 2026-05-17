"""GET /api/scanner - read-only assembler over warm store."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.models.scanner import (
    ScannerCandidate,
    ScannerContextFlag,
    ScannerGatedTicker,
    ScannerGatesStatus,
    ScannerResponse,
    ScannerSignalHit,
)
from uw_scan.config import Settings
from uw_scan.scanner.models import (
    ContextFlag as DCContextFlag,
    ScanCandidate as DCScanCandidate,
    SignalHit as DCSignalHit,
)
from uw_scan.scanner.ranking import build_candidate, rank_candidates
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
    gated: list[ScannerGatedTicker] = []

    try:
        posture_row = repo.fetch_gold_posture_latest()
    except Exception:  # noqa: BLE001
        posture_row = None
    current_chip = posture_row.get("structural_posture_chip") if posture_row else None

    for row in latest:
        ticker = row["ticker"]
        run_id = row.get("run_id")
        if run_id is None:
            continue

        gate = sigs.fetch_gate_for_run(run_id, ticker) or {
            "earnings": "pass",
            "liquidity": "pass",
            "regime": "pass",
        }
        if gate["regime"] == "block":
            chip: Literal["SUSPENDED", "DEGRADED"] | None = None
            if current_chip in ("SUSPENDED", "DEGRADED"):
                chip = current_chip  # type: ignore[assignment]
            gated.append(
                ScannerGatedTicker(
                    ticker=ticker,
                    reason="regime_block",
                    blocking_chip=chip,
                    scanned_at=row.get("scanned_at"),
                )
            )
            continue

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
