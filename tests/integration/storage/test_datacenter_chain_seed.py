"""Standing up a datacenter node is taxonomy rows, not code (spec §2 contract).

The five datacenter build-out chains are `Optical-Communication`'s siblings, and
the point of this test is what it does NOT touch: no assembler, no schema, no
scoring fork. If a chain node ever needs one of those, the extension contract is
broken and this file is where that shows up first.

WHY EVERY SPEC DECLARES THE DOMAIN THE MIRROR WRITES
----------------------------------------------------
`research_taxonomy_seed.CHAIN_DOMAIN` is the source of truth for what domain a
`watchlist_chain` name carries, and the seed script runs the mirror first and
these specs second. `research_chains`' primary key is
`(taxonomy_version, chain, layer)` — `domain` is NOT in the key, so it is a
per-LAYER attribute and nothing in the schema stops a chain from carrying two.
All five chain names are mirrored with a placeholder layer, so declaring a spec
under a domain the mirror did not use would leave one chain carrying two layers
under two domains and `chains(version, domain=...)` would return half a chain.
`test_no_chain_carries_two_domains` and
`test_every_datacenter_spec_declares_the_mirrored_domain` are the guards.
`Optical-Communication` escapes the whole question only because its spec name is
not a `watchlist_chain` name (the watchlist spells it `Networking/Optical`), so
it is unmirrored and may declare any domain.
"""

from __future__ import annotations

from uw_scan.fundamentals.chain_nodes import DATACENTER_CHAINS, OPTICAL_COMMUNICATION
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.research_taxonomy_seed import (
    CHAIN_DOMAIN,
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


def _open_members(conn, schema: str, chain: str | None = None) -> int:
    where = "taxonomy_version = %s AND valid_to IS NULL"
    params: list[object] = [TAXONOMY_V1]
    if chain:
        where += " AND chain = %s"
        params.append(chain)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {schema}.chain_membership WHERE {where}", params
        )
        return int(cur.fetchone()[0])


def _closed_members(conn, schema: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT count(*) FROM {schema}.chain_membership
                 WHERE taxonomy_version = %s AND valid_to IS NOT NULL""",
            (TAXONOMY_V1,),
        )
        return int(cur.fetchone()[0])


def _lay_the_mirrored_rail(conn, schema: str) -> None:
    """Seed watchlist_chain, mirror it, and REFUSE to proceed on an empty rail.

    Without the assertion these tests pass vacuously: if `mirror_watchlist_chain`
    ever stopped mirroring, `seed_chain_spec` would find nothing to move, return
    `memberships: 0`, and both the rank test and the two-domain test would still
    go green against an empty table.
    """
    with conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO {schema}.watchlist_chain (ticker, layer, chain)
                     VALUES (%s, %s, %s)
                ON CONFLICT (ticker, chain) DO NOTHING""",
            SEED_ROWS,
        )
    conn.commit()
    mirror_watchlist_chain(conn, schema=schema)
    assert _open_members(conn, schema) == len(SEED_ROWS), "the mirrored rail is empty"


def test_five_datacenter_chains_declared_in_buildout_order():
    assert {c.chain for c in DATACENTER_CHAINS} == set(EXPECTED)
    for spec in DATACENTER_CHAINS:
        assert len(spec.layers) == 1
        assert spec.layers[0].rank == EXPECTED[spec.chain]


def test_every_datacenter_spec_declares_the_mirrored_domain():
    """A second domain would split a chain across two `chains()` answers.

    Pinned to the MAP, not to a literal: a literal goes stale the moment a
    domain moves, and it did — the five chains left `ai_infrastructure` for
    `dc_buildout` and this assertion kept passing against a branch whose
    `research_chains` rows disagreed with themselves.

    Checks every spec in the module -- `DATACENTER_CHAINS` AND
    `OPTICAL_COMMUNICATION` -- not just the five build-out chains: a chain
    absent from `CHAIN_DOMAIN` is UNMIRRORED (its spec name is not a
    `watchlist_chain` name the mirror ever wrote) and may declare any domain
    it likes, per `chain_nodes.py`'s own docstring -- `.get(..., UNCLASSIFIED)`
    would otherwise demand an unmirrored spec answer `unclassified`, the
    opposite of the rule, and iterating only `DATACENTER_CHAINS` would never
    check `OPTICAL_COMMUNICATION` at all.
    """
    for spec in (OPTICAL_COMMUNICATION, *DATACENTER_CHAINS):
        if spec.chain not in CHAIN_DOMAIN:
            continue  # unmirrored: no watchlist_chain name to agree with
        assert spec.domain == CHAIN_DOMAIN[spec.chain], (
            f"{spec.chain}: spec declares {spec.domain!r} but the mirror writes "
            f"{CHAIN_DOMAIN[spec.chain]!r} — a chain split across "
            f"two domains answers chains(version, domain=...) with half of itself"
        )


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


def test_mirror_and_seed_stop_churning_after_the_first_cycle(seeded_db_empty_cards):
    """mirror -> seed -> mirror -> seed opens no further interval.

    `add_membership`'s own guard keys on (version, chain, LAYER, ticker), and a
    seed leaves no open row at the placeholder layer — so an unguarded mirror
    re-opens every placeholder and the next seed closes it again, two intervals
    per ticker per run, forever. That is the manufactured history the guard
    exists to prevent, and it would falsify the healer registry's standing claim
    that an unchanged placement opens no interval on a reseed.
    """
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _lay_the_mirrored_rail(conn, schema)
    for spec in DATACENTER_CHAINS:
        seed_chain_spec(conn, spec, schema=schema)

    settled_closed = _closed_members(conn, schema)
    settled_open = _open_members(conn, schema)
    assert settled_closed == len(SEED_ROWS)  # one retired placeholder per name

    for _ in range(2):
        counters = mirror_watchlist_chain(conn, schema=schema)
        assert counters["opened"] == 0
        assert counters["already_member"] == len(SEED_ROWS)
        for spec in DATACENTER_CHAINS:
            assert seed_chain_spec(conn, spec, schema=schema)["memberships"] == 0
        assert _closed_members(conn, schema) == settled_closed
        assert _open_members(conn, schema) == settled_open


def test_an_analyst_placement_survives_a_re_home_as_analyst(seeded_db_empty_cards):
    """Provenance is carried, not rewritten.

    `seed_chain_spec` is generic over `ChainSpec`, and `Optical-Communication`'s
    memberships are `evidence_class='analyst'`. Hardcoding `mirrored` on the
    reinsert would silently demote a human's assertion to a copy of the
    watchlist rail — the exact distinction migration 139 says the column exists
    to preserve.
    """
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _lay_the_mirrored_rail(conn, schema)
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    # Replace one mirrored placement with a human one at the same placeholder
    # layer, the way an analyst override would arrive.
    with conn.cursor() as cur:
        cur.execute(
            f"""UPDATE {schema}.chain_membership SET valid_to = now()
                 WHERE taxonomy_version = %s AND ticker = 'EQIX'
                   AND valid_to IS NULL""",
            (TAXONOMY_V1,),
        )
    conn.commit()
    repo.add_membership(
        TAXONOMY_V1,
        chain="DC-REIT/Colo",
        layer="L3",
        ticker="EQIX",
        evidence_class="analyst",
        approved_by="a-human",
        note="asserted placement; not a disclosure",
    )

    spec = next(s for s in DATACENTER_CHAINS if s.chain == "DC-REIT/Colo")
    seed_chain_spec(conn, spec, schema=schema)

    by_ticker = {m["ticker"]: m for m in repo.members(TAXONOMY_V1, "DC-REIT/Colo")}
    assert by_ticker["EQIX"]["layer"] == "DC-REIT-Colo"
    assert by_ticker["EQIX"]["evidence_class"] == "analyst"
    assert by_ticker["EQIX"]["approved_by"] == "a-human"
    # The row's own note survives; the move is appended to it.
    assert by_ticker["EQIX"]["note"].startswith("asserted placement; not a disclosure")
    assert "re-homed from layer 'L3'" in by_ticker["EQIX"]["note"]
    # DLR came through the mirror and stays a mirrored copy.
    assert by_ticker["DLR"]["evidence_class"] == "mirrored"


def test_an_interrupted_seed_heals_on_the_next_run(seeded_db_empty_cards):
    """The crash window leaves a name on BOTH layers, never on neither.

    Reinsert-then-retire is the whole point: a crash after the inserts and
    before the close is recoverable, because the recovery SELECT
    (`layer <> target AND valid_to IS NULL`) still matches the placeholder row.
    Closing first would leave zero open memberships and nothing left to find.
    """
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _lay_the_mirrored_rail(conn, schema)
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    spec = next(s for s in DATACENTER_CHAINS if s.chain == "DC-REIT/Colo")

    # Reproduce the interrupted state by hand: the target layer exists and both
    # names are open on it, and the placeholder rows were never closed.
    repo.define_chains(
        TAXONOMY_V1,
        [
            {
                "domain": spec.domain,
                "chain": spec.chain,
                "layer": spec.layers[0].layer,
                "layer_rank": spec.layers[0].rank,
                "description": spec.layers[0].description,
            }
        ],
    )
    for ticker in ("EQIX", "DLR"):
        repo.add_membership(
            TAXONOMY_V1,
            chain=spec.chain,
            layer=spec.layers[0].layer,
            ticker=ticker,
            evidence_class="mirrored",
            approved_by="seed_chain_spec",
            note="interrupted mid-seed",
        )
    assert _open_members(conn, schema, spec.chain) == 4  # both layers, both names

    counters = seed_chain_spec(conn, spec, schema=schema)
    # Two placeholders really were retired — a counter keyed on `add_membership`
    # would have reported 0 here, telling an operator nothing moved.
    assert counters["memberships"] == 2
    assert counters["opened"] == 0

    open_members = repo.members(TAXONOMY_V1, spec.chain)
    assert len(open_members) == 2
    assert {m["layer"] for m in open_members} == {spec.layers[0].layer}


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
