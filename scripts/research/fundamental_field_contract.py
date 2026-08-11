#!/usr/bin/env python
"""P1a data-contract spike, part 2 — the field map, the overlap, the hash rule.

Spec: docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md (§3.2, §4.4, P1a).
Part 1 (`fundamental_source_coverage.py`) measured WHICH tickers have data. This
measures WHAT the data says, which is the remaining P1a work:

1. FIELD INVENTORY — every `financials.<group>.<field>` massive `/vX` emits, and
   how many of the covered tickers actually carry it. A field present for NVDA is
   not a field present for the cohort; the map may only claim what the cohort has.
2. OVERLAP RECONCILIATION — `/vX` and `/v2` both cover roughly 2010–2020. Where
   they overlap they must agree, or the disagreement needs a stated rule. A4 says
   "reconcile disagreements, never silently prefer one" — this is what makes that
   testable rather than aspirational.
3. ENVELOPE VARIANCE — two identical calls, diffed. Whatever differs is what
   `content_hash` must exclude, or every refresh looks like a restatement (§4.4).
4. ADR / FX EVIDENCE — `/v2` carries `shareFactor` and
   `foreignCurrencyUSDExchangeRate`, which is the only measured source we have for
   the ADR ratio the spec flags as unsourced.

Reproduce:

    MASSIVE_API_KEY=... uv run python scripts/research/fundamental_field_contract.py

Writes `field_contract.json` + `field-contract.md` under
`docs/research/2026-08-10-fundamental-source-coverage/`.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

OUT_DIR = Path("docs/research/2026-08-10-fundamental-source-coverage")
COVERAGE = OUT_DIR / "coverage.json"

# /vX rejects limit>100 (see part 1). 100 reaches back past 2010 for every
# ticker with that much history, which is what the overlap probe needs.
VX_LIMIT = 100
VX_INVENTORY_LIMIT = 4  # recent quarters only — presence, not history

# Tickers used for the overlap probe. Chosen for the WIDEST `/vX` ∩ `/v2`
# window (both endpoints cover ~2010-2020 for these), not at random: a narrow
# overlap gives one comparable quarter and no way to tell a systematic
# disagreement from a single bad period.
OVERLAP_TICKERS = ["NVDA", "AMD", "MSFT", "AMZN", "ETN"]

# The field map. Every `/vX` path here was read off a live payload, not guessed
# — `income_statement.revenues` exists, `income_statement.revenue` does not.
# `/v2` names are the frozen-history equivalents used for reconciliation.
# (canonical, vX_group, vX_field, v2_key)
FIELD_MAP: list[tuple[str, str, str, str]] = [
    # --- income statement ---
    ("revenue", "income_statement", "revenues", "revenues"),
    ("cost_of_revenue", "income_statement", "cost_of_revenue", "costOfRevenue"),
    ("gross_profit", "income_statement", "gross_profit", "grossProfit"),
    (
        "operating_income",
        "income_statement",
        "operating_income_loss",
        "operatingIncome",
    ),
    (
        "operating_expenses",
        "income_statement",
        "operating_expenses",
        "operatingExpenses",
    ),
    (
        "pretax_income",
        "income_statement",
        "income_loss_from_continuing_operations_before_tax",
        "earningsBeforeTax",
    ),
    (
        "income_tax",
        "income_statement",
        "income_tax_expense_benefit",
        "incomeTaxExpense",
    ),
    ("net_income", "income_statement", "net_income_loss", "netIncome"),
    (
        "rnd_expense",
        "income_statement",
        "research_and_development",
        "researchAndDevelopmentExpense",
    ),
    (
        "sga_expense",
        "income_statement",
        "selling_general_and_administrative_expenses",
        "sellingGeneralAndAdministrativeExpense",
    ),
    (
        "eps_diluted",
        "income_statement",
        "diluted_earnings_per_share",
        "earningsPerDilutedShare",
    ),
    (
        "eps_basic",
        "income_statement",
        "basic_earnings_per_share",
        "earningsPerBasicShare",
    ),
    (
        "diluted_shares",
        "income_statement",
        "diluted_average_shares",
        "weightedAverageSharesDiluted",
    ),
    (
        "basic_shares",
        "income_statement",
        "basic_average_shares",
        "weightedAverageShares",
    ),
    # --- balance sheet ---
    ("total_assets", "balance_sheet", "assets", "assets"),
    ("current_assets", "balance_sheet", "current_assets", "assetsCurrent"),
    ("noncurrent_assets", "balance_sheet", "noncurrent_assets", "assetsNonCurrent"),
    ("total_liabilities", "balance_sheet", "liabilities", "totalLiabilities"),
    (
        "current_liabilities",
        "balance_sheet",
        "current_liabilities",
        "currentLiabilities",
    ),
    (
        "noncurrent_liabilities",
        "balance_sheet",
        "noncurrent_liabilities",
        "liabilitiesNonCurrent",
    ),
    ("equity", "balance_sheet", "equity", "shareholdersEquity"),
    ("inventory", "balance_sheet", "inventory", "inventory"),
    (
        "accounts_payable",
        "balance_sheet",
        "accounts_payable",
        "tradeAndNonTradePayables",
    ),
    ("long_term_debt", "balance_sheet", "long_term_debt", "debtNonCurrent"),
    ("fixed_assets", "balance_sheet", "fixed_assets", "propertyPlantEquipmentNet"),
    (
        "intangible_assets",
        "balance_sheet",
        "intangible_assets",
        "goodwillAndIntangibleAssets",
    ),
    # --- cash flow ---
    (
        "ocf",
        "cash_flow_statement",
        "net_cash_flow_from_operating_activities",
        "netCashFlowFromOperations",
    ),
    (
        "icf",
        "cash_flow_statement",
        "net_cash_flow_from_investing_activities",
        "netCashFlowFromInvesting",
    ),
    (
        "financing_cf",
        "cash_flow_statement",
        "net_cash_flow_from_financing_activities",
        "netCashFlowFromFinancing",
    ),
    ("net_cash_flow", "cash_flow_statement", "net_cash_flow", "netCashFlow"),
]

# Fields the METHOD needs that `/vX` does not emit at all. `/v2` has them but is
# frozen at 2020-Q1, so for current data they must come from UW, SEC XBRL, or be
# derived — never silently dropped. Recorded here so the gap is a decision, not a
# discovery made later by a wrong number.
VX_MISSING_BUT_NEEDED = {
    "capital_expenditure": "capitalExpenditure",
    "free_cash_flow": "freeCashFlow",
    "total_debt": "debt",
    "current_debt": "debtCurrent",
    "cash_and_equivalents": "cashAndEquivalents",
    "depreciation_amortization": "depreciationAmortizationAndAccretion",
    "share_based_compensation": "shareBasedCompensation",
    "ebitda": "earningsBeforeInterestTaxesDepreciationAmortization",
    "deferred_revenue": "deferredRevenue",
    "interest_expense": "interestExpense",
}

# Relative tolerance for calling two values "agreeing". Not zero: the two
# endpoints derive from different vendor pipelines and round differently.
REL_TOL = 0.005


def _client(key: str) -> httpx.Client:
    return httpx.Client(
        base_url="https://api.massive.com",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60.0,
    )


def _leaf(row: dict, group: str, field: str) -> float | None:
    grp = (row.get("financials") or {}).get(group) or {}
    leaf = grp.get(field)
    if isinstance(leaf, dict) and leaf.get("value") is not None:
        try:
            return float(leaf["value"])
        except (TypeError, ValueError):
            return None
    return None


# ---------- 1. field inventory ----------


def inventory(client: httpx.Client, tickers: list[str]) -> dict[str, Any]:
    """Which `<group>.<field>` does each covered ticker actually emit?"""
    seen: dict[str, set[str]] = defaultdict(set)  # "group.field" -> {tickers}
    units: dict[str, str] = {}
    labels: dict[str, str] = {}
    probed: list[str] = []

    for t in tickers:
        resp = client.get(
            "/vX/reference/financials",
            params={"ticker": t, "timeframe": "quarterly", "limit": VX_INVENTORY_LIMIT},
        )
        if resp.status_code != 200:
            print(f"  {t}: HTTP {resp.status_code} — skipped", flush=True)
            continue
        probed.append(t)
        for row in resp.json().get("results") or []:
            for group, fields in (row.get("financials") or {}).items():
                for name, leaf in (fields or {}).items():
                    key = f"{group}.{name}"
                    seen[key].add(t)
                    if isinstance(leaf, dict):
                        units.setdefault(key, str(leaf.get("unit")))
                        labels.setdefault(key, str(leaf.get("label")))
        print(
            f"  {t}: {sum(len(f or {}) for f in (row.get('financials') or {}).values())} fields",
            flush=True,
        )

    n = len(probed)
    return {
        "tickers_probed": probed,
        "fields": {
            key: {
                "present_in": len(tks),
                "of": n,
                "coverage": round(len(tks) / n, 3) if n else None,
                "unit": units.get(key),
                "label": labels.get(key),
                "missing_for": sorted(set(probed) - tks),
            }
            for key, tks in sorted(seen.items())
        },
    }


# ---------- 2. overlap reconciliation ----------


def reconcile(client: httpx.Client, ticker: str) -> dict[str, Any]:
    """Compare `/vX` and `/v2` on their most recent COMMON period."""
    vx = client.get(
        "/vX/reference/financials",
        params={"ticker": ticker, "timeframe": "quarterly", "limit": VX_LIMIT},
    )
    v2 = client.get(
        f"/v2/reference/financials/{ticker}", params={"limit": 1000, "type": "Q"}
    )
    if vx.status_code != 200 or v2.status_code != 200:
        return {"error": f"vX={vx.status_code} v2={v2.status_code}"}

    vx_by_period = {r.get("end_date"): r for r in vx.json().get("results") or []}
    v2_by_period = {r.get("reportPeriod"): r for r in v2.json().get("results") or []}
    common = sorted(set(vx_by_period) & set(v2_by_period))
    if not common:
        return {
            "error": "no common period",
            "vx_periods": len(vx_by_period),
            "v2_periods": len(v2_by_period),
        }

    period = common[-1]  # most recent overlap — closest to the modern shape
    a, b = vx_by_period[period], v2_by_period[period]

    fields: dict[str, Any] = {}
    for canonical, group, vx_field, v2_key in FIELD_MAP:
        av = _leaf(a, group, vx_field)
        bv = b.get(v2_key)
        bv = float(bv) if isinstance(bv, (int, float)) else None
        entry: dict[str, Any] = {"vX": av, "v2": bv}
        if av is None or bv is None:
            entry["verdict"] = "missing_one_side"
        elif av == bv:
            entry["verdict"] = "exact"
        else:
            denom = max(abs(av), abs(bv))
            rel = abs(av - bv) / denom if denom else 0.0
            entry["rel_diff"] = round(rel, 6)
            entry["verdict"] = "within_tol" if rel <= REL_TOL else "DISAGREE"
        fields[canonical] = entry

    return {
        "period": period,
        "n_common_periods": len(common),
        "overlap_span": [common[0], common[-1]],
        "fields": fields,
        "summary": {
            v: sum(1 for f in fields.values() if f["verdict"] == v)
            for v in ("exact", "within_tol", "DISAGREE", "missing_one_side")
        },
    }


# ---------- 3. envelope variance ----------


def envelope_variance(client: httpx.Client, ticker: str) -> dict[str, Any]:
    """Two identical calls. Whatever differs cannot enter `content_hash`."""
    params = {"ticker": ticker, "timeframe": "quarterly", "limit": 2}
    a = client.get("/vX/reference/financials", params=params).json()
    b = client.get("/vX/reference/financials", params=params).json()

    top_differs = sorted(
        k for k in set(a) | set(b) if k != "results" and a.get(k) != b.get(k)
    )
    rows_a, rows_b = a.get("results") or [], b.get("results") or []
    row_differs: set[str] = set()
    for ra, rb in zip(rows_a, rows_b):
        row_differs |= {k for k in set(ra) | set(rb) if ra.get(k) != rb.get(k)}

    return {
        "envelope_keys_that_vary": top_differs,
        "row_keys_that_vary": sorted(row_differs),
        "results_identical": rows_a == rows_b,
        "exclusion_list": sorted(set(top_differs) | row_differs),
    }


# ---------- 4. ADR / FX evidence ----------


def adr_fx(client: httpx.Client, tickers: list[str]) -> dict[str, Any]:
    """`/v2` shareFactor + FX rate. The only measured ADR-ratio source we have."""
    out: dict[str, Any] = {}
    for t in tickers:
        resp = client.get(f"/v2/reference/financials/{t}", params={"limit": 1})
        if resp.status_code != 200:
            out[t] = {"http_status": resp.status_code}
            continue
        rows = resp.json().get("results") or []
        if not rows:
            out[t] = {"http_status": 200, "rows": 0}
            continue
        r = rows[0]
        out[t] = {
            "http_status": 200,
            "as_of": r.get("reportPeriod"),
            "share_factor": r.get("shareFactor"),
            "fx_rate": r.get("foreignCurrencyUSDExchangeRate"),
            "revenues_local": r.get("revenues"),
            "revenues_usd": r.get("revenuesUSD"),
        }
    return out


# ---------- 5. impossible values on CURRENT data ----------

# Quarters per ticker scanned for identity violations. 12 covers three years —
# enough to tell a one-off bad period from a standing defect.
IDENTITY_QUARTERS = 12

# Below this, a "diluted share count" for a company reporting revenue is not a
# share count. Every core-25 name has >100M shares outstanding; 1M is three
# orders of magnitude of headroom, so a hit here is a defect, not a small-cap.
MIN_PLAUSIBLE_SHARES = 1_000_000


def identity_violations(client: httpx.Client, tickers: list[str]) -> dict[str, Any]:
    """Does `/vX` emit values that cannot be true, on data we would ship today?

    The overlap probe (§2) found `liabilities` negative in a 2020 quarter. That
    is only interesting if it still happens, so this re-asks the question against
    the most recent quarters — the ones a card would actually render.
    """
    findings: dict[str, list] = {
        "negative_liabilities": [],
        "negative_assets": [],
        "implausible_share_count": [],
        "identity_break": [],  # liabilities + equity != liabilities_and_equity
    }
    rows_checked = 0
    for t in tickers:
        resp = client.get(
            "/vX/reference/financials",
            params={"ticker": t, "timeframe": "quarterly", "limit": IDENTITY_QUARTERS},
        )
        if resp.status_code != 200:
            continue
        for row in resp.json().get("results") or []:
            rows_checked += 1
            tag = f"{t}@{row.get('end_date')}"
            li = _leaf(row, "balance_sheet", "liabilities")
            assets = _leaf(row, "balance_sheet", "assets")
            eq = _leaf(row, "balance_sheet", "equity")
            lae = _leaf(row, "balance_sheet", "liabilities_and_equity")
            shares = _leaf(row, "income_statement", "diluted_average_shares")
            rev = _leaf(row, "income_statement", "revenues")

            if li is not None and li < 0:
                findings["negative_liabilities"].append([tag, li])
            if assets is not None and assets < 0:
                findings["negative_assets"].append([tag, assets])
            if rev and shares is not None and shares < MIN_PLAUSIBLE_SHARES:
                findings["implausible_share_count"].append([tag, shares])
            if (
                None not in (li, eq, lae)
                and lae
                and abs((li + eq) - lae) / abs(lae) > REL_TOL
            ):
                findings["identity_break"].append([tag, round((li + eq) - lae)])

    return {
        "rows_checked": rows_checked,
        "quarters_per_ticker": IDENTITY_QUARTERS,
        "findings": findings,
        "rates": {
            k: round(len(v) / rows_checked, 4) if rows_checked else None
            for k, v in findings.items()
        },
    }


def main() -> int:
    key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not key:
        print("MASSIVE_API_KEY is not set", file=sys.stderr)
        return 2
    if not COVERAGE.exists():
        print(
            f"run fundamental_source_coverage.py first: {COVERAGE} missing",
            file=sys.stderr,
        )
        return 2

    cov = json.loads(COVERAGE.read_text())["tickers"]
    covered = [t for t, r in cov.items() if r["state"] == "covered"]
    all_tickers = list(cov)

    with _client(key) as client:
        print(f"== 1. field inventory over {len(covered)} covered tickers")
        inv = inventory(client, covered)

        print(f"\n== 2. overlap reconciliation ({', '.join(OVERLAP_TICKERS)})")
        rec = {}
        for t in OVERLAP_TICKERS:
            rec[t] = reconcile(client, t)
            s = rec[t].get("summary") or rec[t].get("error")
            print(f"  {t}: {s}", flush=True)

        print("\n== 3. envelope variance (NVDA, two identical calls)")
        env = envelope_variance(client, "NVDA")
        print(
            f"  varies: {env['exclusion_list']}  results_identical={env['results_identical']}"
        )

        print(f"\n== 4. ADR / FX evidence over {len(all_tickers)} tickers")
        adr = adr_fx(client, all_tickers)
        for t, r in adr.items():
            if r.get("share_factor") not in (1, 1.0, None):
                print(f"  {t}: shareFactor={r['share_factor']} fx={r.get('fx_rate')}")

        print(f"\n== 5. impossible values on current data ({len(covered)} tickers)")
        idv = identity_violations(client, covered)
        for k, rate in idv["rates"].items():
            print(
                f"  {k}: {len(idv['findings'][k])}/{idv['rows_checked']} ({rate:.1%})"
            )

    payload = {
        "probed_at": "2026-08-11",
        "reproduce": (
            "MASSIVE_API_KEY=... uv run python "
            "scripts/research/fundamental_field_contract.py"
        ),
        "rel_tol": REL_TOL,
        "field_map": [
            {"canonical": c, "vx_group": g, "vx_field": f, "v2_key": v}
            for c, g, f, v in FIELD_MAP
        ],
        "vx_missing_but_needed": VX_MISSING_BUT_NEEDED,
        "inventory": inv,
        "overlap_reconciliation": rec,
        "envelope_variance": env,
        "adr_fx": adr,
        "identity_violations": idv,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "field_contract.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT_DIR / "field-contract.md").write_text(_render(payload))
    print(f"\nwrote {OUT_DIR}/field_contract.json and field-contract.md")
    return 0


def _render(p: dict[str, Any]) -> str:
    inv = p["inventory"]
    n = len(inv["tickers_probed"])
    lines = [
        "# `/vX` field contract — inventory, overlap, hash rule",
        "",
        f"*Probed {p['probed_at']} · REGENERATED on every run; narrative belongs in"
        " `fx-and-corporate-actions.md` · spec"
        " `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`*",
        "",
        "```bash",
        p["reproduce"],
        "```",
        "",
        "## 1. Field inventory",
        "",
        f"Every `financials.<group>.<field>` massive `/vX` emitted across the"
        f" {n} covered tickers (most recent {VX_INVENTORY_LIMIT} quarters each).",
        "",
        "| Field | Present | Coverage | Unit | Missing for |",
        "|---|---:|---:|---|---|",
    ]
    for key, f in inv["fields"].items():
        missing = ", ".join(f["missing_for"][:6]) or "—"
        if len(f["missing_for"]) > 6:
            missing += f" (+{len(f['missing_for']) - 6})"
        lines.append(
            f"| `{key}` | {f['present_in']}/{f['of']} | {f['coverage']} |"
            f" {f['unit']} | {missing} |"
        )

    lines += [
        "",
        "## 2. Overlap reconciliation (`/vX` ∩ `/v2`)",
        "",
        f"Most recent common period per ticker; `within_tol` is rel-diff ≤ {p['rel_tol']}.",
        "",
        "| Ticker | Period | Common periods | exact | within_tol | DISAGREE | missing one side |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for t, r in p["overlap_reconciliation"].items():
        if r.get("error"):
            lines.append(f"| {t} | — | — | — | — | — | {r['error']} |")
            continue
        s = r["summary"]
        lines.append(
            f"| {t} | {r['period']} | {r['n_common_periods']} | {s['exact']} |"
            f" {s['within_tol']} | **{s['DISAGREE']}** | {s['missing_one_side']} |"
        )

    disagreements = [
        (t, c, f)
        for t, r in p["overlap_reconciliation"].items()
        if not r.get("error")
        for c, f in r["fields"].items()
        if f["verdict"] == "DISAGREE"
    ]
    if disagreements:
        lines += [
            "",
            "### Disagreements",
            "",
            "| Ticker | Field | `/vX` | `/v2` | rel diff |",
            "|---|---|---:|---:|---:|",
        ]
        for t, c, f in disagreements:
            lines.append(
                f"| {t} | `{c}` | {f['vX']:,.0f} | {f['v2']:,.0f} | {f['rel_diff']:.4f} |"
            )

    env = p["envelope_variance"]
    lines += [
        "",
        "## 3. `content_hash` exclusion list",
        "",
        "Two identical `/vX` calls, diffed. These keys vary between calls and must be"
        " excluded from the hash, or every refresh reads as a restatement (spec §4.4).",
        "",
        "```",
        json.dumps(env["exclusion_list"], indent=2),
        "```",
        "",
        f"Result rows byte-identical across the two calls: **{env['results_identical']}**.",
        "",
        "## 4. Fields the method needs that `/vX` does not emit",
        "",
        "`/v2` has these but is frozen at 2020-Q1, so current values must come from"
        " UW, SEC XBRL, or derivation — never a silent `None`.",
        "",
        "| Canonical | `/v2` key |",
        "|---|---|",
    ]
    for c, v in p["vx_missing_but_needed"].items():
        lines.append(f"| `{c}` | `{v}` |")

    lines += [
        "",
        "## 5. ADR ratio / FX evidence (`/v2`)",
        "",
        "`shareFactor` ≠ 1 marks an ADR whose per-share figures need restating."
        " Values are as of the `/v2` freeze — a starting value to re-verify, not a"
        " live feed.",
        "",
        "| Ticker | As of | shareFactor | FX rate | revenues (local) | revenuesUSD |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for t, r in p["adr_fx"].items():
        if r.get("share_factor") is None and r.get("fx_rate") is None:
            continue
        if r.get("share_factor") in (1, 1.0) and r.get("fx_rate") in (1, 1.0):
            continue
        lines.append(
            f"| {t} | {r.get('as_of')} | {r.get('share_factor')} | {r.get('fx_rate')} |"
            f" {r.get('revenues_local')} | {r.get('revenues_usd')} |"
        )

    idv = p["identity_violations"]
    lines += [
        "",
        "## 6. Impossible values on CURRENT data",
        "",
        f"{idv['rows_checked']} rows — every covered ticker's most recent"
        f" {idv['quarters_per_ticker']} quarters. These are values that cannot be"
        " true of any company, in data a card would render today.",
        "",
        "| Check | Hits | Rate |",
        "|---|---:|---:|",
    ]
    for k, hits in idv["findings"].items():
        lines.append(
            f"| `{k}` | {len(hits)}/{idv['rows_checked']} | {idv['rates'][k]:.1%} |"
        )

    for k, hits in idv["findings"].items():
        if not hits:
            continue
        lines += ["", f"### `{k}` ({len(hits)})", "", "| Row | Value |", "|---|---:|"]
        for tag, val in hits:
            lines.append(f"| {tag} | {val:,.0f} |")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
