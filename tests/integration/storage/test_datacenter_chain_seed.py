"""Standing up a datacenter node is taxonomy rows, not code (spec §2 contract).

The five datacenter build-out chains are `Optical-Communication`'s siblings, and
the point of this test is what it does NOT touch: no assembler, no schema, no
scoring fork. If a chain node ever needs one of those, the extension contract is
broken and this file is where that shows up first.

WHY EVERY SPEC IS `ai_infrastructure` AND NOT A NEW DOMAIN
---------------------------------------------------------
`research_chains`' primary key is `(taxonomy_version, chain, layer)` — `domain`
is NOT in the key, so it is a per-LAYER attribute. All five chain names are
already mirrored from `watchlist_chain` under `domain='ai_infrastructure'` with a
placeholder layer, so declaring the specs under a second domain would leave one
chain carrying two layers under two domains and `chains(version, domain=...)`
would return half a chain. `test_no_chain_carries_two_domains` is the guard.
`Optical-Communication` escapes the whole question only because its spec name
differs from the watchlist's `Networking/Optical`.
"""

from __future__ import annotations

from uw_scan.fundamentals.chain_nodes import DATACENTER_CHAINS
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.research_taxonomy_seed import (
    TAXONOMY_V1,
    mirror_watchlist_chain,
    seed_chain_spec,
)

#: chain -> the rank its single real layer carries. Build-out reading order,
#: sparse so an intra-chain split discovered later slots between two of these
#: without renumbering.
EXPECTED = {
    "EPC/Construction": 10,
    "Generation/Nuclear": 20,
    "Power/Electrical": 30,
    "Cooling/Thermal": 40,
    "DC-REIT/Colo": 50,
}

#: Real members, copied verbatim from `watchlist_taxonomy` L3. The test DB's
#: baseline carries no `watchlist_chain` rows (that table is seeded at runtime,
#: not by a migration), so the mirrored rail these specs re-home has to be laid
#: down here. VRT is Power/Electrical, not Cooling/Thermal — the argon taxonomy
#: files Vertiv under electrical distribution.
SEED_ROWS = (
    ("MTZ", "L3", "EPC/Construction"),
    ("EME", "L3", "EPC/Construction"),
    ("OKLO", "L3", "Generation/Nuclear"),
    ("CEG", "L3", "Generation/Nuclear"),
    ("VRT", "L3", "Power/Electrical"),
    ("ETN", "L3", "Power/Electrical"),
    ("MOD", "L3", "Cooling/Thermal"),
    ("AAON", "L3", "Cooling/Thermal"),
    ("EQIX", "L3", "DC-REIT/Colo"),
    ("DLR", "L3", "DC-REIT/Colo"),
)


def _lay_the_mirrored_rail(conn, schema: str) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO {schema}.watchlist_chain (ticker, layer, chain)
                     VALUES (%s, %s, %s)
                ON CONFLICT (ticker, chain) DO NOTHING""",
            SEED_ROWS,
        )
    conn.commit()
    mirror_watchlist_chain(conn, schema=schema)


def test_five_datacenter_chains_declared_in_buildout_order():
    assert {c.chain for c in DATACENTER_CHAINS} == set(EXPECTED)
    for spec in DATACENTER_CHAINS:
        assert len(spec.layers) == 1
        assert spec.layers[0].rank == EXPECTED[spec.chain]


def test_every_datacenter_spec_declares_the_mirrored_domain():
    """A second domain would split a chain across two `chains()` answers."""
    assert {c.domain for c in DATACENTER_CHAINS} == {"ai_infrastructure"}


def test_seed_replaces_placeholder_layer_with_real_rank(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _lay_the_mirrored_rail(conn, schema)
    for spec in DATACENTER_CHAINS:
        counters = seed_chain_spec(conn, spec, schema=schema)
        assert counters["layers"] == 1
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT chain, layer, layer_rank FROM {schema}.research_chains
                 WHERE taxonomy_version = %s AND chain = ANY(%s)""",
            (TAXONOMY_V1, list(EXPECTED)),
        )
        rows = cur.fetchall()
    ranks = {chain: rank for chain, _layer, rank in rows if rank > 0}
    assert ranks == EXPECTED


def test_memberships_move_onto_the_real_layer(seeded_db_empty_cards):
    """Re-home is retire-and-reinsert: the open row is the only current one."""
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _lay_the_mirrored_rail(conn, schema)
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    for spec in DATACENTER_CHAINS:
        counters = seed_chain_spec(conn, spec, schema=schema)
        assert counters["memberships"] == 2

    open_members = repo.members(TAXONOMY_V1, "DC-REIT/Colo")
    assert {m["ticker"] for m in open_members} == {"EQIX", "DLR"}
    assert {m["layer"] for m in open_members} == {"DC-REIT-Colo"}

    # The placeholder interval is closed, not deleted: "was EQIX in this chain
    # when that report was written" has to stay answerable.
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT count(*) FROM {schema}.chain_membership
                 WHERE taxonomy_version = %s AND chain = %s
                   AND layer = 'L3' AND valid_to IS NOT NULL""",
            (TAXONOMY_V1, "DC-REIT/Colo"),
        )
        assert cur.fetchone()[0] == 2


def test_seeding_twice_moves_nothing_the_second_time(seeded_db_empty_cards):
    """A reseed must not manufacture a history of identical intervals."""
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _lay_the_mirrored_rail(conn, schema)
    for spec in DATACENTER_CHAINS:
        seed_chain_spec(conn, spec, schema=schema)
    for spec in DATACENTER_CHAINS:
        assert seed_chain_spec(conn, spec, schema=schema)["memberships"] == 0

    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT count(*) FROM {schema}.chain_membership
                 WHERE taxonomy_version = %s AND valid_to IS NULL""",
            (TAXONOMY_V1,),
        )
        assert cur.fetchone()[0] == len(SEED_ROWS)


def test_no_chain_carries_two_domains(seeded_db_empty_cards):
    """`domain` is a per-layer column; one chain must still mean one domain.

    Nothing in the schema enforces this — the PK is (version, chain, layer) — so
    a spec declared under a domain the mirror did not use would split the chain
    silently, and `chains(version, domain=...)` would answer with half of it.
    """
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _lay_the_mirrored_rail(conn, schema)
    for spec in DATACENTER_CHAINS:
        seed_chain_spec(conn, spec, schema=schema)

    repo = ResearchTaxonomyRepository(conn, schema=schema)
    active = repo.active_version()
    assert active == TAXONOMY_V1
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT chain, array_agg(DISTINCT domain ORDER BY domain)
                  FROM {schema}.research_chains
                 WHERE taxonomy_version = %s
                 GROUP BY chain
                HAVING count(DISTINCT domain) > 1""",
            (active,),
        )
        assert cur.fetchall() == []
