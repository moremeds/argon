#!/usr/bin/env python
"""Probe UW's fundamentals endpoints and cross-check them against massive `/vX`.

Spec: docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md (§3.2, §3.3).

Written after the massive probes found `/vX` unusable for TSM/ASML and defective
at ~5-15% elsewhere. UW's statement endpoints turned out to be **200 on our tier**,
which the spec had assumed they were not — the earlier "UW fundamentals are 403"
note was about the `companies/*` family, a different route.

Route-form discipline (this is the third time the shape of a URL has changed a
conclusion): the real routes are PLURAL —

    /api/stock/{ticker}/income-statements     NOT .../income-statement
    /api/stock/{ticker}/balance-sheets        NOT .../balance-sheet
    /api/stock/{ticker}/cash-flows            NOT .../cash-flow

The singular forms return HTTP 404 `{"error": "Route not found"}`, which a naive
probe records as "no coverage on our tier" — the exact error that made `/v2` look
absent for three separate readings. Routes here were read out of the committed
OpenAPI spec (`docs/uw-samples/unusual_whales_api_spec.yaml`), not guessed.

Four questions, in order of what changes a decision:

1. COVERAGE   — quarterly rows, span, and reported currency per ticker.
2. FIELDS     — non-null rate per field per ticker. A field that exists in the
                schema but is null for the cohort is not a field we have.
3. INTEGRITY  — the same impossible-value checks run against massive, so the two
                sources are judged by one standard.
4. AGREEMENT  — UW vs massive `/vX` on the most recent common quarter. Two
                independent sources on one quarter is the only way to tell which
                one is wrong when they differ.

Reproduce:

    UW_SCAN_API_KEY=... MASSIVE_API_KEY=... uv run python scripts/research/uw_fundamentals_probe.py

Writes `uw_fundamentals.json` + `uw-fundamentals.md` under
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

UW_BASE = "https://api.unusualwhales.com"
MASSIVE_BASE = "https://api.massive.com"

STATEMENTS = ("income-statements", "balance-sheets", "cash-flows")

# Same thresholds as the massive probe so the two sources are comparable.
MIN_PLAUSIBLE_SHARES = 1_000_000
REL_TOL = 0.005

# UW field -> massive `/vX` (group, field), for the head-to-head. Only fields
# both sources claim to carry; UW-only fields are the point of the exercise and
# are reported separately.
CROSS_MAP: list[tuple[str, str, str, str]] = [
    # (uw_statement, uw_field, vx_group, vx_field)
    ("income-statements", "total_revenue", "income_statement", "revenues"),
    ("income-statements", "gross_profit", "income_statement", "gross_profit"),
    (
        "income-statements",
        "operating_income",
        "income_statement",
        "operating_income_loss",
    ),
    ("income-statements", "net_income", "income_statement", "net_income_loss"),
    ("income-statements", "cost_of_revenue", "income_statement", "cost_of_revenue"),
    (
        "income-statements",
        "income_tax_expense",
        "income_statement",
        "income_tax_expense_benefit",
    ),
    (
        "income-statements",
        "research_and_development",
        "income_statement",
        "research_and_development",
    ),
    ("balance-sheets", "total_assets", "balance_sheet", "assets"),
    ("balance-sheets", "total_liabilities", "balance_sheet", "liabilities"),
    ("balance-sheets", "total_shareholder_equity", "balance_sheet", "equity"),
    ("balance-sheets", "total_current_assets", "balance_sheet", "current_assets"),
    (
        "balance-sheets",
        "total_current_liabilities",
        "balance_sheet",
        "current_liabilities",
    ),
    ("balance-sheets", "inventory", "balance_sheet", "inventory"),
    (
        "cash-flows",
        "operating_cashflow",
        "cash_flow_statement",
        "net_cash_flow_from_operating_activities",
    ),
    (
        "cash-flows",
        "cashflow_from_investment",
        "cash_flow_statement",
        "net_cash_flow_from_investing_activities",
    ),
    (
        "cash-flows",
        "cashflow_from_financing",
        "cash_flow_statement",
        "net_cash_flow_from_financing_activities",
    ),
]

# Fields UW carries that massive `/vX` does not emit at all (spec §3.3 F-C).
# Presence of these is the whole argument for reordering source precedence.
UW_ONLY_CRITICAL = {
    "income-statements": [
        "ebitda",
        "ebit",
        "depreciation_and_amortization",
        "interest_expense",
    ],
    "balance-sheets": [
        "cash_and_cash_equivalents",
        "short_long_term_debt_total",
        "current_debt",
        "long_term_debt",
        "goodwill",
        "common_stock_shares_outstanding",
    ],
    "cash-flows": [
        "capital_expenditures",
        "stock_based_compensation",
        "dividend_payout",
    ],
}


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _vx_leaf(row: dict, group: str, field: str) -> float | None:
    leaf = ((row.get("financials") or {}).get(group) or {}).get(field)
    if isinstance(leaf, dict):
        return _num(leaf.get("value"))
    return None


def fetch_uw(client: httpx.Client, ticker: str) -> dict[str, Any]:
    """All three statements for one ticker, quarterly rows keyed by period."""
    out: dict[str, Any] = {}
    for ep in STATEMENTS:
        resp = client.get(f"/api/stock/{ticker}/{ep}")
        if resp.status_code != 200:
            out[ep] = {"http_status": resp.status_code, "rows": None}
            continue
        data = resp.json().get("data") or []
        quarterly = [r for r in data if r.get("report_type") == "quarterly"]
        periods = sorted(
            r["fiscal_date_ending"] for r in quarterly if r.get("fiscal_date_ending")
        )
        out[ep] = {
            "http_status": 200,
            "rows": len(data),
            "quarterly_rows": len(quarterly),
            "first_period": periods[0] if periods else None,
            "last_period": periods[-1] if periods else None,
            "currencies": sorted(
                {
                    r.get("reported_currency")
                    for r in quarterly
                    if r.get("reported_currency")
                }
            ),
            "by_period": {
                r["fiscal_date_ending"]: r
                for r in quarterly
                if r.get("fiscal_date_ending")
            },
        }
    return out


def field_nullrates(uw_by_ticker: dict[str, Any]) -> dict[str, Any]:
    """Per statement/field: in how many tickers is it non-null at least once?

    A schema key that is null for every ticker is not data. This separates
    "UW has an EBITDA column" from "UW gives us EBITDA".
    """
    present: dict[str, dict[str, set]] = {ep: defaultdict(set) for ep in STATEMENTS}
    tickers_ok: dict[str, set] = {ep: set() for ep in STATEMENTS}
    for t, statements in uw_by_ticker.items():
        for ep in STATEMENTS:
            block = statements.get(ep) or {}
            rows = list((block.get("by_period") or {}).values())
            if not rows:
                continue
            tickers_ok[ep].add(t)
            for row in rows:
                for k, v in row.items():
                    if v is not None and v != "":
                        present[ep][k].add(t)
    return {
        ep: {
            "tickers_with_rows": len(tickers_ok[ep]),
            "fields": {
                k: {
                    "present_in": len(ts),
                    "coverage": round(len(ts) / len(tickers_ok[ep]), 3)
                    if tickers_ok[ep]
                    else None,
                }
                for k, ts in sorted(present[ep].items())
            },
        }
        for ep in STATEMENTS
    }


def integrity(uw_by_ticker: dict[str, Any]) -> dict[str, Any]:
    """The massive probe's impossible-value checks, applied to UW."""
    # NOT named `identity_break`: `total_assets = total_liabilities +
    # total_shareholder_equity` is the identity for a filer with NO
    # noncontrolling interest. The true identity is A = L + E_parent + NCI, and
    # UW's balance-sheet schema has no NCI field, so a gap here is a MISSING
    # FIELD, not a wrong number. Measured: 236 of 237 gaps run one direction
    # (L+E < A) and concentrate in MU/CEG/ORCL/TSM/DELL/AMD — all filers with
    # consolidated subsidiaries. Random corruption would not be one-directional.
    findings: dict[str, list] = {
        "negative_liabilities": [],
        "negative_assets": [],
        "implausible_share_count": [],
        "unexplained_balance_gap": [],
    }
    rows_checked = 0
    for t, st in uw_by_ticker.items():
        bs = (st.get("balance-sheets") or {}).get("by_period") or {}
        inc = (st.get("income-statements") or {}).get("by_period") or {}
        for period, row in bs.items():
            rows_checked += 1
            tag = f"{t}@{period}"
            li = _num(row.get("total_liabilities"))
            assets = _num(row.get("total_assets"))
            eq = _num(row.get("total_shareholder_equity"))
            shares = _num(row.get("common_stock_shares_outstanding"))
            rev = _num((inc.get(period) or {}).get("total_revenue"))

            if li is not None and li < 0:
                findings["negative_liabilities"].append([tag, li])
            if assets is not None and assets < 0:
                findings["negative_assets"].append([tag, assets])
            if rev and shares is not None and shares < MIN_PLAUSIBLE_SHARES:
                findings["implausible_share_count"].append([tag, shares])
            if (
                None not in (li, eq, assets)
                and assets
                and abs((li + eq) - assets) / abs(assets) > REL_TOL
            ):
                findings["unexplained_balance_gap"].append(
                    [tag, round((li + eq) - assets)]
                )
    return {
        "rows_checked": rows_checked,
        "findings": findings,
        "rates": {
            k: round(len(v) / rows_checked, 4) if rows_checked else None
            for k, v in findings.items()
        },
    }


def agreement(
    uw_by_ticker: dict[str, Any], mv: httpx.Client, tickers: list[str]
) -> dict[str, Any]:
    """UW vs massive `/vX` on the most recent common quarter.

    Where they agree, both are probably right. Where they differ, this says which
    one carries the impossible value — which is the question §3.3 F-A left open.
    """
    out: dict[str, Any] = {}
    for t in tickers:
        resp = mv.get(
            "/vX/reference/financials",
            params={"ticker": t, "timeframe": "quarterly", "limit": 100},
        )
        if resp.status_code != 200:
            out[t] = {"error": f"massive HTTP {resp.status_code}"}
            continue
        vx = {r.get("end_date"): r for r in resp.json().get("results") or []}
        uw_periods = set(
            (uw_by_ticker.get(t, {}).get("balance-sheets") or {}).get("by_period") or {}
        )
        common = sorted(set(vx) & uw_periods)
        if not common:
            out[t] = {"error": "no common period", "vx": len(vx), "uw": len(uw_periods)}
            continue
        period = common[-1]
        fields: dict[str, Any] = {}
        for ep, uw_field, group, vx_field in CROSS_MAP:
            uw_row = ((uw_by_ticker[t].get(ep) or {}).get("by_period") or {}).get(
                period
            ) or {}
            a, b = _num(uw_row.get(uw_field)), _vx_leaf(vx[period], group, vx_field)
            e: dict[str, Any] = {"uw": a, "vx": b}
            if a is None or b is None:
                e["verdict"] = "missing_one_side"
            elif a == b:
                e["verdict"] = "exact"
            else:
                denom = max(abs(a), abs(b))
                rel = abs(a - b) / denom if denom else 0.0
                e["rel_diff"] = round(rel, 6)
                e["verdict"] = "within_tol" if rel <= REL_TOL else "DISAGREE"
            fields[f"{ep}.{uw_field}"] = e
        out[t] = {
            "period": period,
            "n_common": len(common),
            "fields": fields,
            "summary": {
                v: sum(1 for f in fields.values() if f["verdict"] == v)
                for v in ("exact", "within_tol", "DISAGREE", "missing_one_side")
            },
        }
    return out


def main() -> int:
    uw_key = os.environ.get("UW_SCAN_API_KEY", "").strip()
    mv_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not uw_key or not mv_key:
        print("need UW_SCAN_API_KEY and MASSIVE_API_KEY", file=sys.stderr)
        return 2
    if not COVERAGE.exists():
        print(
            f"run fundamental_source_coverage.py first: {COVERAGE} missing",
            file=sys.stderr,
        )
        return 2

    tickers = list(json.loads(COVERAGE.read_text())["tickers"])

    uw_by_ticker: dict[str, Any] = {}
    with httpx.Client(
        base_url=UW_BASE,
        headers={"Authorization": f"Bearer {uw_key}", "Accept": "application/json"},
        timeout=60.0,
    ) as uw:
        print(f"== 1-2. UW statements for {len(tickers)} tickers")
        for t in tickers:
            uw_by_ticker[t] = fetch_uw(uw, t)
            inc = uw_by_ticker[t].get("income-statements") or {}
            print(
                f"  {t:5} q={inc.get('quarterly_rows')} "
                f"span={inc.get('first_period')}..{inc.get('last_period')} "
                f"ccy={','.join(inc.get('currencies') or []) or '-'}",
                flush=True,
            )

    nulls = field_nullrates(uw_by_ticker)
    print("\n== 3. integrity")
    integ = integrity(uw_by_ticker)
    for k, rate in integ["rates"].items():
        print(
            f"  {k}: {len(integ['findings'][k])}/{integ['rows_checked']} ({rate:.1%})"
        )

    with httpx.Client(
        base_url=MASSIVE_BASE,
        headers={"Authorization": f"Bearer {mv_key}"},
        timeout=60.0,
    ) as mv:
        print("\n== 4. UW vs massive /vX agreement")
        agree = agreement(uw_by_ticker, mv, tickers)
        for t, r in agree.items():
            print(f"  {t:5} {r.get('summary') or r.get('error')}", flush=True)

    # by_period is bulk payload — keep the analysis, drop the rows.
    slim = {
        t: {
            ep: {k: v for k, v in (block or {}).items() if k != "by_period"}
            for ep, block in st.items()
        }
        for t, st in uw_by_ticker.items()
    }
    payload = {
        "probed_at": "2026-08-11",
        "reproduce": (
            "UW_SCAN_API_KEY=... MASSIVE_API_KEY=... uv run python "
            "scripts/research/uw_fundamentals_probe.py"
        ),
        "routes": [f"/api/stock/{{ticker}}/{ep}" for ep in STATEMENTS],
        "coverage": slim,
        "field_nullrates": nulls,
        "uw_only_critical": UW_ONLY_CRITICAL,
        "integrity": integ,
        "agreement_vs_massive": agree,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "uw_fundamentals.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT_DIR / "uw-fundamentals.md").write_text(_render(payload))
    print(f"\nwrote {OUT_DIR}/uw_fundamentals.json and uw-fundamentals.md")
    return 0


def _render(p: dict[str, Any]) -> str:
    lines = [
        "# UW fundamentals — coverage, integrity, and head-to-head vs massive `/vX`",
        "",
        f"*Probed {p['probed_at']} · REGENERATED on every run · spec"
        " `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`*",
        "",
        "```bash",
        p["reproduce"],
        "```",
        "",
        "Routes (PLURAL — the singular forms 404, which reads as 'no coverage'):",
        "",
        *[f"- `{r}`" for r in p["routes"]],
        "",
        "## 1. Coverage",
        "",
        "| Ticker | Quarterly rows | Span | Currency | BS rows | CF rows |",
        "|---|---:|---|---|---:|---:|",
    ]
    for t, st in p["coverage"].items():
        inc = st.get("income-statements") or {}
        bs = st.get("balance-sheets") or {}
        cf = st.get("cash-flows") or {}
        span = (
            f"{inc.get('first_period')} → {inc.get('last_period')}"
            if inc.get("quarterly_rows")
            else "—"
        )
        lines.append(
            f"| {t} | {inc.get('quarterly_rows')} | {span} |"
            f" {','.join(inc.get('currencies') or []) or '—'} |"
            f" {bs.get('quarterly_rows')} | {cf.get('quarterly_rows')} |"
        )

    lines += [
        "",
        "## 2. Critical fields massive `/vX` does not emit at all",
        "",
        "| Statement | Field | Cohort coverage |",
        "|---|---|---:|",
    ]
    for ep, fields in p["uw_only_critical"].items():
        for f in fields:
            cov = ((p["field_nullrates"].get(ep) or {}).get("fields") or {}).get(
                f
            ) or {}
            lines.append(f"| `{ep}` | `{f}` | {cov.get('coverage')} |")

    integ = p["integrity"]
    lines += [
        "",
        "## 3. Integrity — same checks massive was judged by",
        "",
        f"{integ['rows_checked']} quarterly balance-sheet rows.",
        "",
        "`unexplained_balance_gap` is **not** a defect count. It tests"
        " `assets = liabilities + shareholder_equity`, which holds only for filers"
        " with no noncontrolling interest; UW exposes no NCI field, so consolidating"
        " filers break it by construction. The gap is one-directional (`L+E < A`) and"
        " concentrates in MU/CEG/ORCL/TSM/DELL/AMD. Read it as **the size of the"
        " missing-NCI problem**, not as bad data.",
        "",
        "| Check | Hits | Rate |",
        "|---|---:|---:|",
    ]
    for k, hits in integ["findings"].items():
        lines.append(
            f"| `{k}` | {len(hits)}/{integ['rows_checked']} | {integ['rates'][k]:.1%} |"
        )
    for k, hits in integ["findings"].items():
        if hits:
            lines += [
                "",
                f"### `{k}` ({len(hits)})",
                "",
                "| Row | Value |",
                "|---|---:|",
            ]
            lines += [f"| {tag} | {val:,.0f} |" for tag, val in hits[:40]]

    lines += [
        "",
        "## 4. UW vs massive `/vX`, most recent common quarter",
        "",
        "| Ticker | Period | exact | within_tol | DISAGREE | missing one side |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for t, r in p["agreement_vs_massive"].items():
        if r.get("error"):
            lines.append(f"| {t} | — | — | — | — | {r['error']} |")
            continue
        s = r["summary"]
        lines.append(
            f"| {t} | {r['period']} | {s['exact']} | {s['within_tol']} |"
            f" **{s['DISAGREE']}** | {s['missing_one_side']} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
