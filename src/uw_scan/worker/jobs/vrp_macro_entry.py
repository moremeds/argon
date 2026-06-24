"""VRP macro entry-capture snapshot job: daily-born SPX cohort + 8-mark markout.

Every trading day an "auto" cohort is born (the 4 put contracts bracketing the
0.25Δ short / 0.125Δ wing at the ~43-cal-DTE expiry), resolved against the live
macro signal + the UW chain. A worker mark snapshots every open cohort's 4 legs
IB-primary (xenon `/options/greeks`) / UW-fallback, greeks BS-computed. Birth is
idempotent per (name, day) via the partial unique index; snapshots upsert on
(entry_id, as_of, leg). After `taper_calendar_days` a cohort is marked EOD-only.
"""

from __future__ import annotations

import logging
import time
from datetime import date as _date
from datetime import datetime, timedelta
from datetime import time as _time
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.cards.option_chain import _parse_occ
from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_entry import (
    LegQuote,
    quote_leg,
    resolve_entry_contracts,
)
from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    current_macro_signal,
    current_macro_signal_live,
)
from uw_scan.scanners.live_quotes import load_live_quotes
from uw_scan.sources.uw import (
    fetch_greek_exposure_by_expiry,
    fetch_option_contracts_by_expiry,
    fetch_option_contracts_by_symbol,
)
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

# Header strike columns surface under these short leg-names (storage aliases).
_LEG_FIELDS = ("short_above", "short_below", "wing_above", "wing_below")
_TARGET_CAL_DAYS = 43  # ~43 calendar days ≈ the WINNER's 30-trading-day hold


def _occ_put(expiry: _date, strike: float) -> str:
    """OCC for an SPX *weekly* put. SPXW is PM-settled (valid at the 16:10 mark);
    the ~43-DTE expiries we pick are weeklies. A 3rd-Friday AM-settled monthly
    would mis-key here → its UW by-symbol NBBO comes back null and xenon (symbol
    'SPX', IB qualifies the contract) still quotes it — degraded, not broken."""
    return f"SPXW{expiry:%y%m%d}P{int(round(strike * 1000)):08d}"


def _session_for(now: datetime) -> str:
    t = now.astimezone(_ET).time()
    if t >= _time(16, 0):
        return "postclose"
    if t >= _time(15, 55):
        return "eod"
    return "rth"


def _uw_chain_strikes(
    repo: Repository, settings: Settings, symbol: str, on_date: _date
) -> tuple[_date, list[float]]:
    """(chosen_expiry, sorted listed PUT strikes) for the listed expiry nearest
    ``on_date + ~43cal``. Enumerates expiries via greek-exposure/expiry, then
    pulls the chosen expiry's contracts (strikes parsed from each OCC symbol).
    Audit-first UW calls under their own scan_run."""
    client = UwClient(
        api_key=settings.api_key.get_secret_value(), job_name="vrp_macro_entry"
    )
    try:
        run_id = repo.insert_scan_run(symbol, notes="vrp_macro_entry_birth")
        gex = fetch_greek_exposure_by_expiry(client, repo, run_id, symbol)
        expiries = sorted({r.expiry for r in gex if r.expiry > on_date})
        if not expiries:
            raise ValueError(f"{symbol}: no listed expiry after {on_date}")
        target = on_date + timedelta(days=_TARGET_CAL_DAYS)
        chosen = min(expiries, key=lambda e: abs((e - target).days))
        contracts = fetch_option_contracts_by_expiry(
            client, repo, run_id, symbol, chosen.isoformat()
        )
        strikes: set[float] = set()
        for c in contracts:
            parsed = _parse_occ(c.option_symbol)
            if parsed is None:
                continue
            exp, opt_type, strike = parsed
            if opt_type == "P" and exp == chosen:
                strikes.add(float(strike))
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
        return chosen, sorted(strikes)
    finally:
        client.close()


def _uw_leg_nbbo(
    repo: Repository,
    settings: Settings,
    symbol: str,
    expiry: _date,
    strikes: list[float],
) -> dict[float, dict]:
    """Current UW NBBO+IV for the 4 known legs of an open cohort, by-symbol
    (uncapped for known symbols). {strike: uw_row}; {} on failure — xenon/IB is
    the NBBO of record, so a UW miss just leaves the fallback empty."""
    client = UwClient(
        api_key=settings.api_key.get_secret_value(), job_name="vrp_macro_entry"
    )
    try:
        run_id = repo.insert_scan_run(symbol, notes="vrp_macro_entry_snapshot")
        occ = [_occ_put(expiry, s) for s in strikes]
        contracts = fetch_option_contracts_by_symbol(client, repo, run_id, symbol, occ)
        rows: dict[float, dict] = {}
        for c in contracts:
            parsed = _parse_occ(c.option_symbol)
            if parsed is None:
                continue
            _, _, strike = parsed
            rows[float(strike)] = {
                "option_symbol": c.option_symbol,
                "nbbo_bid": c.nbbo_bid,
                "nbbo_ask": c.nbbo_ask,
                "implied_volatility": c.implied_volatility,
            }
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
        return rows
    finally:
        client.close()


def _live_spot(
    repo: Repository, settings: Settings, symbol: str, now: datetime
) -> float | None:
    q = load_live_quotes(
        repo,
        [symbol],
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
        now=now,
    )
    hit = q.get(symbol)
    return float(hit.price) if hit is not None else None


def _resolve_legs(sig, *, on_date, chosen_expiry, strikes, rfr):
    """resolve_entry_contracts wrapper: T from expiry vs on_date (calendar)."""
    T = max((chosen_expiry - on_date).days, 1) / 365.0
    return resolve_entry_contracts(
        spot=sig.spot,
        sigma=sig.iv,
        T=T,
        r=rfr,
        listed_strikes=strikes,
        short_delta=sig.short_delta,
        wing_delta=sig.wing_delta,
    )


def _insert_cohort(repo, sig, *, origin, on_date, now, chosen_expiry, ec) -> int:
    return repo.insert_vrp_macro_entry(
        name=sig.name,
        birth_date=on_date,
        born_at=now,
        origin=origin,
        expiry=chosen_expiry,
        hold_days=sig.hold_days,
        spot_at_birth=sig.spot,
        iv_at_birth=sig.iv,
        vrp_z_at_birth=sig.vrp_z,
        weight_at_birth=sig.weight,
        action_at_birth=sig.action,
        short_delta=sig.short_delta,
        wing_delta=sig.wing_delta,
        short_above=ec.short_above,
        short_below=ec.short_below,
        wing_above=ec.wing_above,
        wing_below=ec.wing_below,
    )


def _birth_auto(repo: Repository, settings: Settings, *, on_date, now, rfr) -> int:
    """Birth today's auto cohort iff fresh SPX+VIX quotes resolve the live signal.
    No EOD fallback for birth (codex ISSUE-3): a holiday/WS-gap day would birth off
    a stale close and pollute the daily stride — let the next mark retry instead."""
    quotes = load_live_quotes(
        repo,
        ["SPX", "VIX"],
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
        now=now,
    )
    spx, vix = quotes.get("SPX"), quotes.get("VIX")
    if spx is None or vix is None:
        logger.info("vrp_macro_entry_birth_skipped reason=no_fresh_quote")
        return 0
    sig = current_macro_signal_live(
        repo,
        settings,
        "SPX",
        WINNER,
        live_spot=float(spx.price),
        live_iv=float(vix.price) / 100.0,
    )
    chosen_expiry, strikes = _uw_chain_strikes(repo, settings, "SPX", on_date)
    ec = _resolve_legs(
        sig, on_date=on_date, chosen_expiry=chosen_expiry, strikes=strikes, rfr=rfr
    )
    _insert_cohort(
        repo,
        sig,
        origin="auto",
        on_date=on_date,
        now=now,
        chosen_expiry=chosen_expiry,
        ec=ec,
    )
    repo.conn.commit()
    logger.info(
        "vrp_macro_entry_birth name=SPX expiry=%s action=%s", chosen_expiry, sig.action
    )
    return 1


def _null_quote(entry_id, as_of, session, leg, strike) -> dict:
    return {
        "entry_id": entry_id,
        "as_of": as_of,
        "session": session,
        "leg": leg,
        "strike": strike,
        "opt_right": "P",
        "nbbo_bid": None,
        "nbbo_ask": None,
        "iv": None,
        "delta": None,
        "gamma": None,
        "vega": None,
        "theta": None,
        "und_spot": None,
        "source": "uw",
        "greeks_source": "none",
        "source_asof": None,
    }


def _snapshot_cohort(
    repo: Repository,
    settings: Settings,
    cohort: dict,
    *,
    session,
    as_of,
    und,
    rfr,
    deadline,
) -> int:
    """Snapshot one cohort's 4 legs (one as_of). Per-leg try/except: a dead leg
    records nulls without dropping the other 3. UW NBBO is fetched once per cohort
    for the xenon fallback. ``deadline`` (monotonic) past → quote UW-only."""
    expiry: _date = cohort["expiry"]
    expiry_occ = expiry.strftime("%Y%m%d")
    legs = {leg: float(cohort[leg]) for leg in _LEG_FIELDS}
    und_spot = und if und is not None else float(cohort["spot_at_birth"])
    try:
        uw_nbbo = _uw_leg_nbbo(repo, settings, "SPX", expiry, list(legs.values()))
    except Exception as exc:  # noqa: BLE001 — UW miss is non-fatal; xenon is primary
        logger.warning(
            "vrp_macro_entry_uw_nbbo_failed entry_id=%s err=%s",
            cohort["entry_id"],
            repr(exc),
        )
        uw_nbbo = {}
    rows = []
    for leg, strike in legs.items():
        try_xenon = deadline is None or time.monotonic() < deadline
        try:
            q: LegQuote = quote_leg(
                strike=strike,
                expiry=expiry_occ,
                as_of=as_of,
                underlying_spot=und_spot,
                r=rfr,
                settings=settings,
                uw_row=uw_nbbo.get(strike),
                try_xenon=try_xenon,
            )
            rows.append(
                {
                    "entry_id": cohort["entry_id"],
                    "as_of": as_of,
                    "session": session,
                    "leg": leg,
                    "strike": strike,
                    "opt_right": "P",
                    "nbbo_bid": q.nbbo_bid,
                    "nbbo_ask": q.nbbo_ask,
                    "iv": q.iv,
                    "delta": q.delta,
                    "gamma": q.gamma,
                    "vega": q.vega,
                    "theta": q.theta,
                    "und_spot": q.und_spot,
                    "source": q.source,
                    "greeks_source": q.greeks_source,
                    "source_asof": q.source_asof,
                }
            )
        except Exception as exc:  # noqa: BLE001 — one dead leg never drops the cohort
            logger.warning(
                "vrp_macro_entry_leg_failed entry_id=%s leg=%s err=%s",
                cohort["entry_id"],
                leg,
                repr(exc),
            )
            rows.append(_null_quote(cohort["entry_id"], as_of, session, leg, strike))
    repo.insert_vrp_macro_entry_quotes(rows)
    repo.conn.commit()
    return len(rows)


def vrp_macro_entry_snapshot_once(
    repo: Repository,
    settings: Settings,
    *,
    session: str,
    now: datetime | None = None,
    birth: bool = False,
) -> dict:
    """One mark: optional birth (auto, idempotent) + snapshot every open auto
    cohort's 4 legs. Cohorts older than the taper window are EOD-only. Per-cohort
    try/except isolates DB failures. Returns {births, cohorts, quotes}."""
    now = now or datetime.now(_ET)
    on_date = now.astimezone(_ET).date()
    rfr = settings.vrp_risk_free_rate
    taper_days = getattr(settings, "vrp_macro_entry_taper_calendar_days", 30)
    budget_s = getattr(settings, "vrp_macro_entry_mark_budget_s", 600.0)

    births = 0
    if birth:
        existing = repo.fetch_open_vrp_macro_entries("SPX", on_date)
        if not any(c["birth_date"] == on_date for c in existing):
            try:
                births = _birth_auto(repo, settings, on_date=on_date, now=now, rfr=rfr)
            except Exception as exc:  # noqa: BLE001 — birth never blocks snapshotting
                repo.conn.rollback()
                logger.warning("vrp_macro_entry_birth_failed err=%s", repr(exc))

    cohorts = repo.fetch_open_vrp_macro_entries("SPX", on_date)
    und = _live_spot(repo, settings, "SPX", now)
    deadline = time.monotonic() + budget_s
    snapped = quotes = 0
    for cohort in cohorts:
        age = (on_date - cohort["birth_date"]).days
        if age > taper_days and session != "eod":
            continue
        try:
            quotes += _snapshot_cohort(
                repo,
                settings,
                cohort,
                session=session,
                as_of=now,
                und=und,
                rfr=rfr,
                deadline=deadline,
            )
            snapped += 1
        except Exception as exc:  # noqa: BLE001 — one cohort's DB error never blocks the rest
            repo.conn.rollback()
            logger.warning(
                "vrp_macro_entry_cohort_failed entry_id=%s err=%s",
                cohort.get("entry_id"),
                repr(exc),
            )
    return {"births": births, "cohorts": snapped, "quotes": quotes}


def capture_entry_now(
    repo: Repository, settings: Settings, *, now: datetime | None = None
) -> int:
    """Birth a one-shot 'button' cohort (IB-primary) + one immediate snapshot.
    Returns entry_id. Live signal if SPX+VIX quotes are fresh, else EOD signal
    (preview/button may run off-session — unlike auto birth, a button click is an
    explicit user action so the EOD fallback is acceptable here)."""
    now = now or datetime.now(_ET)
    on_date = now.astimezone(_ET).date()
    rfr = settings.vrp_risk_free_rate
    quotes = load_live_quotes(
        repo,
        ["SPX", "VIX"],
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
        now=now,
    )
    spx, vix = quotes.get("SPX"), quotes.get("VIX")
    if spx is not None and vix is not None:
        sig = current_macro_signal_live(
            repo,
            settings,
            "SPX",
            WINNER,
            live_spot=float(spx.price),
            live_iv=float(vix.price) / 100.0,
        )
        und = float(spx.price)
    else:
        sig = current_macro_signal(repo, settings, "SPX")
        und = sig.spot
    chosen_expiry, strikes = _uw_chain_strikes(repo, settings, "SPX", on_date)
    ec = _resolve_legs(
        sig, on_date=on_date, chosen_expiry=chosen_expiry, strikes=strikes, rfr=rfr
    )
    entry_id = _insert_cohort(
        repo,
        sig,
        origin="button",
        on_date=on_date,
        now=now,
        chosen_expiry=chosen_expiry,
        ec=ec,
    )
    repo.conn.commit()
    cohort = {
        "entry_id": entry_id,
        "expiry": chosen_expiry,
        "spot_at_birth": sig.spot,
        "short_above": ec.short_above,
        "short_below": ec.short_below,
        "wing_above": ec.wing_above,
        "wing_below": ec.wing_below,
    }
    _snapshot_cohort(
        repo,
        settings,
        cohort,
        session=_session_for(now),
        as_of=now,
        und=und,
        rfr=rfr,
        deadline=None,
    )
    return entry_id
