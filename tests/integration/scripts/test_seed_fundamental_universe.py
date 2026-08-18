"""Admission rules for the fundamental universe's third provenance.

Two properties are under test, and the second is the one that bites. Admission
must reach names that have no statements yet — otherwise the rule is circular,
because `fundamental_ingest` takes its ticker list from `fundamental_universe`,
so a name outside the universe never gets statements and a statements-keyed rule
can never let it in. And admission must be strictly additive: `seed_universe`
upserts `reason`, so a validated name re-offered by this source would have its
provenance silently rewritten to the weakest of the three.

Tickers are real listings from the chain taxonomy. No prices are involved.
"""

from __future__ import annotations

import importlib.util


def _seeder():
    spec = importlib.util.spec_from_file_location(
        "seed_fundamental_universe", "scripts/seed_fundamental_universe.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _add_chain_members(repo, rows: list[tuple[str, str, str]]) -> None:
    with repo.conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {repo._schema}.watchlist_chain (ticker, layer, chain)
                 VALUES (%s, %s, %s)
            ON CONFLICT (ticker, chain) DO NOTHING
            """,
            rows,
        )
    repo.conn.commit()


def test_chain_members_are_admitted_without_any_statements(seeded_db_empty_cards):
    """The circle-breaker: no statements exist for these names, and they still qualify."""
    repo = seeded_db_empty_cards
    mod = _seeder()
    _add_chain_members(
        repo,
        [
            ("CAMT", "L1", "ai-semiconductor"),
            ("LITE", "L3", "ai-optical-interconnect"),
        ],
    )

    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {repo._schema}.fundamental_statement_obs")
        assert cur.fetchone()[0] == 0, "precondition: no statements anywhere"

    got = mod.researched_tickers(repo.conn, set(), repo._schema)
    assert "CAMT" in got
    assert "LITE" in got


def test_already_admitted_names_are_excluded_not_downgraded(seeded_db_empty_cards):
    """A validated name offered again must not come back and overwrite its reason."""
    repo = seeded_db_empty_cards
    mod = _seeder()
    _add_chain_members(
        repo,
        [
            ("MSFT", "L2", "ai-hyperscaler"),
            ("CAMT", "L1", "ai-semiconductor"),
        ],
    )

    # Same database, same query — only `already` differs. Without the contrast the
    # test would pass just as well if MSFT were missing for some unrelated reason.
    assert "MSFT" in mod.researched_tickers(repo.conn, set(), repo._schema)

    got = mod.researched_tickers(repo.conn, {"MSFT"}, repo._schema)
    assert "MSFT" not in got
    assert "CAMT" in got


def test_the_three_provenances_stay_separable(seeded_db_empty_cards):
    """Each source writes a distinct `reason`, so a later reader cannot merge them."""
    repo = seeded_db_empty_cards
    mod = _seeder()
    _add_chain_members(repo, [("CAMT", "L1", "ai-semiconductor")])

    rows = [
        ("MSFT", None, "validated: in the 245-name breadth panel"),
        (
            "AMD",
            None,
            "core member; outside the validated panel (lake price history too short)",
        ),
    ]
    already = {t for t, _, _ in rows}
    rows += [
        (t, None, mod.RESEARCHED_REASON)
        for t in mod.researched_tickers(repo.conn, already, repo._schema)
    ]

    repo_obs = mod.FundamentalObsRepository(repo.conn, schema=repo._schema)
    repo_obs.seed_universe("ranked", rows)

    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT ticker, reason FROM {repo._schema}.fundamental_universe "
            f"WHERE tier = 'ranked'"
        )
        reasons = dict(cur.fetchall())

    assert reasons["CAMT"] == mod.RESEARCHED_REASON
    assert reasons["MSFT"].startswith("validated:")
    assert reasons["AMD"].startswith("core member;")
    assert len(set(reasons.values())) == 3
