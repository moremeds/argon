#!/usr/bin/env python
"""Probe SEC XBRL for the two fields UW does not expose.

Spec: docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md (§3.3).
Brief: docs/masterplan/2026-08-11-fundamental-data-brief-for-livewire.md (§6.1, §6.2).

Two gaps, both measured rather than assumed:

1. NONCONTROLLING INTEREST — UW's balance sheet has no NCI field, so
   `assets = liabilities + equity` fails for 14.2% of rows, one-directionally,
   concentrated in consolidating filers (MU, CEG, ORCL, TSM, DELL, AMD). Without
   NCI those six tickers' equity ratios are wrong and must render `na`.
2. CURRENT DEBT — UW ships a `current_debt` column that is null for all 25
   tickers. Net-debt calculations want the current tranche.

SEC XBRL is free, keyless, and authoritative (it IS the filing). The only
requirement is a declared User-Agent; SEC rate-limits to 10 req/s and blocks
anonymous clients.

Concept names are tried in order because filers tag the same economic quantity
differently — `MinorityInterest` is the older tag, and the
`...IncludingPortionAttributableToNoncontrollingInterest` pair is how modern
filings express it. A ticker is only "uncovered" if EVERY candidate misses.

Reproduce:

    uv run python scripts/research/sec_xbrl_gapfill_probe.py

Writes `sec_xbrl_gapfill.json` + `sec-xbrl-gapfill.md` under
`docs/research/2026-08-10-fundamental-source-coverage/`.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

OUT_DIR = Path("docs/research/2026-08-10-fundamental-source-coverage")
COVERAGE = OUT_DIR / "coverage.json"

# SEC requires a real contact string and blocks clients without one.
UA = "argon-research chenxi lcxxcllcx@gmail.com"
SEC = "https://data.sec.gov"
TICKER_MAP = "https://www.sec.gov/files/company_tickers.json"

# SEC asks for <=10 req/s. One call per concept per ticker is well inside that,
# but sleep anyway — a 403 for rudeness reads exactly like "no data".
THROTTLE_S = 0.15

# The six tickers whose UW rows fail the balance identity (brief §3.3.2), plus
# two clean controls. Without controls, "the probe returns nothing" and "the
# concept does not exist" are indistinguishable.
NCI_TICKERS = ["MU", "CEG", "ORCL", "TSM", "DELL", "AMD"]
CONTROLS = ["NVDA", "MSFT"]

# (taxonomy, tag) pairs, tried in order. Two taxonomies, not one: domestic
# filers tag under `us-gaap`, but foreign private issuers filing 20-F use
# `ifrs-full`. Probing only us-gaap returns 404 for TSM and reads as "SEC has no
# data for TSM" — it has plenty, under a different taxonomy.
CONCEPTS: dict[str, list[tuple[str, str]]] = {
    "noncontrolling_interest": [
        ("us-gaap", "MinorityInterest"),
        (
            "us-gaap",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        ("ifrs-full", "NoncontrollingInterests"),
    ],
    "current_debt": [
        ("us-gaap", "DebtCurrent"),
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "ShortTermBorrowings"),
        ("ifrs-full", "CurrentPortionOfLongtermBorrowings"),
    ],
    # Control concept: every filer has this. If it misses, the probe is broken,
    # not the data — the same role "CoWoS" played in the EDGAR full-text probe.
    "_control_assets": [("us-gaap", "Assets"), ("ifrs-full", "Assets")],
}


def load_cik_map(client: httpx.Client) -> dict[str, str]:
    """ticker -> zero-padded 10-digit CIK."""
    rows = client.get(TICKER_MAP).json()
    out: dict[str, str] = {}
    for r in rows.values():
        out[str(r["ticker"]).upper()] = f"{int(r['cik_str']):010d}"
    return out


def probe_concept(
    client: httpx.Client, cik: str, taxonomy: str, concept: str
) -> dict[str, Any]:
    """One concept for one filer, under one taxonomy."""
    url = f"{SEC}/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json"
    resp = client.get(url)
    time.sleep(THROTTLE_S)
    if resp.status_code == 404:
        return {"http_status": 404, "units": None}  # concept genuinely absent
    if resp.status_code != 200:
        return {
            "http_status": resp.status_code,
            "units": None,
            "error": resp.text[:120],
        }
    payload = resp.json()
    units = payload.get("units") or {}
    facts = units.get("USD") or next(iter(units.values()), [])
    quarterly = [f for f in facts if f.get("form") in ("10-Q", "10-K", "20-F")]
    ends = sorted(f.get("end", "") for f in quarterly if f.get("end"))
    forms = sorted({f.get("form") for f in quarterly if f.get("form")})
    return {
        "http_status": 200,
        "forms": forms,
        # 20-F only => ANNUAL. A quarterly pipeline cannot consume it, however
        # many facts there are.
        "quarterly_capable": "10-Q" in forms,
        "unit_keys": sorted(units),
        "fact_count": len(facts),
        "filing_facts": len(quarterly),
        "first_period": ends[0] if ends else None,
        "last_period": ends[-1] if ends else None,
        "latest_value": quarterly[-1].get("val") if quarterly else None,
    }


def main() -> int:
    if not COVERAGE.exists():
        print(
            f"run fundamental_source_coverage.py first: {COVERAGE} missing",
            file=sys.stderr,
        )
        return 2

    tickers = NCI_TICKERS + CONTROLS
    # proxy=None is load-bearing, not defensive. With the macOS system proxy
    # inherited, every sec.gov connect dies with
    # `SSL: UNEXPECTED_EOF_WHILE_READING` — the same class of failure that made
    # `MassiveWsClient` pass proxy=None (root CLAUDE.md, standing rules). curl
    # confirms it: default 000, `--noproxy '*'` 200.
    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
        timeout=60.0,
        proxy=None,
        trust_env=False,
    ) as client:
        print("resolving CIKs")
        cikmap = load_cik_map(client)
        missing = [t for t in tickers if t not in cikmap]
        if missing:
            print(f"  no CIK for: {missing}")

        results: dict[str, Any] = {}
        for t in tickers:
            cik = cikmap.get(t)
            if not cik:
                results[t] = {"error": "no CIK in SEC ticker map"}
                print(f"  {t:6} NO CIK")
                continue
            per: dict[str, Any] = {"cik": cik}
            for gap, candidates in CONCEPTS.items():
                hit = None
                for taxonomy, concept in candidates:
                    r = probe_concept(client, cik, taxonomy, concept)
                    if r.get("filing_facts"):
                        hit = {"concept": concept, "taxonomy": taxonomy, **r}
                        break
                per[gap] = hit or {"concept": None, "found": False}
            results[t] = per
            nci = per["noncontrolling_interest"]
            cd = per["current_debt"]
            print(
                f"  {t:6} NCI={nci.get('concept') or '—':46.46} "
                f"[{nci.get('taxonomy') or '-':9}] n={nci.get('filing_facts')} "
                f"Q={nci.get('quarterly_capable')}  "
                f"curDebt={cd.get('concept') or '—':30.30} n={cd.get('filing_facts')}",
                flush=True,
            )

    payload = {
        "probed_at": "2026-08-11",
        "reproduce": "uv run python scripts/research/sec_xbrl_gapfill_probe.py",
        "concepts_tried": CONCEPTS,
        "nci_tickers": NCI_TICKERS,
        "controls": CONTROLS,
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "sec_xbrl_gapfill.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT_DIR / "sec-xbrl-gapfill.md").write_text(_render(payload))
    print(f"\nwrote {OUT_DIR}/sec_xbrl_gapfill.json and sec-xbrl-gapfill.md")
    return 0


def _render(p: dict[str, Any]) -> str:
    lines = [
        "# SEC XBRL gap-fill — noncontrolling interest and current debt",
        "",
        f"*Probed {p['probed_at']} · REGENERATED on every run · free, keyless, authoritative*",
        "",
        "```bash",
        p["reproduce"],
        "```",
        "",
        "Tickers are the six whose UW rows fail `assets = liabilities + equity`,"
        " plus two clean controls — without controls, an empty result and a broken"
        " probe look identical.",
        "",
        "| Ticker | CIK | NCI concept | taxonomy | facts | quarterly? | span | current-debt concept | facts |",
        "|---|---|---|---|---:|---|---|---|---:|",
    ]
    for t, r in p["results"].items():
        if r.get("error"):
            lines.append(f"| {t} | — | {r['error']} | — | — | — | — |")
            continue
        n = r.get("noncontrolling_interest") or {}
        c = r.get("current_debt") or {}
        span = (
            f"{n.get('first_period')} → {n.get('last_period')}"
            if n.get("filing_facts")
            else "—"
        )
        tag = "**control** " if t in p["controls"] else ""
        lines.append(
            f"| {tag}{t} | {r.get('cik')} | `{n.get('concept') or '—'}` |"
            f" `{n.get('taxonomy') or '—'}` | {n.get('filing_facts') or 0} |"
            f" {'yes' if n.get('quarterly_capable') else '**annual only**' if n.get('filing_facts') else '—'} | {span} |"
            f" `{c.get('concept') or '—'}` | {c.get('filing_facts') or 0} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
