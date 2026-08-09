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
