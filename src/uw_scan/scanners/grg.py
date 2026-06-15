"""GRG (Gamma Rotation Gap) scanner — orchestrator on cards/grg_scoring.

UW-bound: fetches the SPY & TLT greek-exposure time-series from Unusual
Whales (instant 90-session history). Reads SPY/TLT gamma-flip + spot from
the warm-store ``gex_snapshots`` (TLT flip/spot are None until TLT lands in
``gex_scan_tickers`` — GRG still computes from the UW series). Persists one
self-contained snapshot to ``grg_snapshots``.

No WS run_live: dealer gamma is not in the live WS feed, so freshness comes
from the worker re-running this scan (15-min RTH + post-close).
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.cards import grg_scoring
from uw_scan.cards.greek_exposure_history import parse_greek_exposure_history
from uw_scan.sources import uw as uw_source
from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _is_market_open() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def _spot_flip_from_gex(
    repo: Repository, ticker: str
) -> tuple[float | None, float | None]:
    """Spot + gamma-flip read ATOMICALLY from one ``gex_snapshots`` payload.

    Both come from the SAME ``fetch_latest_gex`` row (same ``scanned_at``), so
    they can't be sourced from two different scans. Uses argon's CANONICAL
    persisted flip — ``levels.gex_flip.strike``, exactly what the GEX tab shows
    — for one flip definition app-wide. This is an INTENTIONAL deviation from
    radon, which recomputes a last-neg→pos-crossing-at/below-spot flip from
    by-strike rows; see docs/research/grg-gamma-rotation-gap/CLAUDE.md. Returns
    ``(None, None)`` when no snapshot exists (e.g. TLT before its first GEX
    scan → flip renders ``---``, matching radon).
    """
    raw = repo.fetch_latest_gex(ticker=ticker)
    if not raw:
        return None, None

    def _num(v: object) -> float | None:
        try:
            return float(v) if v is not None else None  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            log.debug("grg gex coerce skipped %s: %s", ticker, repr(exc))
            return None

    spot = _num(raw.get("spot"))
    flip = None
    levels = raw.get("levels")
    gex_flip = levels.get("gex_flip") if isinstance(levels, dict) else None
    if isinstance(gex_flip, dict):
        flip = _num(gex_flip.get("strike"))
    return spot, flip


def _spy_close_by_date(repo: Repository) -> dict[str, float]:
    """``{date_iso: close}`` of SPY daily closes from the warm-store ``daily_ohlc``.

    Used to overlay SPY's actual price on the divergence chart. The OHLC job
    keeps SPY's daily bars current; a generous limit (400 rows ≈ 1.5y) covers
    the 1Y greek-history window with room to spare. Missing dates simply have
    no overlay point (the chart skips nulls). Read failure → empty map, so a
    transient OHLC gap never aborts the GRG scan (gamma series is the contract).
    """
    try:
        rows = repo.list_daily_ohlc("SPY", limit=400)
    except Exception as exc:  # pragma: no cover - defensive: never abort scan
        log.warning("grg_spy_close_read_failed err=%s", repr(exc))
        return {}
    out: dict[str, float] = {}
    for r in rows:
        if r.date is None or r.close is None:
            continue
        try:
            out[r.date.isoformat()] = float(r.close)
        except (TypeError, ValueError) as exc:
            log.debug("grg spy close coerce skipped %s: %s", r.date, repr(exc))
    return out


def run(
    client: UwClient,
    repo: Repository,
    schema: str = "uw_scan",
    *,
    scan_time: str | None = None,
) -> int | None:
    """Fetch SPY/TLT greek-exposure history, compute GRG, persist a snapshot.

    Returns the inserted row id, or None if there isn't enough aligned data.

    Audit ticker is the synthetic ``GRG`` (NOT ``SPY``): a successful
    ``scan_runs`` row for SPY with ``notes='grg_scan'`` would otherwise be
    picked up by ``latest_run_id('SPY')`` and shadow SPY's real full-scan.
    ``grg_scan`` is also excluded from ``latest_run_id`` as defense-in-depth.
    """
    run_id = repo.insert_scan_run("GRG", notes="grg_scan")
    try:
        # "1Y" window: the 63-session z-window must be fully warmed BEFORE the
        # YTD display window (Jan 1), or early-year z-scores would be thin.
        spy_rows = parse_greek_exposure_history(
            uw_source.fetch_greek_exposure_history(
                client, repo, run_id, "SPY", timeframe="1Y"
            )
        )
        tlt_rows = parse_greek_exposure_history(
            uw_source.fetch_greek_exposure_history(
                client, repo, run_id, "TLT", timeframe="1Y"
            )
        )
        spy_spot, spy_flip = _spot_flip_from_gex(repo, "SPY")
        tlt_spot, tlt_flip = _spot_flip_from_gex(repo, "TLT")
        spy_prices = _spy_close_by_date(repo)
        payload = grg_scoring.run_analysis(
            spy_rows,
            tlt_rows,
            spy_spot=spy_spot,
            spy_flip=spy_flip,
            tlt_spot=tlt_spot,
            tlt_flip=tlt_flip,
            spy_prices=spy_prices,
            scan_time=scan_time
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            market_open=_is_market_open(),
        )
        # Persist BEFORE marking the run ok: a DB failure here must NOT leave an
        # 'ok' audit row with no GRG snapshot. Mirrors gex.py.
        snap_repo = GrgSnapshotRepository(repo.conn, schema=schema)
        data_date = _date.fromisoformat(payload["data_date"])
        row_id = snap_repo.insert_snapshot(payload=payload, data_date=data_date)
    except ValueError as exc:
        log.warning("grg_scan_skipped_thin_data err=%s", repr(exc))
        repo.finish_scan_run(run_id, status="error")
        return None
    except Exception:
        repo.finish_scan_run(run_id, status="error")
        raise

    repo.finish_scan_run(run_id, status="ok")
    log.info(
        "grg_scan_persisted row_id=%d data_date=%s grg_z=%s state=%s",
        row_id,
        data_date,
        payload["signal"]["grg_z"],
        payload["signal"]["state"],
    )
    return row_id
