"""Chain membership behaviour that the filter and the seeder both rely on."""

from __future__ import annotations

from uw_scan.storage.watchlist_chain import WatchlistChainRepository


def _repo(seeded) -> WatchlistChainRepository:
    return WatchlistChainRepository(seeded.conn, schema=seeded._schema)


def _add_ticker(seeded, ticker: str, sector: str) -> None:
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {seeded._schema}.watchlist (ticker, sector, sort_rank) "
            "VALUES (%s, %s, 0) ON CONFLICT (ticker) DO UPDATE SET sector = EXCLUDED.sector, "
            "removed_at = NULL",
            (ticker, sector),
        )


def test_one_ticker_holds_several_chains(seeded_db_empty_cards):
    """The whole point: a single sector column cannot express this."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "NVDA", "M7")
    r.replace_taxonomy_memberships(
        [
            ("NVDA", "L1", "Computer/GPU"),
            ("NVDA", "X", "M7"),
            ("NVDA", "L5", "Foundation-Model-Proxy"),
        ]
    )
    assert r.chains_by_ticker(["NVDA"])["NVDA"] == [
        "Computer/GPU",
        "Foundation-Model-Proxy",
        "M7",
    ]
    # And the chain that reads as empty under a single tag now resolves.
    assert r.tickers_in_chain("Foundation-Model-Proxy") == ["NVDA"]


def test_reseeding_drops_memberships_the_taxonomy_no_longer_lists(
    seeded_db_empty_cards,
):
    """A plain upsert would leave an orphan the filter still returns."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "ARM", "Semi-Logic")
    r.replace_taxonomy_memberships(
        [("ARM", "L1", "Computer/GPU"), ("ARM", "L1", "Foundry")]
    )
    assert r.tickers_in_chain("Foundry") == ["ARM"]

    r.replace_taxonomy_memberships([("ARM", "L1", "Computer/GPU")])
    assert r.tickers_in_chain("Foundry") == []  # gone, not stranded
    assert r.tickers_in_chain("Computer/GPU") == ["ARM"]


def test_reseed_preserves_inherited_sector_rows(seeded_db_empty_cards):
    """Re-seeding the taxonomy must not strip a ticker's fallback membership."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "JPM", "Banks")
    r.inherit_sector_memberships({"Banks": "DEF"})
    # The fixture pre-seeds its own Banks names, so assert membership rather
    # than an exact list — the point is that inherited rows exist and persist.
    before = r.tickers_in_chain("Banks")
    assert "JPM" in before

    r.replace_taxonomy_memberships([("NVDA", "X", "M7")])
    assert r.tickers_in_chain("Banks") == before  # survived the taxonomy replace


def test_inherit_does_not_downgrade_a_taxonomy_row(seeded_db_empty_cards):
    """Taxonomy wins: ON CONFLICT DO NOTHING must not relabel the source."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "NVDA", "M7")
    r.replace_taxonomy_memberships([("NVDA", "X", "M7")])
    r.inherit_sector_memberships({"M7": "X"})
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT source FROM {seeded_db_empty_cards._schema}.watchlist_chain "
            "WHERE ticker = 'NVDA' AND chain = 'M7'"
        )
        assert cur.fetchone()[0] == "taxonomy"


def test_removed_tickers_drop_out_of_chain_reads(seeded_db_empty_cards):
    """Membership rows outlive watchlist removal, so reads must join and filter.

    Without the join a removed ticker keeps answering the filter and keeps
    inflating chain counts.
    """
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "SPX", "Beta")
    r.replace_taxonomy_memberships([("SPX", "IDX", "Beta")])
    assert r.tickers_in_chain("Beta") == ["SPX"]

    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {seeded_db_empty_cards._schema}.watchlist "
            "SET removed_at = now() WHERE ticker = 'SPX'"
        )
    assert r.tickers_in_chain("Beta") == []
    assert "Beta" not in r.counts_by_chain()


def test_ticker_is_upper_cased_on_write(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "AMD", "Semi-Logic")
    r.replace_taxonomy_memberships([("amd", "L1", "Computer/GPU")])
    assert r.tickers_in_chain("Computer/GPU") == ["AMD"]


def test_changing_sector_retracts_the_old_inherited_row(seeded_db_empty_cards):
    """The regression that stranded NOV under Healthcare after it moved to Energy.

    Inheriting only ever filled gaps, so correcting `watchlist.sector` left the
    previous chain asserted forever and no re-seed could clear it.
    """
    r = _repo(seeded_db_empty_cards)
    layers = {"Healthcare": "DEF", "Energy": "DEF"}
    _add_ticker(seeded_db_empty_cards, "NOV", "Healthcare")
    r.inherit_sector_memberships(layers)
    assert "NOV" in r.tickers_in_chain("Healthcare")

    _add_ticker(seeded_db_empty_cards, "NOV", "Energy")  # sector corrected
    r.inherit_sector_memberships(layers)

    assert r.chains_by_ticker(["NOV"])["NOV"] == ["Energy"]
    assert "NOV" not in r.tickers_in_chain("Healthcare")


def test_reconcile_leaves_taxonomy_rows_alone(seeded_db_empty_cards):
    """Only inherited rows are retractable — taxonomy rows have another owner."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "IBM", "Quantum")
    r.replace_taxonomy_memberships([("IBM", "L2", "Cloud/Hyperscaler")])
    r.inherit_sector_memberships({"Quantum": "THM"})
    assert r.chains_by_ticker(["IBM"])["IBM"] == ["Cloud/Hyperscaler", "Quantum"]

    # Sector moves; the taxonomy-asserted chain must survive untouched.
    _add_ticker(seeded_db_empty_cards, "IBM", "Banks")
    r.inherit_sector_memberships({"Quantum": "THM", "Banks": "DEF"})
    assert r.chains_by_ticker(["IBM"])["IBM"] == ["Banks", "Cloud/Hyperscaler"]


def test_reconcile_is_idempotent(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "XOM", "Energy")
    r.inherit_sector_memberships({"Energy": "DEF"})
    first = r.chains_by_ticker(["XOM"])["XOM"]
    r.inherit_sector_memberships({"Energy": "DEF"})
    assert r.chains_by_ticker(["XOM"])["XOM"] == first
    assert r.drop_stale_inherited_memberships() == 0


def test_sync_ticker_writes_the_taxonomy_rows_for_one_ticker(seeded_db_empty_cards):
    """The mutation path: a newly added ticker is filterable immediately."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "NVDA", "Computer/GPU")
    got = r.sync_ticker_memberships(
        "NVDA", [("L1", "Computer/GPU"), ("X", "M7")], {"Computer/GPU": "L1"}
    )
    assert got == ["Computer/GPU", "M7"]


def test_sync_ticker_falls_back_to_sector_when_unenumerated(seeded_db_empty_cards):
    """A ticker the module does not list must still be reachable by some filter."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "PLTR", "Banks")
    assert r.sync_ticker_memberships("PLTR", [], {"Banks": "DEF"}) == ["Banks"]

    # And a sector that is not a known chain invents nothing.
    _add_ticker(seeded_db_empty_cards, "WEIRD", "Not-A-Chain")
    assert r.sync_ticker_memberships("WEIRD", [], {"Banks": "DEF"}) == []


def test_sync_ticker_touches_only_that_ticker(seeded_db_empty_cards):
    """Blast radius is the point — a mutation must not rewrite the whole table."""
    r = _repo(seeded_db_empty_cards)
    _add_ticker(seeded_db_empty_cards, "AMD", "Computer/GPU")
    _add_ticker(seeded_db_empty_cards, "ARM", "Semi-Logic/ASIC")
    r.replace_taxonomy_memberships(
        [("AMD", "L1", "Computer/GPU"), ("ARM", "L1", "Semi-Logic/ASIC")]
    )
    r.sync_ticker_memberships("AMD", [("X", "M7")], {"Computer/GPU": "L1"})
    # AMD keeps Computer/GPU as its sector fallback, gains M7 from the taxonomy.
    assert r.chains_by_ticker(["AMD"])["AMD"] == ["Computer/GPU", "M7"]
    assert r.chains_by_ticker(["ARM"])["ARM"] == ["Semi-Logic/ASIC"]


def test_sync_ticker_agrees_with_the_bulk_seed_path(seeded_db_empty_cards):
    """Two writers, one answer.

    The seeder rebuilds the whole table; the API syncs one ticker. If they
    disagree, a ticker's chains depend on which path last touched it — so pin
    them against each other rather than trusting the two implementations to
    stay aligned by inspection.
    """
    r = _repo(seeded_db_empty_cards)
    layers = {"Consumer": "DEF", "Healthcare": "DEF"}
    # Sector deliberately differs from the chain the taxonomy asserts.
    _add_ticker(seeded_db_empty_cards, "KO", "Healthcare")

    r.replace_taxonomy_memberships([("KO", "DEF", "Consumer")])
    r.inherit_sector_memberships(layers)
    bulk = r.chains_by_ticker(["KO"])["KO"]

    r.sync_ticker_memberships("KO", [("DEF", "Consumer")], layers)
    assert r.chains_by_ticker(["KO"])["KO"] == bulk == ["Consumer", "Healthcare"]
