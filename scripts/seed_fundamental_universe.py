"""Seed the two-tier fundamental universe (migration 114, spec §4.3 rev 5).

    uv run python scripts/seed_fundamental_universe.py [--dry-run]

`core` is the hand-curated chain-spanning list the valuation/narrative stages run
over. `ranked` starts from the breadth probe's own gates, replayed from the raw
rows rather than copied as a ticker list, so membership stays tied to the
evidence that justified it — re-running the probe and re-running this script
agree by construction.

`core ⊂ ranked` is verified, never assumed, and the check pays for itself: 12 of
the 25 core names are missing from the probe's candidate set. **None were
rejected on their fundamentals.** The probe gated on *local lake price depth*
(>=2,500 bars starting on or before 2013-01-01) because it needed forward returns
to validate against, and the lake mirror is shallow for these names — AMD starts
2015-01-02, AVGO 2016-02-02, ANET 2014-06-06, though AMD has traded since 1972.

Statement ingest reads UW and never touches the lake, so that limit does not
apply here and the 12 are seeded. The distinction survives in the `reason`
column: 245 names carry validation backing, the rest are ingested and ranked
without it. Do not let a later reader collapse those into one claim.

A third source extends the same argument to every name this desk researches —
see `researched_tickers`. That source reads a live table, so unlike the breadth
replay this script is no longer a pure function of committed files: re-running it
after the chain taxonomy changes gives a different membership, by design. The
`reason` column is what keeps the three provenances separable, and membership is
only ever added — `seed_universe` upserts `reason`, so a name already admitted by
a higher-provenance source is excluded from the new one rather than overwritten.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.fundamental_obs import FundamentalObsRepository

BREADTH = Path(
    "docs/research/2026-08-11-fundamental-signal-validation/universe_breadth.json"
)

CORE_25: dict[str, tuple[str, ...]] = {
    "L1": ("NVDA", "AMD", "AVGO", "MRVL", "TSM", "ASML", "AMAT", "MU"),
    "L2": ("MSFT", "GOOGL", "AMZN", "META", "ORCL"),
    "L3": ("ANET", "VRT", "ETN", "GEV", "CEG", "VST"),
    "L45": ("DELL", "SMCI", "PLTR", "CRWD", "NOW", "APP"),
}


def ranked_tickers() -> tuple[list[str], dict[str, int]]:
    """Names passing the breadth probe's gates, re-applied from the raw rows."""
    doc = json.loads(BREADTH.read_text())
    gates = doc["gates"]
    keep = [
        row["ticker"]
        for row in doc["names"]
        if row.get("bars")
        and row["bars"] >= gates["min_bars"]
        and row.get("first_bar")
        and row["first_bar"] <= gates["max_start"]
        and row.get("quarters")
        and row["quarters"] >= gates["min_quarters"]
    ]
    return sorted(keep), {"expected": doc["usable"], "recomputed": len(keep)}


RESEARCHED_REASON = "researched: industry-chain member, no validation backing"


def researched_tickers(conn, already: set[str], schema: str) -> list[str]:
    """Names this desk researches that the breadth probe never got to consider.

    Sourced from `watchlist_chain` — the durable industry-chain taxonomy — plus
    any name that somehow already carries statements. **The chain half is what
    makes this work in production**, and the reason is a circle worth stating:
    `fundamental_ingest` draws its ticker list from `fundamental_universe`, so a
    name with no membership never gets statements, and a rule that admits only
    statement-bearing names can never let it in. Keying on statements alone reads
    correct on a laptop and is a silent no-op on the mini, because the extra
    statement-bearing names in `option_wizard_local` are residue from a research
    backfill run while the mini was down — not a state production shares.

    These names carry no validation backing at all: the breadth probe gated on
    LOCAL LAKE PRICE DEPTH because it needed forward returns to validate against,
    which says nothing about whether a name is ingestable. That is the same
    argument this module's docstring already makes for the 12 core names.

    `already` is excluded rather than re-seeded. `seed_universe` upserts `reason`,
    so re-admitting a validated name from here would quietly downgrade its
    provenance to this one.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ticker FROM {schema}.watchlist_chain
             UNION
            SELECT DISTINCT ticker FROM {schema}.fundamental_statement_obs
             ORDER BY 1
            """
        )
        return [t for (t,) in cur.fetchall() if t not in already]


def main() -> int:
    dry = "--dry-run" in sys.argv
    ranked, counts = ranked_tickers()
    if counts["recomputed"] != counts["expected"]:
        print(
            f"!! gate replay gives {counts['recomputed']} names, probe recorded "
            f"{counts['expected']} — the gates and the stored result disagree",
            file=sys.stderr,
        )
        return 1

    core = [
        (t, layer, "core chain coverage") for layer, ts in CORE_25.items() for t in ts
    ]
    core_names = {t for t, _, _ in core}
    missing = sorted(core_names - set(ranked))

    ranked_rows = [
        (t, None, "validated: in the 245-name breadth panel") for t in ranked
    ]
    ranked_rows += [
        (
            t,
            None,
            "core member; outside the validated panel (lake price history too short)",
        )
        for t in missing
    ]

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        researched = researched_tickers(
            conn, {t for t, _, _ in ranked_rows}, settings.db_schema
        )
        ranked_rows += [(t, None, RESEARCHED_REASON) for t in researched]

        print(f"core    {len(core)} names")
        print(
            f"ranked  {len(ranked)} validated + {len(missing)} core-containment "
            f"+ {len(researched)} researched = {len(ranked_rows)}"
        )
        if missing:
            print(f"  core names outside the validated panel: {', '.join(missing)}")
        if dry:
            return 0

        repo = FundamentalObsRepository(conn, schema=settings.db_schema)
        repo.seed_universe("core", core)
        repo.seed_universe("ranked", ranked_rows)
        print(
            f"seeded: core={len(repo.list_universe('core'))} "
            f"ranked={len(repo.list_universe('ranked'))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
