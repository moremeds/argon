"""Seed `uw_scan.watchlist_chain` and optionally add the approved tickers.

Two separable jobs behind one script, because they must happen in this order:

1. `--add-tickers` inserts `SELECTED_ADDS` into the watchlist. Each gets a
   primary `sector` = its first chain, since `sector` still decides which single
   section a card renders under.
2. Membership seeding always runs: taxonomy rows from the module, then
   `sector`-inherited rows so nothing is left unreachable by the filter.

Adding a ticker is NOT free — it enlists the name in every per-ticker scheduled
job at roughly 240 UW calls/day. Against the mini that is a budget decision, so
`--add-tickers` is opt-in and the script prints the cost before doing it.

Idempotent and safe to re-run. Re-seeding replaces taxonomy rows wholesale (see
WatchlistChainRepository.replace_taxonomy_memberships for why) and leaves
inherited rows alone.

Reproduce (local):
    uv run python scripts/backfill/watchlist_chain_seed.py --dry-run
    uv run python scripts/backfill/watchlist_chain_seed.py --add-tickers
"""

from __future__ import annotations

import argparse

import psycopg

from uw_scan.storage.watchlist_chain import WatchlistChainRepository
from uw_scan.watchlist_taxonomy import LAYERS, SELECTED_ADDS, chains_for, memberships

CALLS_PER_TICKER_DAY = 240  # measured 2026-08-03..07 on the mini


def layer_for_chain() -> dict[str, str]:
    return {chain: layer.key for layer in LAYERS for chain in layer.chains}


def primary_sector(ticker: str) -> str:
    """The single tag a card renders under. First chain in declared layer order.

    Deliberately not "most specific" or "highest layer" — any rule here is a
    judgement call, and a stable, explainable one beats a clever one.
    """
    chains = chains_for(ticker)
    return chains[0] if chains else "Unassigned"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dsn", default="host=127.0.0.1 dbname=option_wizard_local user=chenxi"
    )
    ap.add_argument("--schema", default="uw_scan")
    ap.add_argument("--add-tickers", action="store_true", help="insert SELECTED_ADDS")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(args.dsn) as conn:
        repo = WatchlistChainRepository(conn, schema=args.schema)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT ticker FROM {args.schema}.watchlist WHERE removed_at IS NULL"
            )
            existing = {r[0] for r in cur.fetchall()}

        to_add = sorted(SELECTED_ADDS - existing)
        already = sorted(SELECTED_ADDS & existing)
        print(f"watchlist: {len(existing)} active")
        print(
            f"approved adds: {len(SELECTED_ADDS)}  new: {len(to_add)}  already held: {len(already)}"
        )
        if to_add:
            print(
                f"UW cost of adding {len(to_add)}: "
                f"~{len(to_add) * CALLS_PER_TICKER_DAY / 1000:.1f}k calls/day"
            )

        if args.dry_run:
            for t in to_add:
                print(f"  + {t:<6} sector={primary_sector(t)}  chains={chains_for(t)}")
            return 0

        if args.add_tickers and to_add:
            with conn.cursor() as cur:
                cur.executemany(
                    f"""
                    INSERT INTO {args.schema}.watchlist (ticker, sector, sort_rank)
                    VALUES (%s, %s, 0)
                    ON CONFLICT (ticker) DO UPDATE
                       SET sector = EXCLUDED.sector, removed_at = NULL
                    """,
                    [(t, primary_sector(t)) for t in to_add],
                )
            print(f"added {len(to_add)} tickers")

        n_tax = repo.replace_taxonomy_memberships(memberships())
        n_sec = repo.inherit_sector_memberships(layer_for_chain())
        conn.commit()
        print(f"memberships: {n_tax} taxonomy, {n_sec} inherited")

        counts = repo.counts_by_chain()
        empty = [c for c in layer_for_chain() if c not in counts]
        print(f"chains with active members: {len(counts)}/{len(layer_for_chain())}")
        if empty:
            # Named, not hidden: an empty chain is a rail button that filters to
            # nothing, and the UI needs to decide whether to render it.
            print(f"empty chains: {' '.join(sorted(empty))}")

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT count(*) FROM {args.schema}.watchlist w
                 WHERE w.removed_at IS NULL
                   AND NOT EXISTS (SELECT 1 FROM {args.schema}.watchlist_chain c
                                    WHERE c.ticker = w.ticker)
                """
            )
            print(f"active tickers with NO chain: {cur.fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
