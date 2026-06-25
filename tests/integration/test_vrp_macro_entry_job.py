"""vrp_macro_entry_snapshot_once — daily birth + 8-mark snapshot + 30d EOD taper.

Reuses the regime live-signal fixture (`_seed_spx_vix_varied` + fresh SPX/VIX
intraday quotes) so birth resolves; stubs the two UW seams (`_uw_chain_strikes`,
`_uw_leg_nbbo`) and `quote_leg` so the job exercises no network.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from tests.integration.reports.test_vrp_macro_signal import _seed_spx_vix_varied
from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_entry import LegQuote
from uw_scan.worker.jobs import vrp_macro_entry as J

_ET = ZoneInfo("America/New_York")
_QUOTED = datetime(2026, 6, 12, 15, 30, tzinfo=timezone.utc)  # a Friday RTH instant
_NOW = _QUOTED + timedelta(minutes=1)
_STRIKES = [
    6000.0 + 5 * i for i in range(320)
]  # 6000..7595, brackets the 0.25/0.125 puts
_EXPIRY = date(2026, 8, 7)


def _settings() -> Settings:
    return Settings.from_env()


def _fake_chain(repo, settings, symbol, on_date, **_kw):
    return _EXPIRY, _STRIKES


def _fake_quote_leg(
    *,
    strike,
    expiry,
    as_of,
    underlying_spot,
    r,
    settings,
    uw_row=None,
    try_xenon=True,
    xenon_client=None,
):
    return LegQuote(
        strike=strike,
        nbbo_bid=10.0,
        nbbo_ask=10.5,
        iv=0.2,
        delta=-0.25,
        gamma=0.001,
        vega=8.0,
        theta=-1.0,
        und_spot=underlying_spot,
        source="xenon_ib",
        greeks_source="bs",
        source_asof=None,
    )


def _stub_uw(monkeypatch):
    monkeypatch.setattr(J, "_uw_chain_strikes", _fake_chain)
    monkeypatch.setattr(J, "_uw_leg_nbbo", lambda *a, **k: {})
    monkeypatch.setattr(J, "quote_leg", _fake_quote_leg)


def test_birth_then_snapshot(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.conn.commit()
    _stub_uw(monkeypatch)
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=_NOW.astimezone(_ET).date(),
        chosen_expiry=_EXPIRY,
        strikes=_STRIKES,
    )
    repo.conn.commit()
    settings = _settings()

    out = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=True, now=_NOW
    )
    assert out["births"] == 1 and out["cohorts"] == 1 and out["quotes"] == 4

    # second mark, same day, birth=False → idempotent (no new cohort), 4 more quotes
    out2 = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=False, now=_NOW + timedelta(hours=1)
    )
    assert out2["births"] == 0 and out2["cohorts"] == 1 and out2["quotes"] == 4

    # a re-birth mark is a no-op (partial unique index) — still one cohort
    out3 = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=True, now=_NOW + timedelta(hours=2)
    )
    assert out3["births"] == 0 and out3["cohorts"] == 1

    on_date = _NOW.astimezone(_ET).date()
    cohorts = repo.fetch_open_vrp_macro_entries("SPX", on_date)
    assert len(cohorts) == 1
    quotes = repo.fetch_vrp_macro_entry_quotes(cohorts[0]["entry_id"])
    # 3 marks × 4 legs, distinct as_of each → 12 rows
    assert len(quotes) == 12
    assert {q["leg"] for q in quotes} == set(J._LEG_FIELDS)
    assert all(q["source"] == "xenon_ib" and q["greeks_source"] == "bs" for q in quotes)


def test_aged_cohort_eod_only(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    _stub_uw(monkeypatch)
    settings = _settings()
    on_date = _NOW.astimezone(_ET).date()
    # aged cohort: born 40 cal days ago (> 30d taper), expiry still open
    repo.insert_vrp_macro_entry(
        name="SPX",
        birth_date=on_date - timedelta(days=40),
        born_at=_QUOTED - timedelta(days=40),
        origin="auto",
        expiry=_EXPIRY,
        hold_days=30,
        spot_at_birth=7000,
        iv_at_birth=0.2,
        vrp_z_at_birth=0.5,
        weight_at_birth=1.0,
        action_at_birth="TRADE",
        short_delta=0.25,
        wing_delta=0.125,
        short_above=6900,
        short_below=6890,
        wing_above=6600,
        wing_below=6590,
    )
    repo.conn.commit()

    out_rth = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=False, now=_NOW
    )
    assert out_rth["cohorts"] == 0  # aged cohort skipped on an intraday mark

    out_eod = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="eod", birth=False, now=_NOW
    )
    assert out_eod["cohorts"] == 1 and out_eod["quotes"] == 4  # captured at EOD


def test_birth_skipped_when_grid_cache_cold(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.conn.commit()
    _stub_uw(monkeypatch)  # _uw_chain_strikes stubbed, but birth must NOT call it
    settings = _settings()

    # fresh quotes but no cached grid → birth skips cleanly, no cohort, no crash
    out = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=True, now=_NOW
    )
    assert out["births"] == 0
    on_date = _NOW.astimezone(_ET).date()
    assert repo.fetch_open_vrp_macro_entries("SPX", on_date) == []


def test_grid_refresh_caches_listed_strikes(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    monkeypatch.setattr(J, "_uw_chain_strikes", _fake_chain)
    settings = _settings()

    out = J.vrp_macro_entry_grid_refresh(repo, settings, now=_NOW)
    assert out["chosen_expiry"] == _EXPIRY and out["strikes"] == len(_STRIKES)

    # rollback first: proves the JOB committed (a scheduled _repo conn would close
    # and discard an uncommitted row, leaving the 10:00 birth cold). The row must
    # survive a rollback on this same connection.
    repo.conn.rollback()
    on_date = _NOW.astimezone(_ET).date()
    got = repo.fetch_vrp_macro_entry_grid("SPX", on_date)
    assert got is not None and got["chosen_expiry"] == _EXPIRY
    assert len(got["strikes"]) == len(_STRIKES)


def test_birth_succeeds_when_uw_would_429(seeded_db_empty_cards, monkeypatch):
    """The regression test for the bug: with a warm grid cache, birth must NOT
    touch UW — so even if the UW chain enumeration would raise (429), birth still
    persists the cohort."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=_NOW.astimezone(_ET).date(),
        chosen_expiry=_EXPIRY,
        strikes=_STRIKES,
    )
    repo.conn.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("UW HTTP 429 daily_request_limit_hit")

    monkeypatch.setattr(J, "_uw_chain_strikes", _boom)
    monkeypatch.setattr(J, "_uw_leg_nbbo", lambda *a, **k: {})
    monkeypatch.setattr(J, "quote_leg", _fake_quote_leg)
    settings = _settings()

    out = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=True, now=_NOW
    )
    assert out["births"] == 1 and out["cohorts"] == 1 and out["quotes"] == 4

    # provenance: the persisted cohort must use the REAL cached grid — its expiry
    # and all four leg strikes are drawn from the seeded grid, never synthesised.
    on_date = _NOW.astimezone(_ET).date()
    cohort = repo.fetch_open_vrp_macro_entries("SPX", on_date)[0]
    assert cohort["expiry"] == _EXPIRY
    listed = set(_STRIKES)
    assert all(float(cohort[leg]) in listed for leg in J._LEG_FIELDS)
    # and they bracket sensibly: wings strictly below the shorts (OTM puts)
    assert float(cohort["wing_above"]) < float(cohort["short_above"])
    assert float(cohort["wing_below"]) < float(cohort["short_below"])


def test_capture_button_uses_grid_cache(seeded_db_empty_cards, monkeypatch):
    """The on-demand Capture button reads the cache too (so it works mid-RTH when
    UW is exhausted): with a warm cache it persists a one-shot 'button' cohort + 4
    legs without calling the UW chain enumeration."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=_NOW.astimezone(_ET).date(),
        chosen_expiry=_EXPIRY,
        strikes=_STRIKES,
    )
    repo.conn.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("UW HTTP 429 — button must not hit UW when cache warm")

    monkeypatch.setattr(J, "_uw_chain_strikes", _boom)
    monkeypatch.setattr(J, "_uw_leg_nbbo", lambda *a, **k: {})
    monkeypatch.setattr(J, "quote_leg", _fake_quote_leg)
    settings = _settings()

    entry_id = J.capture_entry_now(repo, settings, now=_NOW)
    header = repo.fetch_vrp_macro_entry(entry_id)
    assert header is not None and header["origin"] == "button"
    quotes = repo.fetch_vrp_macro_entry_quotes(entry_id)
    assert len(quotes) == 4 and {q["leg"] for q in quotes} == set(J._LEG_FIELDS)


def test_uw_chain_strikes_closes_run_on_failure(seeded_db_empty_cards, monkeypatch):
    """A UW failure inside _uw_chain_strikes must not leave a stuck 'running'
    scan_run (the original-bug symptom). insert_scan_run commits the row up front,
    so the failure path has to close it."""
    import pytest

    monkeypatch.setenv("UW_SCAN_API_KEY", "test-key")  # UwClient ctor reads it
    repo = seeded_db_empty_cards
    settings = _settings()

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

    def _boom(*_a, **_k):
        raise RuntimeError("UW 5xx during expiry enumeration")

    monkeypatch.setattr(J, "UwClient", _FakeClient)
    monkeypatch.setattr(J, "fetch_greek_exposure_by_expiry", _boom)

    with pytest.raises(RuntimeError):
        J._uw_chain_strikes(
            repo,
            settings,
            "SPX",
            date(2026, 6, 24),
            run_notes="vrp_macro_entry_grid_refresh",
        )
    repo.conn.rollback()  # the test's own view; the committed failed-run survives
    rows = repo.conn.execute(
        "SELECT status FROM uw_scan.scan_runs "
        "WHERE notes = 'vrp_macro_entry_grid_refresh'"
    ).fetchall()
    # invariant: the run is terminal (closed-failed), never left 'running'
    assert rows and all(r[0] != "running" for r in rows)
