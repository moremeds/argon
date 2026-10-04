"""/regime VRP macro signal (EOD + live) and entry preview/capture."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.models.vrp_macro_entry import (
    VrpMacroEntryCaptureResponse,
    VrpMacroEntryLeg,
    VrpMacroEntryPreview,
)
from uw_scan.api.routers.regime_routes._shared import (
    _active_ws_source,
    _f,
    logger,
)
from uw_scan.api.schemas import (
    RegimeLiveQuote,
    VrpMacroSignalLiveResponse,
    VrpMacroSignalResponse,
    VrpMacroSignalRow,
)
from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    current_macro_signal,
    current_macro_signal_live,
)
from uw_scan.scanners.live_quotes import LiveQuote, live_or_eod
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.vrp_macro_entry import capture_entry_now

router = APIRouter()


@router.get("/vrp-macro-signal", response_model=VrpMacroSignalResponse)
def get_vrp_macro_signal(
    repo: Annotated[Repository, Depends(get_repo)],
) -> VrpMacroSignalResponse:
    """Latest VRP macro short-vol signal per index (SPX/QQQ/IWM). Read-only over
    the daily snapshot written by the nightly vrp_macro_signal_refresh job."""
    rows = repo.fetch_latest_vrp_macro_signals()
    return VrpMacroSignalResponse(signals=[VrpMacroSignalRow(**r) for r in rows])


@router.get("/vrp-macro-signal/live", response_model=VrpMacroSignalLiveResponse)
def get_vrp_macro_signal_live(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroSignalLiveResponse:
    """Live SPX VRP macro short-vol signal: intraday VIX -> live vrp_z (rv20/distribution
    from EOD). Falls back to the latest nightly basis='eod' snapshot when quotes are
    stale. Mirrors /cri/live; does not persist (the 5-min job does that)."""
    today_et = datetime.now(
        ZoneInfo(settings.rth_tz)
    ).date()  # match the worker's ET date

    def live(quotes: dict[str, LiveQuote]) -> VrpMacroSignalLiveResponse | None:
        spx_q, vix_q = quotes.get("SPX"), quotes.get("VIX")
        if spx_q is None or vix_q is None:
            return None
        try:
            sig = current_macro_signal_live(
                repo,
                settings,
                "SPX",
                WINNER,
                live_spot=float(spx_q.price),
                live_iv=float(vix_q.price) / 100.0,
            )
        except ValueError as exc:
            logger.debug(
                "vrp live recompute failed; falling back to EOD: %s", repr(exc)
            )
            return None
        if sig is None:
            return None
        # merge the static backtest headline from the latest EOD row, if present
        eod_rows = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
        bt = eod_rows[0] if eod_rows else {}
        row = VrpMacroSignalRow(
            name=sig.name,
            snapshot_date=today_et,
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
            bt_n=bt.get("bt_n"),
            bt_sharpe=bt.get("bt_sharpe"),
            bt_maxdd=bt.get("bt_maxdd"),
            bt_annror=bt.get("bt_annror"),
            bt_calmar=bt.get("bt_calmar"),
            short_put_delta=sig.short_put_delta,
            long_put_delta=sig.long_put_delta,
            strike_basis=sig.strike_basis,
            strike_grid_date=sig.strike_grid_date,
            expiry=sig.expiry,
        )
        return VrpMacroSignalLiveResponse(
            basis="live",
            signal=row,
            live_quotes={
                s: RegimeLiveQuote(
                    price=float(q.price), quoted_at=q.quoted_at, source=q.source
                )
                for s, q in (("SPX", spx_q), ("VIX", vix_q))
            },
            active_source=_active_ws_source(repo),
        )

    def eod() -> VrpMacroSignalLiveResponse:
        eod_rows = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
        if not eod_rows:
            return VrpMacroSignalLiveResponse(basis="eod", signal=None)
        return VrpMacroSignalLiveResponse(
            basis="eod",
            signal=VrpMacroSignalRow(
                **{k: eod_rows[0].get(k) for k in VrpMacroSignalRow.model_fields}
            ),
        )

    return live_or_eod(repo, settings, live, eod)


# ─── VRP macro entry-capture preview + capture ───────────────────

_PREVIEW_LEG_ORDER = ("short_above", "short_below", "wing_above", "wing_below")


def _live_or_eod_macro_signal(repo: Repository, settings: Settings):
    """Live SPX macro signal if SPX+VIX quotes are fresh, else the EOD signal,
    else None. Reads DB only — ZERO UW, ZERO IB, ZERO writes (preview is
    browser-polled; a fetcher call would write an audit row per poll)."""

    def live(quotes: dict[str, LiveQuote]):
        spx, vix = quotes.get("SPX"), quotes.get("VIX")
        if spx is None or vix is None:
            return None
        try:
            return current_macro_signal_live(
                repo,
                settings,
                "SPX",
                WINNER,
                live_spot=float(spx.price),
                live_iv=float(vix.price) / 100.0,
            )
        except ValueError as exc:
            logger.debug("vrp preview live signal failed: %s", repr(exc))
            return None

    def eod():
        try:
            return current_macro_signal(repo, settings, "SPX")
        except ValueError as exc:
            logger.debug("vrp preview eod signal failed: %s", repr(exc))
            return None

    return live_or_eod(repo, settings, live, eod)


def _persisted_preview_legs(quotes: list[dict]) -> list[VrpMacroEntryLeg]:
    """Latest-as_of snapshot legs of a persisted cohort, ordered."""
    if not quotes:
        return []
    latest = max(q["as_of"] for q in quotes)
    by_leg = {q["leg"]: q for q in quotes if q["as_of"] == latest}
    legs: list[VrpMacroEntryLeg] = []
    for name in _PREVIEW_LEG_ORDER:
        q = by_leg.get(name)
        if q is None:
            continue
        legs.append(
            VrpMacroEntryLeg(
                leg=name,
                strike=float(q["strike"]),
                nbbo_bid=_f(q["nbbo_bid"]),
                nbbo_ask=_f(q["nbbo_ask"]),
                iv=_f(q["iv"]),
                delta=_f(q["delta"]),
                gamma=_f(q["gamma"]),
                vega=_f(q["vega"]),
                theta=_f(q["theta"]),
                und_spot=_f(q["und_spot"]),
                source=q["source"],
                greeks_source=q["greeks_source"],
            )
        )
    return legs


def _leg_mid(leg: VrpMacroEntryLeg) -> float | None:
    if leg.nbbo_bid is not None and leg.nbbo_ask is not None:
        return (leg.nbbo_bid + leg.nbbo_ask) / 2.0
    return None


def _modeled_credit(legs: list[VrpMacroEntryLeg]) -> float | None:
    """short-leg mid − wing-leg mid using the consistent 'above' bracket (the
    continuous-strike MacroSignal.credit won't match the snapped legs)."""
    by = {leg.leg: leg for leg in legs}
    s, w = by.get("short_above"), by.get("wing_above")
    if s is None or w is None:
        return None
    sm, wm = _leg_mid(s), _leg_mid(w)
    if sm is None or wm is None:
        return None
    return sm - wm


@router.get("/vrp-macro-signal/entry/preview", response_model=VrpMacroEntryPreview)
def get_vrp_macro_entry_preview(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroEntryPreview:
    """SPX entry preview. ZERO IB, ZERO new UW, ZERO writes — browser-polled.
    Serves today's persisted auto-cohort snapshot legs (real strikes + NBBO) if
    present, else empty legs — never a fabricated indicative grid (a synthetic
    strike/mid is worse than none). Degrades to action=None + empty legs when no
    signal resolves (never 500)."""
    today_et = datetime.now(ZoneInfo(settings.rth_tz)).date()
    sig = _live_or_eod_macro_signal(repo, settings)
    today_cohort = next(
        (
            c
            for c in repo.fetch_open_vrp_macro_entries("SPX", today_et)
            if c["birth_date"] == today_et
        ),
        None,
    )
    if today_cohort is not None:
        quotes = repo.fetch_vrp_macro_entry_quotes(today_cohort["entry_id"])
        legs = _persisted_preview_legs(quotes)
        return VrpMacroEntryPreview(
            name="SPX",
            as_of=max((q["as_of"] for q in quotes), default=None),
            spot=float(sig.spot) if sig else _f(today_cohort["spot_at_birth"]),
            expiry=today_cohort["expiry"],
            hold_days=today_cohort["hold_days"],
            action=sig.action if sig else today_cohort["action_at_birth"],
            vrp_z=(
                float(sig.vrp_z)
                if sig and sig.vrp_z is not None
                else _f(today_cohort["vrp_z_at_birth"])
            ),
            weight=float(sig.weight) if sig else _f(today_cohort["weight_at_birth"]),
            modeled_credit=_modeled_credit(legs),
            legs=legs,
        )
    if sig is None:
        return VrpMacroEntryPreview(name="SPX", legs=[])
    # No cohort born/captured today → no real strikes or quotes exist yet. Do NOT
    # fabricate an indicative grid: synthetic strikes + flat-vol BS mids are not
    # market data, and a fake number is worse than none. Surface the real signal
    # context with empty legs; the card renders "No entry preview yet" + "ETD —".
    return VrpMacroEntryPreview(
        name="SPX",
        spot=float(sig.spot),
        hold_days=sig.hold_days,
        action=sig.action,
        vrp_z=float(sig.vrp_z) if sig.vrp_z is not None else None,
        weight=float(sig.weight),
        legs=[],
    )


@router.post(
    "/vrp-macro-signal/entry/capture", response_model=VrpMacroEntryCaptureResponse
)
def post_vrp_macro_entry_capture(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroEntryCaptureResponse:
    """Capture the current SPX entry now (IB-primary): persists a one-shot 'button'
    cohort + its 4 legs, then returns them read back from the persisted rows."""
    entry_id = capture_entry_now(repo, settings)
    header = repo.fetch_vrp_macro_entry(entry_id)
    quotes = repo.fetch_vrp_macro_entry_quotes(entry_id)
    legs = _persisted_preview_legs(quotes)
    preview = VrpMacroEntryPreview(
        name="SPX",
        as_of=max((q["as_of"] for q in quotes), default=None),
        spot=_f(header["spot_at_birth"]) if header else None,
        expiry=header["expiry"] if header else None,
        hold_days=header["hold_days"] if header else None,
        action=header["action_at_birth"] if header else None,
        vrp_z=_f(header["vrp_z_at_birth"]) if header else None,
        weight=_f(header["weight_at_birth"]) if header else None,
        modeled_credit=_modeled_credit(legs),
        legs=legs,
    )
    return VrpMacroEntryCaptureResponse(entry_id=entry_id, preview=preview)
