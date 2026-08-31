"""Task 19: `domain` must SEPARATE, not universally coincide (see task-19-brief.md).

Before this task `mirror_watchlist_chain` stamped ONE hardcoded literal
(`domain="ai_infrastructure"`) onto every chain it mirrors — so `WHERE domain IN
(...)` matched every chain in the rail, not a subset. These tests pin the fix:
`CHAIN_DOMAIN` must route real chains to real domains, an unmapped chain must
land in `UNCLASSIFIED` rather than silently defaulting into the AI bucket, and a
re-seed must actually rewrite an existing row's `domain` (guards the
`ON CONFLICT ... DO UPDATE SET` list in `research_taxonomy.define_chains`).
"""

from __future__ import annotations

import pytest

from uw_scan.worker.jobs.research_taxonomy_seed import mirror_watchlist_chain

#: One representative ticker per chain under test. Chains that must land on the
#: AI/semi desk (Networking/Optical, Semi-Logic/ASIC, Generation/Nuclear) plus
#: chains that must NOT (Banks, Credit, Crypto, Sector-ETF, Macro, Space) — the
#: exact set the brief's tests assert on.
SEED_ROWS = (
    ("CIEN", "L3", "Networking/Optical"),
    ("AVGO", "L3", "Semi-Logic/ASIC"),
    ("OKLO", "L3", "Generation/Nuclear"),
    ("JPM", "L3", "Banks"),
    ("SYF", "L3", "Credit"),
    ("COIN", "L3", "Crypto"),
    ("XLK", "L3", "Sector-ETF"),
    ("GLD", "L3", "Macro"),
    ("RKLB", "L3", "Space"),
)


@pytest.fixture
def seeded_taxonomy_conn(seeded_db_empty_cards):
    """A real Postgres connection with `watchlist_chain` seeded and mirrored once.

    Mirroring once here (not just seeding raw rows) is required by
    `test_reseeding_rewrites_an_existing_rows_domain`, which corrupts an
    already-existing `research_chains.domain` value and re-mirrors to prove the
    `ON CONFLICT` SET list actually rewrites it — that test is a no-op if the row
    doesn't exist yet when the corruption UPDATE runs.
    """
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    with conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO {schema}.watchlist_chain (ticker, layer, chain)
                     VALUES (%s, %s, %s)
                ON CONFLICT (ticker, chain) DO NOTHING""",
            SEED_ROWS,
        )
    conn.commit()
    mirror_watchlist_chain(conn, schema=schema)
    return conn


def test_section_domains_exclude_the_non_ai_chains(seeded_taxonomy_conn):
    """The whole point: a domain filter must SEPARATE. Before this task every
    chain carried 'ai_infrastructure', so this filter returned all 38."""
    from uw_scan.worker.jobs.research_taxonomy_seed import mirror_watchlist_chain

    mirror_watchlist_chain(seeded_taxonomy_conn, schema="uw_scan")
    with seeded_taxonomy_conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT chain FROM uw_scan.research_chains
                WHERE domain IN ('ai_infrastructure','optical_communication','dc_buildout')"""
        )
        selected = {r[0] for r in cur.fetchall()}
    assert "Networking/Optical" in selected
    assert "Semi-Logic/ASIC" in selected
    assert "Generation/Nuclear" in selected
    for excluded in ("Banks", "Credit", "Crypto", "Sector-ETF", "Macro", "Space"):
        assert excluded not in selected, f"{excluded} must not reach the AI/semi desk"


def test_an_unmapped_chain_lands_in_unclassified_not_ai_infrastructure(
    seeded_taxonomy_conn,
):
    """A chain nobody has classified must be VISIBLY unclassified. Defaulting it
    into the AI bucket is how Banks ended up on an AI/semi desk in the first place."""
    from uw_scan.worker.jobs.research_taxonomy_seed import (
        CHAIN_DOMAIN,
        UNCLASSIFIED,
        mirror_watchlist_chain,
    )

    with seeded_taxonomy_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.watchlist_chain (ticker, chain, layer) VALUES (%s,%s,%s)",
            ("VRT", "Brand-New-Unmapped-Chain", "L3"),
        )
    assert "Brand-New-Unmapped-Chain" not in CHAIN_DOMAIN
    mirror_watchlist_chain(seeded_taxonomy_conn, schema="uw_scan")
    with seeded_taxonomy_conn.cursor() as cur:
        cur.execute(
            "SELECT domain FROM uw_scan.research_chains WHERE chain = %s",
            ("Brand-New-Unmapped-Chain",),
        )
        assert cur.fetchone()[0] == UNCLASSIFIED


def test_reseeding_rewrites_an_existing_rows_domain(seeded_taxonomy_conn):
    """Guards the ON CONFLICT SET list (Step 1). Seed a chain with the WRONG
    domain first, then re-mirror and assert the map won."""
    from uw_scan.worker.jobs.research_taxonomy_seed import mirror_watchlist_chain

    with seeded_taxonomy_conn.cursor() as cur:
        cur.execute(
            """UPDATE uw_scan.research_chains SET domain = 'wrong_on_purpose'
                WHERE chain = 'Networking/Optical'"""
        )
    mirror_watchlist_chain(seeded_taxonomy_conn, schema="uw_scan")
    with seeded_taxonomy_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT domain FROM uw_scan.research_chains WHERE chain = %s",
            ("Networking/Optical",),
        )
        assert [r[0] for r in cur.fetchall()] == ["optical_communication"]
