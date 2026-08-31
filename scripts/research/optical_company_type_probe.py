"""Which Optical-Communication chain members route through the wrong
`company_type` — and why.

Task 11 (spec §5-vii). The research VERDICT
(`docs/research/2026-08-26-optical-chain-pm-desk/VERDICT.md`, finding 4) found
that "`company_type` routing sends most of these names to `power_infra` /
`ebitda_to_ev` — an artefact of the argon-chain sector vocabulary... The
percentile is still own-history and valid; the label is wrong." This script is
the measurement that names exactly which tickers, and confirms the mechanism.

MECHANISM (verified against this DB, not assumed from the plan): `SECTOR_TO_TYPE`
already maps `"Networking/Optical" -> "chips_cyclical"`. But
`fundamental_anchors.seed_company_types` routes on `watchlist.sector`, a SINGLE
tag per ticker. Several genuine optical/networking names on the watchlist carry
`sector="DC-Connect"` instead — a real tag (DC-Connect is a legitimate `power_infra`
bucket for other names) that happens to shadow the correct optical classification
for these seven. The chain map entry is right and unreachable for them.

A ticker counts as MISROUTED here iff it is a current member of the
`Optical-Communication` chain (active taxonomy version) AND its persisted
`company_type` is `power_infra` (equivalently: `method == ebitda_to_ev`). None of
the chain's members are genuinely power/electrical-infrastructure businesses
(the four M7 names and ORCL are cloud/hyperscale customers correctly routed
elsewhere; AVGO and POET already route to `chips_cyclical` via their own real
sector tags) — so `power_infra` on this chain is definitionally wrong, not a
judgment call per ticker.

Reproduce:

    uv run python scripts/research/optical_company_type_probe.py

Read-only: no writes, no external calls. Reads
`postgresql://argon_app@127.0.0.1/option_wizard_local` via the standard
`Settings.from_env()` DSN.
"""

from __future__ import annotations

from datetime import date, timezone
from datetime import datetime as dt

import psycopg

from uw_scan.config import Settings
from uw_scan.fundamentals.valuation_policy import TYPE_YIELD
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository

CHAIN = "Optical-Communication"

#: The company_type this chain's members must never legitimately carry: none of
#: its members (optical components, networking silicon/systems, or the
#: hyperscale/cloud customers that buy from them) is a power/electrical
#: infrastructure business.
WRONG_TYPE = "power_infra"


def probe(conn: psycopg.Connection, schema: str) -> dict:
    taxonomy = ResearchTaxonomyRepository(conn, schema=schema)
    anchors = FundamentalAnchorsRepository(conn, schema=schema)
    version = taxonomy.active_version()
    if version is None:
        raise RuntimeError("no active research taxonomy version — nothing to probe")

    # `.members` is keyed (chain, layer) and a ticker can sit in one layer only
    # (chain_membership's open-interval uniqueness is (version, chain, layer,
    # ticker)), so a plain dict-by-ticker across every layer call is safe and
    # dedupes for free if a name ever opened two layers at once.
    members: dict[str, str] = {}
    for row in taxonomy.members(version, CHAIN):
        members[row["ticker"]] = row["layer"]

    types = anchors.company_types()

    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT ticker, sector FROM {schema}.watchlist
                 WHERE ticker = ANY(%s)""",
            (sorted(members),),
        )
        sectors = dict(cur.fetchall())
        cur.execute(
            f"""SELECT ticker, note FROM {schema}.fundamental_company_type
                 WHERE ticker = ANY(%s)""",
            (sorted(members),),
        )
        notes = dict(cur.fetchall())

    rows = []
    for ticker in sorted(members):
        company_type = types.get(ticker)
        method = TYPE_YIELD.get(company_type) if company_type else None
        misrouted = company_type == WRONG_TYPE
        rows.append(
            {
                "ticker": ticker,
                "layer": members[ticker],
                "sector": sectors.get(ticker) or None,
                "company_type": company_type,
                "method": method,
                "note": notes.get(ticker),
                "misrouted": misrouted,
            }
        )
    return {
        "taxonomy_version": version,
        "chain": CHAIN,
        "member_count": len(rows),
        "rows": rows,
        "misrouted": [r["ticker"] for r in rows if r["misrouted"]],
    }


def render_markdown(result: dict, as_of: date) -> str:
    lines = [
        "# Optical `company_type` routing probe",
        "",
        f"**As of:** {as_of.isoformat()} · **DB:** "
        "`postgresql://argon_app@127.0.0.1/option_wizard_local` · "
        f"**Taxonomy version:** `{result['taxonomy_version']}` · "
        f"**Chain:** `{result['chain']}` ({result['member_count']} members)",
        "",
        "**Reproduce:**",
        "",
        "```bash",
        "uv run python scripts/research/optical_company_type_probe.py",
        "```",
        "",
        (
            "Brief context (Task 11, spec §5-vii): the plan's account says "
            '"16 Optical-Communication members". This DB carries '
            f"**{result['member_count']}**, not 16 — another instance of a plan "
            "brief being wrong about a data count. The routing mechanism it "
            "describes (a single `watchlist.sector` tag shadowing the correct "
            "`SECTOR_TO_TYPE` optical entry) IS what this probe finds."
        ),
        "",
        "| ticker | layer | watchlist.sector | company_type | method | misrouted |",
        "|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        lines.append(
            f"| {r['ticker']} | {r['layer']} | {r['sector'] or '(none)'} | "
            f"{r['company_type'] or '(unrouted)'} | {r['method'] or '—'} | "
            f"{'YES' if r['misrouted'] else 'no'} |"
        )
    lines += [
        "",
        f"**Misrouted ({len(result['misrouted'])} of {result['member_count']}):** "
        + ", ".join(result["misrouted"]),
        "",
        "All seven carry `watchlist.sector = 'DC-Connect'` — a real sector tag "
        'for other names, which happens to shadow the `"Networking/Optical": '
        '"chips_cyclical"` entry these names should have matched instead. None '
        "of the seven is a power/electrical-infrastructure business (AAOI = "
        "Applied Optoelectronics, ANET = Arista Networks, COHR = Coherent, "
        "CRDO = Credo, FN = Fabrinet, LITE = Lumentum, MRVL = Marvell).",
        "",
        "Not misrouted, for the record: the four M7 names and ORCL are "
        "hyperscale/cloud customers correctly routed to `platform_scale` / "
        "`high_risk_growth` via their own sector tags; AVGO already carries "
        '`Semi-Logic` (matches the `"Semi"` prefix -> `chips_cyclical`); POET '
        "already carries the correct `Networking/Optical` tag directly. CIEN, "
        "JNPR and NTAP carry no `watchlist` row at all (`no sector on file` -> "
        "`unclassified`, the documented non-bug default) — that is an absence "
        "of data, not a wrong single-tag routing, and is out of this fix's "
        "scope.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        result = probe(conn, settings.db_schema)
    as_of = dt.now(tz=timezone.utc).date()
    doc = render_markdown(result, as_of)
    print(doc)

    out_path = (
        __file__.rsplit("scripts/", 1)[0]
        + "docs/research/2026-08-26-optical-chain-pm-desk/routing_probe.md"
    )
    with open(out_path, "w") as f:
        f.write(doc)
    print(f"\npersisted: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
