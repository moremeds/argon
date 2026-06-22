"""VRP macro short-vol signal refresh job (Layer-3 deploy) — thin orchestration
that runs reports/vrp_macro_signal.py over the tracked names and persists the
daily snapshot. The engine module stays persistence-free; this worker layer is
the seam that knows both reports and storage.

Runs at 03:45 ET (after vol_index_lake_sync at 03:15) so it reads the freshest
synced EOD vol. SPX (VIX) is the live name; QQQ/IWM (VXN/RVX) are wired but their
vol-index feed may lag — the row's as_of vs snapshot_date reveals staleness."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date as _date
from datetime import datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    MacroSignalConfig,
    backtest_laddered,
    current_macro_signal,
)
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

DEFAULT_NAMES: tuple[str, ...] = ("SPX", "QQQ", "IWM")


def _finite(x: float | None) -> float | None:
    """Postgres NUMERIC chokes on nan/inf; map non-finite backtest stats to NULL.
    Sharpe is nan when the monthly series has zero variance; Calmar is inf when
    maxDD is zero."""
    return x if (x is not None and isfinite(x)) else None


def vrp_macro_signal_refresh(
    *,
    repo: Repository,
    settings: Settings,
    snapshot_date: _date | None = None,
    names: tuple[str, ...] | list[str] = DEFAULT_NAMES,
    cfg: MacroSignalConfig = WINNER,
) -> dict[str, Any]:
    """For each name: compute the current weekly signal + the full-history backtest
    headline and upsert a (name, snapshot_date) row. Per-name isolation — one name's
    stale/missing vol data never blocks the others. Single commit at the end so
    readers never see a partial set. Idempotent (re-run same day overwrites)."""
    if snapshot_date is None:
        snapshot_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
    config = asdict(cfg)
    persisted = 0
    failed: list[str] = []
    for name in names:
        try:
            loaded = load_index_vol(repo, name)
            bt = backtest_laddered(loaded, settings, cfg)
            sig = current_macro_signal(repo, settings, name, cfg)
            repo.upsert_vrp_macro_signal(
                name=name,
                snapshot_date=snapshot_date,
                as_of=sig.as_of,
                spot=sig.spot,
                iv=sig.iv,
                rv20=sig.rv20,
                vrp=sig.vrp,
                vrp_z=sig.vrp_z,
                weight=sig.weight,
                action=sig.action,
                short_put=sig.short_put,
                long_put=sig.long_put,
                put_width=sig.put_width,
                credit=sig.credit,
                max_loss=sig.max_loss,
                hold_days=sig.hold_days,
                short_delta=sig.short_delta,
                wing_delta=sig.wing_delta,
                bt_n=bt.get("n"),
                bt_sharpe=_finite(bt.get("sharpe")),
                bt_maxdd=_finite(bt.get("maxdd")),
                bt_annror=_finite(bt.get("annror")),
                bt_calmar=_finite(bt.get("calmar")),
                config=config,
            )
            persisted += 1
            log.info(
                "vrp_macro_signal %s: as_of=%s action=%s weight=%.3f sharpe=%s",
                name,
                sig.as_of,
                sig.action,
                sig.weight,
                _finite(bt.get("sharpe")),
            )
        except Exception as exc:  # noqa: BLE001 - per-name isolation; log and continue
            failed.append(name)
            log.warning("vrp_macro_signal %s: skipped — %s", name, repr(exc))
    repo.conn.commit()
    counts = {"persisted": persisted, "failed": failed, "snapshot_date": snapshot_date}
    log.info(
        "vrp_macro_signal_refresh: %d persisted, %d failed (%s) for %s",
        persisted,
        len(failed),
        ",".join(failed) or "none",
        snapshot_date,
    )
    return counts
