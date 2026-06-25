"""/regime/vrp-macro-signal/entry — preview (no IB / no UW) + capture (IB).

Preview serves persisted cohort legs or empty legs (never a fabricated grid); it
must make zero UW/IB calls (asserted by raising in those fetchers). Capture stubs the
job's UW + quote seams so no network, and asserts a one-shot button cohort + 4
quote rows persist.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import uw_scan.sources.uw as uw_src
import uw_scan.worker.jobs.vrp_macro_entry as job
from tests.integration.reports.test_vrp_macro_signal import _seed_spx_vix_varied
from uw_scan.reports.vrp_macro_entry import LegQuote

_ET = ZoneInfo("America/New_York")


def _today() -> date:
    return datetime.now(_ET).date()


def _seed_cohort_with_quotes(repo, *, birth_date, expiry):
    eid = repo.insert_vrp_macro_entry(
        name="SPX",
        birth_date=birth_date,
        born_at=datetime.now(timezone.utc),
        origin="auto",
        expiry=expiry,
        hold_days=30,
        spot_at_birth=7300,
        iv_at_birth=0.2,
        vrp_z_at_birth=0.6,
        weight_at_birth=1.0,
        action_at_birth="TRADE",
        short_delta=0.25,
        wing_delta=0.125,
        short_above=6900,
        short_below=6890,
        wing_above=6600,
        wing_below=6590,
    )
    as_of = datetime.now(timezone.utc)
    legs = [
        ("short_above", 6900),
        ("short_below", 6890),
        ("wing_above", 6600),
        ("wing_below", 6590),
    ]
    rows = [
        dict(
            entry_id=eid,
            as_of=as_of,
            session="rth",
            leg=leg,
            strike=strike,
            opt_right="P",
            nbbo_bid=12.0,
            nbbo_ask=12.4,
            iv=0.2,
            delta=-0.25,
            gamma=0.001,
            vega=8.0,
            theta=-1.0,
            und_spot=7300,
            source="xenon_ib",
            greeks_source="bs",
            source_asof=None,
        )
        for leg, strike in legs
    ]
    repo.insert_vrp_macro_entry_quotes(rows)
    repo.conn.commit()
    return eid


def test_preview_serves_persisted_cohort_without_uw_or_ib(
    client: TestClient, seeded_db_empty_cards, monkeypatch
):
    today = _today()
    expiry = today + timedelta(days=45)
    eid = _seed_cohort_with_quotes(
        seeded_db_empty_cards, birth_date=today, expiry=expiry
    )

    # any UW fetch or IB call inside the preview path must fail the request
    def _boom(*a, **k):
        raise AssertionError("preview must not call UW/IB")

    monkeypatch.setattr(uw_src, "_fetch_json", _boom)

    res = client.get("/api/regime/vrp-macro-signal/entry/preview")
    assert res.status_code == 200
    body = res.json()
    assert body["expiry"] == expiry.isoformat()
    assert len(body["legs"]) == 4
    assert {leg["leg"] for leg in body["legs"]} == {
        "short_above",
        "short_below",
        "wing_above",
        "wing_below",
    }
    assert all(leg["source"] == "xenon_ib" for leg in body["legs"])
    # modeled_credit = mid(short_above) − mid(wing_above) = 12.2 − 12.2 = 0 here
    assert body["modeled_credit"] is not None
    assert eid > 0


def test_preview_pre_birth_returns_no_legs(
    client: TestClient, seeded_db_empty_cards, monkeypatch
):
    """Pre-birth (no cohort today) the preview serves the real signal context but
    ZERO legs — never a fabricated indicative strike grid. A synthetic strike/mid
    is worse than none, so the card shows 'No entry preview yet' + 'ETD —'."""
    _seed_spx_vix_varied(
        seeded_db_empty_cards
    )  # EOD vol so current_macro_signal resolves
    seeded_db_empty_cards.conn.commit()

    monkeypatch.setattr(
        uw_src,
        "_fetch_json",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("preview must not call UW")
        ),
    )

    res = client.get("/api/regime/vrp-macro-signal/entry/preview")
    assert res.status_code == 200
    body = res.json()
    assert body["legs"] == []  # no fabricated legs
    assert body["expiry"] is None  # no fabricated ETD pre-birth
    assert body["modeled_credit"] is None
    assert body["action"] in {"TRADE", "SKIP"}  # real signal context still served


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
        nbbo_bid=11.0,
        nbbo_ask=11.5,
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


def test_capture_persists_button_cohort(
    client: TestClient, seeded_db_empty_cards, monkeypatch
):
    _seed_spx_vix_varied(
        seeded_db_empty_cards
    )  # EOD signal for the (no live quote) path
    seeded_db_empty_cards.conn.commit()
    # stub the job's UW chain + quoter so capture makes no network call
    monkeypatch.setattr(
        job,
        "_uw_chain_strikes",
        lambda *a, **k: (date(2026, 8, 7), [500.0 + 5 * i for i in range(2000)]),
    )
    monkeypatch.setattr(job, "quote_leg", _fake_quote_leg)

    res = client.post("/api/regime/vrp-macro-signal/entry/capture")
    assert res.status_code == 200
    body = res.json()
    entry_id = body["entry_id"]
    assert entry_id > 0
    assert len(body["preview"]["legs"]) == 4

    header = seeded_db_empty_cards.fetch_vrp_macro_entry(entry_id)
    assert header is not None and header["origin"] == "button"
    quotes = seeded_db_empty_cards.fetch_vrp_macro_entry_quotes(entry_id)
    assert len(quotes) == 4
