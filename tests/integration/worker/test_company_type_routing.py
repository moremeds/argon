"""Routing precedence: name override, chain sector, vendor sector, pooled default.

The precedence is the contract. The chain taxonomy is hand-curated for this desk
and strictly more specific (it separates Foundry from Memory, which the vendor
vocabulary calls one thing), so it must win wherever it exists; the vendor sector
only reaches names the chain taxonomy has never labelled.

Tickers are real and their sectors are the ones actually on file 2026-08-19.
"""

from __future__ import annotations

from uw_scan.fundamentals.valuation import FINANCIALS, UNCLASSIFIED
from uw_scan.storage.company_sector import CompanySectorRepository
from uw_scan.worker.jobs.fundamental_anchors import (
    PROBE_OPTICAL_TICKERS,
    seed_company_types,
)


def _universe(conn, tickers: list[str]) -> None:
    with conn.cursor() as cur:
        for t in tickers:
            cur.execute(
                "INSERT INTO uw_scan.fundamental_universe (ticker, tier, reason) "
                "VALUES (%s, 'ranked', 'test') ON CONFLICT DO NOTHING",
                (t,),
            )
    conn.commit()


def _watchlist(conn, ticker: str, sector: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.watchlist (ticker, sector) VALUES (%s, %s) "
            "ON CONFLICT (ticker) DO UPDATE SET sector = EXCLUDED.sector",
            (ticker, sector),
        )
    conn.commit()


def _type_of(conn, ticker: str) -> tuple[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT company_type, note FROM uw_scan.fundamental_company_type "
            "WHERE ticker = %s",
            (ticker,),
        )
        return cur.fetchone()


def test_a_chain_labelled_bank_refuses_without_any_vendor_call(seeded_db_empty_cards):
    """JPM carries `Banks` on the watchlist — 8 of the 11 panel financials do,
    so the common case must never depend on the monthly fetch having run."""
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["JPM"])
    _watchlist(conn, "JPM", "Banks")
    seed_company_types(conn)
    company_type, note = _type_of(conn, "JPM")
    assert company_type == FINANCIALS
    assert note == "sector=Banks"


def test_a_vendor_sector_reaches_a_name_no_chain_rule_can(seeded_db_empty_cards):
    """AXP's real situation: no watchlist row at all, and it was one of the five
    financials rendering a `medium`-confidence band off the pooled default."""
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["AXP"])
    _only_vendor(conn, "AXP", "Financial Services")
    seed_company_types(conn)
    company_type, note = _type_of(conn, "AXP")
    assert company_type == FINANCIALS
    assert note == "vendor_sector=Financial Services"


def test_the_chain_sector_wins_when_both_exist(seeded_db_empty_cards):
    """TSM is `Foundry` on the chain and `Technology` to the vendor. The chain
    answer is the specific one; letting the vendor win would collapse Foundry,
    Memory and Semi-Cap into a single type and change which yield they price on.
    """
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["TSM"])
    _watchlist(conn, "TSM", "Foundry")
    CompanySectorRepository(conn).upsert("TSM", "Technology")
    seed_company_types(conn)
    company_type, note = _type_of(conn, "TSM")
    assert company_type == "chips_cyclical"
    assert note == "sector=Foundry"


def _only_vendor(conn, ticker: str, vendor_sector: str) -> None:
    """Put a name on the vendor path, and PROVE it is on it.

    The seeded watchlist carries a chain sector for 186 real tickers (XOM, CVX,
    LLY, TSM, JPM...), and `watchlist.sector` is NOT NULL so it cannot simply be
    cleared. So these tests use names genuinely absent from it — which is also
    the real situation they model: AXP and COF are in the fundamental universe
    with no watchlist row at all.

    The assertion is the point. An earlier draft picked XOM, assumed it carried
    no chain sector, and "failed" because the chain sector correctly won. A
    vendor-precedence test that silently exercises the CHAIN path proves
    nothing, and nothing about the seeded fixture stops that from recurring.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT sector FROM uw_scan.watchlist WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
    assert row is None or row[0] is None, (
        f"{ticker} now carries chain sector {row[0]!r}, so this test would "
        "exercise the chain path rather than the vendor path — pick another "
        "ticker or the assertion below proves nothing"
    )
    CompanySectorRepository(conn).upsert(ticker, vendor_sector)


def test_an_unmapped_vendor_sector_still_falls_through_to_the_default(
    seeded_db_empty_cards,
):
    """The vendor map answers one question. A name it does not answer must land
    exactly where it landed before this change, or the bank fix silently
    re-rates the panel."""
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["BMY"])
    _only_vendor(conn, "BMY", "Healthcare")
    seed_company_types(conn)
    company_type, _ = _type_of(conn, "BMY")
    assert company_type == UNCLASSIFIED


def test_a_vendor_Energy_name_is_not_routed_to_power_infra(seeded_db_empty_cards):
    """THE collision test.

    `Energy` means power generation in argon's chain taxonomy (-> `power_infra`,
    EV/EBITDA) and oil-and-gas in the vendor's. COP must NOT inherit
    `power_infra` from a vendor sector that merely shares a word with a chain
    label — which is exactly what one merged map would do, with no error
    anywhere and a repriced band as the only symptom.
    """
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["COP"])
    _only_vendor(conn, "COP", "Energy")
    seed_company_types(conn)
    company_type, _ = _type_of(conn, "COP")
    assert company_type == UNCLASSIFIED


def test_a_recorded_null_sector_is_not_asked_again(seeded_db_empty_cards):
    """A NULL is the answer "the vendor cannot classify this name". Re-asking it
    every run would spend the budget on the one reply that cannot change the
    routing, forever."""
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["AAA", "BBB"])
    repo = CompanySectorRepository(conn)
    assert set(repo.tickers_needing_fetch(10)) >= {"AAA", "BBB"}
    repo.upsert("AAA", None)
    remaining = repo.tickers_needing_fetch(10)
    assert "AAA" not in remaining
    assert "BBB" in remaining
    assert repo.coverage()["classified"] == 0


# --------------------------------------------------------------------------
# The fetch job
# --------------------------------------------------------------------------


class _StubClient:
    """Returns a canned `/stock/{ticker}/info` body per ticker.

    A ticker mapped to None yields HTTP 500, which is how a provider failure is
    distinguished here from "the vendor has no sector".
    """

    def __init__(self, bodies: dict[str, dict | None]) -> None:
        self._bodies = bodies
        self.asked: list[str] = []

    def get(self, slug, ticker=None, params=None, run_id=None, **kw):
        self.asked.append(ticker)
        body = self._bodies.get(ticker, {})

        class _Resp:
            status_code = 500 if body is None else 200

            @staticmethod
            def json():
                return body

        return _Resp(), None


def test_the_job_records_an_unclassifiable_name_so_it_is_never_re_asked(
    seeded_db_empty_cards,
):
    """The subtle half. A vendor reply with no sector is an ANSWER, and it has to
    be written — otherwise `tickers_needing_fetch` returns the same names every
    month and the job bills a call per name forever for a reply that cannot
    change the routing.
    """
    from uw_scan.worker.jobs.company_sector_refresh import company_sector_refresh

    conn = seeded_db_empty_cards.conn
    _universe(conn, ["ZZA", "ZZB"])
    client = _StubClient(
        {
            "ZZA": {"data": {"symbol": "ZZA", "sector": "Financial Services"}},
            "ZZB": {"data": {"symbol": "ZZB"}},  # vendor knows the name, no sector
        }
    )
    totals = company_sector_refresh(conn=conn, client=client, max_calls=50)
    assert totals["classified"] >= 1
    assert totals["unclassified"] >= 1

    repo = CompanySectorRepository(conn)
    remaining = repo.tickers_needing_fetch(50)
    assert "ZZA" not in remaining
    assert "ZZB" not in remaining


def test_a_provider_failure_is_counted_and_left_unasked_for_next_run(
    seeded_db_empty_cards,
):
    """A 500 must NOT be recorded as "no sector" — that would burn the retry.
    The distinction is the whole reason `failed` is a separate counter."""
    from uw_scan.worker.jobs.company_sector_refresh import company_sector_refresh

    conn = seeded_db_empty_cards.conn
    _universe(conn, ["ZZC"])
    totals = company_sector_refresh(
        conn=conn, client=_StubClient({"ZZC": None}), max_calls=50
    )
    assert totals["failed"] == 1
    assert totals["asked"] == 0
    assert "ZZC" in CompanySectorRepository(conn).tickers_needing_fetch(50)


def test_the_name_override_wins_over_both_sector_passes(seeded_db_empty_cards):
    """PYPL's real situation, and the reason the override is checked FIRST.

    It carries chain sector `Fintech` and vendor sector `Financial Services`, so
    both passes independently route it to the refusal. Only a rule ahead of both
    can keep its band, and that band is worth keeping: `platform_scale` prices it
    on `fcf_yield`, which divides by market cap and never touches the net-debt
    term the refusal exists to reject.
    """
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["PYPL"])
    _watchlist(conn, "PYPL", "Fintech")
    CompanySectorRepository(conn).upsert("PYPL", "Financial Services")
    seed_company_types(conn)
    company_type, note = _type_of(conn, "PYPL")
    assert company_type == "platform_scale"
    assert note == "ticker override (sector='Fintech')"


def test_the_override_does_not_leak_to_its_sector_neighbours(seeded_db_empty_cards):
    """One name, not the label. HOOD is a broker and SOFI a lender; they share
    `Fintech` with PYPL and must keep refusing."""
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["HOOD", "SOFI"])
    _watchlist(conn, "HOOD", "Fintech")
    _watchlist(conn, "SOFI", "Fintech")
    seed_company_types(conn)
    assert _type_of(conn, "HOOD")[0] == FINANCIALS
    assert _type_of(conn, "SOFI")[0] == FINANCIALS


def test_a_hand_correction_still_beats_the_override(seeded_db_empty_cards):
    """The override writes `seeded`, so the DB-level escape hatch is intact: an
    operator who disagrees with the PYPL call can still overrule it, and a
    reseed must not undo them."""
    from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository

    conn = seeded_db_empty_cards.conn
    _universe(conn, ["PYPL"])
    _watchlist(conn, "PYPL", "Fintech")
    FundamentalAnchorsRepository(conn).assign("PYPL", FINANCIALS, source="manual")
    seed_company_types(conn)
    assert _type_of(conn, "PYPL")[0] == FINANCIALS


def test_every_probe_optical_ticker_escapes_DC_Connect_to_chips_cyclical(
    seeded_db_empty_cards,
):
    """Task 11 (spec §5-vii). Every ticker the probe found misrouted, not a
    hardcoded sample of it — `PROBE_OPTICAL_TICKERS` is the same set the
    production map and the routing probe both enumerate, so a ticker added to
    (or dropped from) that set is covered here without editing this test.

    Real situation, verified against `option_wizard_local` 2026-08-27/28: all
    seven carry `watchlist.sector = 'DC-Connect'`, which — absent the
    override — matches `SECTOR_TO_TYPE`'s own `"DC-Connect": "power_infra"`
    entry directly and routes there, not to the `"Networking/Optical"` entry
    these names should hit.
    """
    conn = seeded_db_empty_cards.conn
    tickers = sorted(PROBE_OPTICAL_TICKERS)
    _universe(conn, tickers)
    for t in tickers:
        _watchlist(conn, t, "DC-Connect")
    seed_company_types(conn)
    for t in tickers:
        company_type, note = _type_of(conn, t)
        assert company_type == "chips_cyclical", (
            f"{t}: expected the ticker override to win over DC-Connect, got "
            f"{company_type!r}"
        )
        assert note == "ticker override (sector='DC-Connect')"


def test_DC_Connect_still_routes_power_infra_for_a_name_the_override_does_not_cover(
    seeded_db_empty_cards,
):
    """The override must not leak past the seven it names. GLW (Corning) is a
    real `DC-Connect` name on the watchlist that is NOT in
    `PROBE_OPTICAL_TICKERS` — it must keep routing exactly as it did before
    this change."""
    conn = seeded_db_empty_cards.conn
    assert "GLW" not in PROBE_OPTICAL_TICKERS
    _universe(conn, ["GLW"])
    _watchlist(conn, "GLW", "DC-Connect")
    seed_company_types(conn)
    company_type, note = _type_of(conn, "GLW")
    assert company_type == "power_infra"
    assert note == "sector=DC-Connect"


def test_a_capped_run_says_so_instead_of_looking_complete(seeded_db_empty_cards):
    """A truncated fill and a finished one produce identical counters otherwise.

    The universe is 450 names and the first run fetches all of them, so a cap
    below that drops names silently. The daily cron picks the remainder up the
    next morning, so this is not a correctness hole — but a cap that binds means
    the universe outgrew what one run was sized for, and nothing else on record
    would say so. `capped` is the record.
    """
    conn = seeded_db_empty_cards.conn
    _universe(conn, ["ZZD", "ZZE", "ZZF"])
    bodies = {
        t: {"data": {"symbol": t, "sector": "Financial Services"}}
        for t in ("ZZD", "ZZE", "ZZF")
    }
    from uw_scan.worker.jobs.company_sector_refresh import company_sector_refresh

    client = _StubClient(bodies)
    totals = company_sector_refresh(conn=conn, client=client, max_calls=2)
    assert totals["capped"] == 1
    assert totals["asked"] == 2, "the cap must still bound the spend it reports"
    assert len(client.asked) == 2

    # And an uncapped run reports the opposite, so the flag means something.
    rest = company_sector_refresh(conn=conn, client=_StubClient(bodies), max_calls=50)
    assert rest["capped"] == 0
