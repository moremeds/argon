"""Read-only check of the silver-priced valuation band against production.

Writes NOTHING: insert_anchors is swapped for a collector and the connection is
rolled back. Splits for the silver-missing names are inserted INSIDE the same
transaction so the in-window guard runs exactly as it will once the widened
17:35 corporate-actions ingest has covered the fundamental universe.

Reproduce:
  ssh macmini 'docker run --rm --env-file /opt/argon/.env \
    --add-host host.docker.internal:host-gateway \
    -v /Volumes/DATA_LAKE/livewire/data-lake:/lake:ro \
    -v /tmp/argonpatch/validate.py:/tmp/validate.py:ro \
    ghcr.io/moremeds/argon-app:latest python /tmp/validate.py'
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal

import psycopg

from uw_scan.config import Settings
from uw_scan.sources.massive_fundamentals import MassiveFundamentalsProvider
from uw_scan.storage.corporate_actions import CorporateActionsRepository
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.worker.jobs import fundamental_anchors as mod

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
s = Settings.from_env()
silver_root = s.market_warehouse_lake_root / "silver/asset_class=equity"

with psycopg.connect(s.db_dsn()) as conn:
    ca = CorporateActionsRepository(conn, schema=s.db_schema)
    universe = ca.fetch_fundamental_universe_tickers()
    missing = [
        t for t in universe if not (silver_root / f"symbol={t}" / "1d.parquet").exists()
    ]
    print(f"universe={len(universe)} no_silver={len(missing)} {missing}")

    # STAGE_SPLITS=1 simulates the post-deploy split store for exactly those
    # names; STAGE_SPLITS=0 leaves production as it stands, which is the state
    # the job meets on the first night if it deploys before the widened ingest
    # has run. Both are worth measuring: the second is what the evidence rule in
    # `_bronze_basis_refusal` exists for.
    if os.environ.get("STAGE_SPLITS", "1") == "1":
        with MassiveFundamentalsProvider(s.massive_api_key.get_secret_value()) as p:
            added = 0
            for t in missing:
                for r in p.fetch_splits(t, limit=50):
                    if not (r["execution_date"] and r["split_from"] and r["split_to"]):
                        continue
                    ca.upsert_corporate_action(
                        ticker=t,
                        event_type="split",
                        event_date=r["execution_date"],
                        split_ratio=Decimal(r["split_to"]) / Decimal(r["split_from"]),
                    )
                    added += 1
                # Dividends too, or the simulation is not the widened ingest:
                # they are what makes a never-split name verifiable, and CCEP
                # carries 22 of them against 0 splits.
                for r in p.fetch_dividends(t, limit=24):
                    if not r["ex_dividend_date"]:
                        continue
                    ca.upsert_corporate_action(
                        ticker=t,
                        event_type="dividend",
                        event_date=r["ex_dividend_date"],
                        cash_amount=r.get("cash_amount"),
                    )
                    added += 1
        print(f"staged {added} corporate-action rows (rolled back at exit)")
    else:
        print("STAGE_SPLITS=0: reading the split store exactly as production has it")

    before = {}
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT ticker, buy_below, spot FROM (SELECT DISTINCT ON (ticker) * "
            f"FROM {s.db_schema}.valuation_anchors "
            "ORDER BY ticker, as_of DESC, result_id DESC) a"
        )
        before = {t: (bb, sp) for t, bb, sp in cur.fetchall()}

    collected: list[dict] = []
    FundamentalAnchorsRepository.insert_anchors = lambda self, rows: (
        collected.extend(rows) or len(rows)
    )

    counters = mod.fundamental_anchors(
        conn=conn,
        lake_root=s.lake_credit_etf_root,
        silver_root=silver_root,
        fx_root=s.lake_fx_root,
        schema=s.db_schema,
    )
    conn.rollback()

print("counters:", counters)

moved, entered, left, refused_now = [], [], [], []
for row in collected:
    t = row["ticker"]
    bb_new, spot = row.get("buy_below"), row.get("spot")
    bb_old, spot_old = before.get(t, (None, None))
    if bb_old is None and bb_new is None:
        continue
    was_in = bb_old is not None and spot_old is not None and spot_old <= bb_old
    is_in = bb_new is not None and spot is not None and spot <= bb_new
    if bb_old is not None and bb_new is None:
        refused_now.append((t, spot, bb_old, was_in))
    elif bb_old is not None and bb_new is not None:
        ratio = float(bb_new) / float(bb_old)
        if ratio < 0.9 or ratio > 1.1:
            moved.append((t, spot, bb_old, bb_new, was_in, is_in))
    if was_in and not is_in:
        left.append(t)
    if is_in and not was_in:
        entered.append(t)

print(f"\n=== bands that moved >10% ({len(moved)}) ===")
for t, spot, o, n, wi, ii in sorted(moved, key=lambda r: -abs(float(r[3]) / float(r[2]))):
    print(
        f"  {t:6s} spot={float(spot or 0):9.2f} buy_below {float(o):10.2f} -> "
        f"{float(n):9.2f}   {'IN' if wi else '--'} -> {'IN' if ii else '--'}"
    )
print(f"\n=== banded before, refused now ({len(refused_now)}) ===")
for t, spot, o, wi in refused_now:
    print(f"  {t:6s} spot={float(spot or 0):9.2f} was buy_below {float(o):10.2f} {'IN ZONE' if wi else ''}")
gained = [
    (r["ticker"], r.get("spot"), r.get("buy_below"), r.get("history_quarters"))
    for r in collected
    if r.get("buy_below") is not None and before.get(r["ticker"], (None, None))[0] is None
]
print(f"\n=== refused before, banded now ({len(gained)}) ===")
for t, spot, bb, hq in sorted(gained):
    mark = "  IN ZONE" if spot is not None and spot <= bb else ""
    print(f"  {t:6s} spot={float(spot or 0):9.2f} buy_below {float(bb):9.2f} hist={hq}q{mark}")

print(f"\nleft the buy zone: {sorted(left)}")
print(f"entered the buy zone: {sorted(entered)}")
