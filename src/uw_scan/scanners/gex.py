"""GEX scanner — UW-driven. Ported from xenon/src/xenon/scanners/gex.py 2026-05-16.

Differences from xenon:
- No MenthorQ (Playwright dep skipped); ``mq`` and ``source_delta`` always None.
- No file cache; history is read/written via ``Repository.fetch_latest_gex`` /
  ``upsert_gex_snapshot`` against the ``gex_snapshots`` Postgres table.
- No CLI; no HTML rendering.
- This repo's UW pattern threads ``run_id`` from ``repo.insert_scan_run(...)``
  through every fetcher for audit trail.
- Spot source: ``/stock/{ticker}/stock-state`` (intraday) with iv_rank.close as
  EOD fallback (xenon uses /stock-state; ``/info`` returns only metadata, no
  price). Yahoo banned. ``compute_days_above_flip`` set to 0 in v1 (no history
  reader).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.cards.greek_exposure_history import parse_greek_exposure_history
from uw_scan.sources import uw as uw_source
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

INDEX_TICKERS = {"SPX", "NDX"}
BUCKET_SIZE_INDEX = 25
BUCKET_SIZE_ETF = 5
PROFILE_RANGE_PCT = 0.10
TRADING_DAYS_PER_YEAR = 252


def _bucket_size_for(ticker: str, spot: float) -> int:
    if ticker in INDEX_TICKERS:
        return BUCKET_SIZE_INDEX
    if ticker in ("SPY", "QQQ"):
        return BUCKET_SIZE_ETF
    return max(1, round(spot * 0.005))


# ─── Pure-logic compute functions (verbatim from xenon gex.py:378-582) ──────


def bucket_profile(
    strike_data: list[dict[str, Any]],
    bucket_size: int,
    spot: float,
    range_pct: float = PROFILE_RANGE_PCT,
) -> list[dict[str, Any]]:
    """Aggregate per-strike GEX into buckets within range of spot."""
    low_bound = spot * (1 - range_pct)
    high_bound = spot * (1 + range_pct)

    buckets: dict[float, dict[str, float]] = defaultdict(
        lambda: {"call_gex": 0.0, "put_gex": 0.0, "net_gex": 0.0}
    )

    for row in strike_data:
        s = row["strike"]
        if s < low_bound or s > high_bound:
            continue
        b = round(s / bucket_size) * bucket_size
        buckets[b]["call_gex"] += row["call_gex"]
        buckets[b]["put_gex"] += row["put_gex"]
        buckets[b]["net_gex"] += row["net_gex"]

    result = []
    for strike in sorted(buckets.keys()):
        vals = buckets[strike]
        result.append(
            {
                "strike": strike,
                "call_gex": round(vals["call_gex"], 2),
                "put_gex": round(vals["put_gex"], 2),
                "net_gex": round(vals["net_gex"], 2),
                "pct_from_spot": round((strike - spot) / spot * 100, 2),
                "tag": None,
            }
        )
    return result


def compute_gex_flip(profile: list[dict[str, Any]], spot: float) -> float | None:
    """Find the GEX flip: last strike below spot where net GEX crosses from negative to positive."""
    flip = None
    for i in range(1, len(profile)):
        prev_net = profile[i - 1]["net_gex"]
        curr_net = profile[i]["net_gex"]
        strike = profile[i]["strike"]
        if prev_net < 0 and curr_net > 0 and strike <= spot:
            flip = strike
    return flip


def find_key_levels(
    profile: list[dict[str, Any]], spot: float
) -> dict[str, dict[str, Any] | None]:
    """Identify max magnet, 2nd magnet, max accelerator, put wall, call wall."""
    if not profile:
        return {
            "max_magnet": None,
            "second_magnet": None,
            "max_accelerator": None,
            "put_wall": None,
            "call_wall": None,
        }

    positive = [b for b in profile if b["net_gex"] > 0]
    negative = [b for b in profile if b["net_gex"] < 0]

    positive_sorted = sorted(positive, key=lambda b: b["net_gex"], reverse=True)
    negative_sorted = sorted(negative, key=lambda b: b["net_gex"])

    def _make_level(bucket):
        if bucket is None:
            return None
        return {
            "strike": bucket["strike"],
            "gamma": round(bucket["net_gex"], 2),
            "distance": round(bucket["strike"] - spot, 2),
            "distance_pct": round((bucket["strike"] - spot) / spot * 100, 2),
        }

    max_magnet = _make_level(positive_sorted[0] if positive_sorted else None)
    second_magnet = _make_level(
        positive_sorted[1] if len(positive_sorted) > 1 else None
    )
    max_accel = _make_level(negative_sorted[0] if negative_sorted else None)

    put_wall_bucket = max(profile, key=lambda b: abs(b["put_gex"])) if profile else None
    call_wall_bucket = max(profile, key=lambda b: b["call_gex"]) if profile else None

    return {
        "max_magnet": max_magnet,
        "second_magnet": second_magnet,
        "max_accelerator": max_accel,
        "put_wall": _make_level(put_wall_bucket),
        "call_wall": _make_level(call_wall_bucket),
    }


def tag_profile(
    profile: list[dict[str, Any]],
    spot: float,
    flip: float | None,
    levels: dict[str, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Add tags to profile buckets for chart annotation."""
    spot_bucket = None
    min_dist = float("inf")
    for b in profile:
        d = abs(b["strike"] - spot)
        if d < min_dist:
            min_dist = d
            spot_bucket = b["strike"]

    tag_map: dict[float, str] = {}
    if spot_bucket is not None:
        tag_map[spot_bucket] = "SPOT"
    if flip is not None:
        tag_map[flip] = "GEX FLIP"

    for name, level in levels.items():
        if level is None:
            continue
        label = name.upper().replace("_", " ")
        s = level["strike"]
        if s not in tag_map:
            tag_map[s] = label

    for b in profile:
        b["tag"] = tag_map.get(b["strike"])
    return profile


def compute_expected_range(spot: float, atm_iv: float | None) -> dict[str, Any]:
    """Compute 1-day expected range from ATM IV."""
    if atm_iv is None or atm_iv <= 0:
        return {"low": None, "high": None, "iv_1d": None}
    iv_1d = atm_iv / math.sqrt(TRADING_DAYS_PER_YEAR)
    move = spot * iv_1d
    return {
        "low": round(spot - move, 2),
        "high": round(spot + move, 2),
        "iv_1d": round(iv_1d * 100, 4),
    }


def compute_directional_bias(
    spot: float,
    flip: float | None,
    net_gex: float,
    levels: dict[str, dict[str, Any] | None],
    days_above_flip: int,
) -> dict[str, Any]:
    """Determine directional bias heuristic."""
    reasons = []

    if flip is None:
        return {
            "direction": "NEUTRAL",
            "reasons": ["GEX flip not computable"],
            "days_above_flip": 0,
            "flip_migration": [],
        }

    above_flip = spot > flip
    magnet_above = (
        levels.get("max_magnet") is not None and levels["max_magnet"]["strike"] > spot
    )

    if above_flip and net_gex > 0 and magnet_above:
        direction = "BULL"
        reasons.append(f"Spot above flip ({flip:.0f})")
        reasons.append("Net GEX positive (stabilizing)")
        reasons.append(
            f"Max magnet at {levels['max_magnet']['strike']:.0f} pulls higher"
        )
    elif above_flip and magnet_above:
        direction = "CAUTIOUS_BULL"
        reasons.append(f"Spot above flip ({flip:.0f})")
        if net_gex < 0:
            reasons.append("Net GEX still negative")
        if magnet_above:
            reasons.append(f"Magnet at {levels['max_magnet']['strike']:.0f} above spot")
    elif not above_flip and net_gex < 0:
        direction = "BEAR"
        reasons.append(f"Spot below flip ({flip:.0f})")
        reasons.append("Net GEX negative (destabilizing)")
        accel = levels.get("max_accelerator")
        if accel and accel["strike"] < spot:
            reasons.append(f"Accelerator at {accel['strike']:.0f} below")
    elif not above_flip:
        direction = "CAUTIOUS_BEAR"
        reasons.append(f"Spot below flip ({flip:.0f})")
    else:
        direction = "NEUTRAL"
        reasons.append("Near flip level")

    if abs(days_above_flip) >= 3:
        side = "above" if days_above_flip > 0 else "below"
        reasons.append(f"{abs(days_above_flip)} consecutive days {side} flip")

    return {
        "direction": direction,
        "reasons": reasons,
        "days_above_flip": days_above_flip,
        "flip_migration": [],
    }


# ─── UW-driven fetchers (adapted for this repo's client + run_id pattern) ──


def fetch_strike_gex(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[dict[str, Any]]:
    """Per-strike GEX rows. Aggregates the UW response into the canonical shape."""
    body = uw_source.fetch_greek_exposure_by_strike(client, repo, run_id, ticker)
    rows = body.get("data", []) or []
    parsed = []
    for r in rows:
        try:
            strike = float(r["strike"])
            call_gex = float(r.get("call_gex", 0) or 0)
            put_gex = float(r.get("put_gex", 0) or 0)
            call_delta = float(r.get("call_delta", 0) or 0)
            put_delta = float(r.get("put_delta", 0) or 0)
            parsed.append(
                {
                    "strike": strike,
                    "call_gex": call_gex,
                    "put_gex": put_gex,
                    "net_gex": call_gex + put_gex,
                    "call_delta": call_delta,
                    "put_delta": put_delta,
                    "net_delta": call_delta + put_delta,
                }
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.debug("gex strike row skipped: %s", repr(exc))
            continue
    return parsed


def fetch_aggregate_gex(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[dict[str, Any]]:
    """Aggregate GEX time series.

    Delegates parsing to the shared ``cards/greek_exposure_history`` util so
    the same logic is reused by the regime-page history persistence path.
    """
    body = uw_source.fetch_greek_exposure_history(client, repo, run_id, ticker)
    return parse_greek_exposure_history(body)


def fetch_iv_rank_rows(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[dict[str, Any]]:
    """Raw iv_rank rows — atm_iv, iv_rank, and spot all consume the same data."""
    body = uw_source._fetch_json(client, repo, run_id, EndpointSlug.IV_RANK, ticker)
    return body.get("data", []) or []


def _latest_iv_rank_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda r: r.get("date", "") or "")


def fetch_atm_iv(iv_rank_rows: list[dict[str, Any]]) -> float | None:
    """30D ATM IV from latest iv_rank row's ``volatility`` field."""
    row = _latest_iv_rank_row(iv_rank_rows)
    if row is None:
        return None
    v = row.get("volatility")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError) as exc:
        log.debug("atm_iv coercion failed: %s", repr(exc))
        return None


def fetch_iv_rank(iv_rank_rows: list[dict[str, Any]]) -> float | None:
    """1Y IV rank percentile from latest row's ``iv_rank_1y`` field."""
    row = _latest_iv_rank_row(iv_rank_rows)
    if row is None:
        return None
    r = row.get("iv_rank_1y")
    try:
        return float(r) if r is not None else None
    except (TypeError, ValueError) as exc:
        log.debug("iv_rank coercion failed: %s", repr(exc))
        return None


def fetch_spot_price(iv_rank_rows: list[dict[str, Any]]) -> float | None:
    """EOD fallback spot from latest iv_rank row's ``close`` field.

    ``stock-state`` (intraday) is the primary spot source; this lags by hours
    because iv_rank updates once per day at ~22:35 UTC. Kept as graceful
    fallback when ``stock-state`` errors. Yahoo banned project-wide.
    """
    row = _latest_iv_rank_row(iv_rank_rows)
    if row is None:
        return None
    p = row.get("close")
    try:
        return float(p) if p is not None else None
    except (TypeError, ValueError) as exc:
        log.debug("spot_price coercion failed: %s", repr(exc))
        return None


def fetch_stock_state_snapshot(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> dict[str, Any] | None:
    """Live spot snapshot from /stock-state. Returns None on any failure.

    Normalized keys: ``spot, prev_close, market_time, tape_time, source``.
    ``source`` is always ``"stock_state"`` when this returns a dict — callers
    use it to distinguish from the iv_rank fallback in the payload.
    """
    try:
        body = uw_source.fetch_stock_state(client, repo, run_id, ticker)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return None
        close = data.get("close")
        if close is None:
            return None
        return {
            "spot": float(close),
            "prev_close": float(data["prev_close"])
            if data.get("prev_close") is not None
            else None,
            "market_time": data.get("market_time"),
            "tape_time": data.get("tape_time"),
            "source": "stock_state",
        }
    except Exception as exc:
        log.warning("stock_state_fetch_failed ticker=%s err=%s", ticker, repr(exc))
        return None


def fetch_vol_pc(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> float | None:
    """Volume put/call ratio from the screener row for this ticker."""
    try:
        body = uw_source._fetch_json(
            client,
            repo,
            run_id,
            EndpointSlug.BULK_SCREENER_STOCKS,
            None,
            params={"ticker": ticker.upper()},
        )
        rows = body.get("data", []) or []
        for r in rows:
            t = r.get("ticker", r.get("symbol", ""))
            if str(t).upper() == ticker.upper():
                pc = r.get("put_call_ratio")
                return float(pc) if pc is not None else None
        return None
    except Exception as exc:
        log.warning("vol_pc_fetch_failed ticker=%s err=%s", ticker, repr(exc))
        return None


# ─── Orchestration ─────────────────────────────────────────────────────────


def run(client: UwClient, repo: Repository, ticker: str = "SPX") -> int:
    """Run a full GEX scan against UW and persist to gex_snapshots.

    Returns the inserted row id. Raises if spot cannot be determined.
    """
    ticker = ticker.upper()
    run_id = repo.insert_scan_run(ticker, notes=f"gex_scan_{ticker}")
    log.info("gex_scan_start ticker=%s run_id=%d", ticker, run_id)

    try:
        iv_rows = fetch_iv_rank_rows(client, repo, run_id, ticker)
        snapshot = fetch_stock_state_snapshot(client, repo, run_id, ticker)
        if snapshot is not None:
            spot = snapshot["spot"]
            prev_close = snapshot["prev_close"]
            market_time = snapshot["market_time"]
            tape_time = snapshot["tape_time"]
            spot_source = snapshot["source"]
        else:
            spot = fetch_spot_price(iv_rows)
            prev_close = None
            market_time = None
            tape_time = None
            spot_source = "iv_rank_eod" if spot is not None else None
        if spot is None:
            log.warning("gex_scan_aborted_no_spot ticker=%s run_id=%d", ticker, run_id)
            repo.finish_scan_run(run_id, status="error")
            raise RuntimeError(f"could not fetch spot for {ticker}")

        strike_rows = fetch_strike_gex(client, repo, run_id, ticker)
        aggregate_rows = fetch_aggregate_gex(client, repo, run_id, ticker)
        # Persist the daily tail for the regime history chart. We already
        # have the parsed rows in aggregate_rows — no extra UW call. Failures
        # here are non-fatal: the scan's primary outcome is the snapshot row.
        try:
            from uw_scan.storage.greek_exposure_repository import (
                GreekExposureDailyRepository,
            )

            GreekExposureDailyRepository(repo.conn, schema=repo._schema).upsert_rows(
                ticker,
                [
                    {
                        "trade_date": h["date"],
                        "call_gex": h["call_gex"],
                        "put_gex": h["put_gex"],
                        "call_delta": h["call_delta"],
                        "put_delta": h["put_delta"],
                        # JSONB needs a serializable form — date stays in
                        # the trade_date column, so drop it from payload.
                        "payload": {k: v for k, v in h.items() if k != "date"},
                    }
                    for h in aggregate_rows
                ],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "greek_exposure_daily_upsert_failed ticker=%s err=%s",
                ticker,
                repr(exc),
            )
        atm_iv = fetch_atm_iv(iv_rows)
        iv_rank = fetch_iv_rank(iv_rows)
        vol_pc = fetch_vol_pc(client, repo, run_id, ticker)

        bucket_size = _bucket_size_for(ticker, spot)
        profile = bucket_profile(strike_rows, bucket_size, spot)
        levels = find_key_levels(profile, spot)
        gex_flip_strike = compute_gex_flip(profile, spot)
        profile = tag_profile(profile, spot, gex_flip_strike, levels)
        expected_range = compute_expected_range(spot, atm_iv)

        net_gex = sum(b["net_gex"] for b in profile)
        net_dex = sum(
            r.get("call_delta", 0) + r.get("put_delta", 0) for r in aggregate_rows
        )

        days_above_flip = 0  # v1: history reader not wired yet
        bias = compute_directional_bias(
            spot, gex_flip_strike, net_gex, levels, days_above_flip
        )

        # Inject GEX flip into levels block (xenon does this in build_gex_output)
        if gex_flip_strike is not None:
            levels = dict(levels)
            levels["gex_flip"] = {
                "strike": gex_flip_strike,
                "gamma": 0.0,
                "distance": round(gex_flip_strike - spot, 2),
                "distance_pct": round((gex_flip_strike - spot) / spot * 100, 2),
            }
        else:
            levels = dict(levels)
            levels["gex_flip"] = None

        day_change = round(spot - prev_close, 4) if prev_close is not None else None
        day_change_pct = (
            round((spot - prev_close) / prev_close * 100, 4)
            if prev_close is not None and prev_close != 0
            else None
        )
        payload: dict[str, Any] = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "spot": spot,
            "close": spot,
            "prev_close": prev_close,
            "market_time": market_time,
            "tape_time": tape_time,
            "spot_source": spot_source,
            "day_change": day_change,
            "day_change_pct": day_change_pct,
            "data_date": datetime.now(timezone.utc).date().isoformat(),
            "net_gex": net_gex,
            "net_dex": net_dex,
            "atm_iv": atm_iv,
            "vol_pc": vol_pc,
            "levels": levels,
            "profile": profile,
            "expected_range": expected_range,
            "bias": bias,
            "history": [],
            "iv": {
                "iv30d": atm_iv,
                "iv_rank": iv_rank,
                "hv30": None,
                "mq_iv30d": None,
                "mq_iv_rank": None,
                "source": "uw" if atm_iv is not None else None,
            },
            "mq": None,
            "source_delta": None,
        }

        row_id = repo.upsert_gex_snapshot(
            ticker=ticker,
            payload=payload,
            data_date=datetime.now(timezone.utc).date(),
        )
        repo.finish_scan_run(run_id, status="ok")
        log.info(
            "gex_scan_done ticker=%s row_id=%d net_gex=%.2e",
            ticker,
            row_id,
            net_gex,
        )
        return row_id
    except Exception:
        # Recovery is best-effort: if the original failure left the conn in an
        # aborted state, the UPDATE in finish_scan_run will raise
        # InFailedSqlTransaction, which would then mask the original error AND
        # leave an orphaned status='running' row. Rollback to clear the conn
        # and retry the status update. Never let the recovery path overshadow
        # the original exception via `raise`.
        try:
            repo.finish_scan_run(run_id, status="error")
        except Exception as cleanup_exc:
            log.debug(
                "gex_scan_finish_cleanup_pending ticker=%s run_id=%d cleanup_exc=%s",
                ticker,
                run_id,
                repr(cleanup_exc),
            )
            try:
                repo.conn.rollback()
                repo.finish_scan_run(run_id, status="error")
            except Exception as retry_exc:
                log.warning(
                    "gex_scan_finish_cleanup_failed ticker=%s run_id=%d cleanup_exc=%s retry_exc=%s",
                    ticker,
                    run_id,
                    repr(cleanup_exc),
                    repr(retry_exc),
                )
        raise
