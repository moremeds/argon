# Fundamentals Card Flip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an eighth descriptive card to the Fundamentals tab and let every card flip to reveal the raw quarterly figures its ratio was computed from.

**Architecture:** A new pure-compute function beside `build_features` resolves each feature's own input components and its ratio, keyed off the existing `FEATURE_INPUTS` map. A new read-only endpoint serves those components; the client plots what it is given and performs no ratio math of its own. A hand-rolled SVG grouped-bar chart renders the back.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic v2 / psycopg 3 · Next.js 16 / React 19 / TypeScript · pytest + pytest-postgresql · Vitest + Playwright

Spec: `docs/superpowers/specs/2026-08-12-fundamentals-card-flip-design.md`

## Global Constraints

- **uv only.** `uv run pytest`, never bare `pytest`.
- **Hand-rolled SVG only.** Use `web/lib/svgChart.ts`. Do not add `recharts` / `d3` / `visx`, and do not extend `lightweight-charts` — it has exactly two documented exceptions and neither is a bar chart.
- **No new scored feature.** The composite stays a z-mean of the same seven features. The eighth card is descriptive and enters no score.
- **Three features carry `direction: null`** — `gross_margin`, `op_margin`, `roe`. No colour, arrow, or ordering may imply a good direction for them. Source of truth: `FEATURE_DIRECTION` in `src/uw_scan/fundamentals/features.py:62`.
- **The reconciliation invariant.** For every feature, the plotted `ratio` must equal its `role="input"` series combined by that feature's own formula, period for period.
- **Real frozen fixtures, never synthetic.** NVDA 2026-04-30: `total_revenue` 81615000000, `gross_profit` 61157000000, `operating_income` 53536000000, `net_income` 58321000000, `reported_currency` USD.
- **Never commit without an explicit user request** — the commit step in each task is drafted for the operator, who runs it when they choose.
- **CHANGELOG rides this PR** (Task 8), not a follow-up.
- **Branch from main only after PR #331 merges** — the Fundamentals tab does not exist on main until then.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/uw_scan/fundamentals/features.py` *(modify)* | add `FEATURE_CONTEXT`, `feature_basis()`, `build_feature_details` beside the existing `build_features` they must not drift from |
| `src/uw_scan/models/fundamentals.py` *(modify)* | add the three response models |
| `src/uw_scan/api/routers/stock.py` *(modify)* | add the `/fundamentals/statements` route |
| `web/lib/types.ts` *(regenerate)* | generated client types |
| `web/lib/api.ts` *(modify)* | add `fundamentalStatements` |
| `web/components/stock/panels/FundamentalBarChart.tsx` *(create)* | grouped bars + ratio line, role-aware, pure |
| `web/components/stock/panels/FundamentalCardBack.tsx` *(create)* | one feature's back: chart, basis, currency, close |
| `web/components/stock/tabs/FundamentalsTab.tsx` *(modify)* | flip state, expansion, the eighth card |

---

### Task 1: `build_feature_details` — the compute

**Files:**
- Modify: `src/uw_scan/fundamentals/features.py`
- Test: `tests/unit/fundamentals/test_feature_details.py` (create)

**Interfaces:**
- Consumes: existing `FEATURE_INPUTS`, `FEATURE_UNITS`, `_f`, `_ttm`, `build_features` in the same module.
- Produces: `build_feature_details(uw: dict, quarters: int = 20) -> dict[str, Any]` returning
  `{"period_ends": list[str], "reported_currency": str | None, "features": [{"feature": str, "basis": str, "series": [{"key": str, "label": str, "role": str, "unit": str, "values": list[float | None]}], "ratio": list[float | None]}]}`.
  Also `FEATURE_CONTEXT: dict[str, tuple[str, ...]]` and `feature_basis(feature: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/fundamentals/test_feature_details.py
"""`build_feature_details` must never disagree with `build_features`.

The two live in one module and share `_f`/`_ttm` for exactly this reason: the
back of a card states the figures a ratio came from, so a back whose bars do not
reconcile with its own line is worse than no back at all.
"""

from __future__ import annotations

import pytest

from uw_scan.fundamentals.features import (
    FEATURE_INPUTS,
    build_feature_details,
    build_features,
)

# NVDA's real last TEN fiscal quarters, frozen 2026-08-12 from
# uw_scan.fundamental_statement_obs — every figure as UW reports it.
#
# TEN, not five, and that is load-bearing: `rev_growth` compares a TTM window
# against the TTM window ending four quarters earlier, so it needs EIGHT before
# it can produce a single number. A five-quarter fixture makes the rev_growth
# reconciliation vacuous — every period null, the assertion passes by saying
# nothing.
#
# period, revenue, gross_profit, op_income, net_income, ebitda,
#         equity, assets, debt, cash, ocf, capex
_RAW = [
    ("2024-01-31", 22103, 16791, 13614, 12285, 14556, 42978, 65728, 11056, 7280, 11499, 254),
    ("2024-04-30", 26044, 20406, 16909, 14881, 17753, 49142, 77072, 10991, 7587, 15345, 369),
    ("2024-07-31", 30040, 22574, 18642, 16599, 19708, 58157, 85227, 10015, 8563, 14488, 977),
    ("2024-10-31", 35082, 26156, 21869, 19309, 22855, 65899, 96013, 10225, 9107, 17627, 813),
    ("2025-01-31", 39331, 28723, 24034, 22091, 25821, 79327, 111601, 10270, 8589, 16629, 1077),
    ("2025-04-30", 44062, 26668, 21638, 18775, 22584, 83843, 125254, 10285, 15234, 27414, 1227),
    ("2025-07-31", 46743, 33853, 28440, 26422, 31937, 100131, 140740, 10598, 11639, 15365, 1895),
    ("2025-10-31", 57006, 41849, 36010, 31910, 38748, 118897, 161148, 10822, 11486, 23751, 1636),
    ("2026-01-31", 68127, 51093, 44299, 42960, 51283, 157293, 206803, 11412, 10605, 36188, 1284),
    ("2026-04-30", 81615, 61157, 53536, 58321, 71002, 195474, 259474, 12814, 13237, 50344, 1757),
]
_M = 1_000_000  # figures above are in millions; UW serves whole units as strings

_INC = {
    r[0]: {"total_revenue": str(r[1] * _M), "gross_profit": str(r[2] * _M),
           "cost_of_revenue": str((r[1] - r[2]) * _M),
           "operating_income": str(r[3] * _M), "net_income": str(r[4] * _M),
           "ebitda": str(r[5] * _M), "reported_currency": "USD"}
    for r in _RAW
}
_BS = {
    r[0]: {"total_shareholder_equity": str(r[6] * _M), "total_assets": str(r[7] * _M),
           "short_long_term_debt_total": str(r[8] * _M),
           "cash_and_cash_equivalents": str(r[9] * _M), "reported_currency": "USD"}
    for r in _RAW
}
_CF = {
    r[0]: {"operating_cashflow": str(r[10] * _M),
           # UW reports capex as a POSITIVE outflow for NVDA. `build_features`
           # takes abs() precisely because the sign is not dependable.
           "capital_expenditures": str(r[11] * _M), "reported_currency": "USD"}
    for r in _RAW
}
PANEL = {"NVDA": {"income-statements": _INC, "balance-sheets": _BS,
                  "cash-flows": _CF, "filing_dates": {}, "obs_ids": {}}}


def _series(detail: dict, key: str) -> list[float | None]:
    for s in detail["series"]:
        if s["key"] == key:
            return s["values"]
    raise AssertionError(f"no series {key} in {[s['key'] for s in detail['series']]}")


def test_gross_margin_reconciles_bars_to_line():
    """The invariant, stated for the simplest feature: line == num/den, per period."""
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == "gross_margin")
    gp, rev = _series(detail, "gross_profit"), _series(detail, "total_revenue")
    for i, r in enumerate(detail["ratio"]):
        if r is None:
            continue
        assert r == pytest.approx(gp[i] / rev[i], rel=1e-12)
    # Not vacuous: the last period must actually be populated.
    assert detail["ratio"][-1] == pytest.approx(61157000000 / 81615000000, rel=1e-12)


# The invariant, written out per feature. Spec §5 requires this for EVERY
# feature, not just the easy one: each formula here is transcribed from
# `build_features`, so a typo in either surfaces as a failure rather than as a
# back side that quietly disagrees with its own front.
# Each lambda is transcribed from `build_features` VERBATIM, including where its
# own guards are inconsistent — `gross_margin` and `op_margin` and `roe` and
# `fcf_margin` test their numerator with `is not None`, while `rev_growth` and
# `asset_turnover` test theirs for truthiness, so a zero TTM revenue yields None
# there rather than a ratio.
#
# That inconsistency is NOT corrected here, and the reason matters: this oracle's
# job is to reproduce the implementation under test, not to improve it. An
# "idealised" oracle disagrees with correct output and fails on the first
# zero-revenue quarter — a real state for a pre-revenue biotech. If the guards
# should be unified, that is a change to `build_features` with its own test,
# because it would move published validation numbers.
RECONCILE = {
    "rev_growth": lambda s: [
        None if not a or not b else a / b - 1
        for a, b in zip(s["total_revenue_ttm"], s["rev_ttm_prev"], strict=True)
    ],
    "gross_margin": lambda s: [
        None if a is None or not b else a / b
        for a, b in zip(s["gross_profit"], s["total_revenue"], strict=True)
    ],
    "op_margin": lambda s: [
        None if a is None or not b else a / b
        for a, b in zip(s["operating_income"], s["total_revenue"], strict=True)
    ],
    "fcf_margin": lambda s: [
        None if None in (o, c) or not r else (o - abs(c)) / r
        for o, c, r in zip(
            s["operating_cashflow_ttm"], s["capital_expenditures_ttm"],
            s["total_revenue_ttm"], strict=True)
    ],
    "roe": lambda s: [
        None if n is None or not e or e <= 0 else n / e
        for n, e in zip(s["net_income_ttm"], s["total_shareholder_equity"],
                        strict=True)
    ],
    "neg_net_debt_ebitda": lambda s: [
        None if None in (d, c, e) or not e or e <= 0 else -((d - c) / e)
        for d, c, e in zip(
            s["short_long_term_debt_total"], s["cash_and_cash_equivalents"],
            s["ebitda_ttm"], strict=True)
    ],
    "asset_turnover": lambda s: [
        None if not r or not a else r / a
        for r, a in zip(s["total_revenue_ttm"], s["total_assets"], strict=True)
    ],
}


@pytest.mark.parametrize("feature", sorted(FEATURE_INPUTS))
def test_every_feature_reconciles_its_bars_to_its_line(feature):
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == feature)
    inputs = {
        s["key"]: s["values"] for s in detail["series"] if s["role"] == "input"
    }
    expected = RECONCILE[feature](inputs)
    assert len(expected) == len(detail["ratio"])
    for i, (got, want) in enumerate(zip(detail["ratio"], expected, strict=True)):
        if want is None:
            assert got is None, (feature, i)
        else:
            assert got == pytest.approx(want, rel=1e-12), (feature, i)
    # Not vacuous: at least one period must actually reconcile to a number.
    assert any(r is not None for r in detail["ratio"]), feature


def test_all_seven_features_are_present():
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    assert {f["feature"] for f in out["features"]} >= set(FEATURE_INPUTS)


def test_details_agree_with_build_features():
    """The anti-drift assertion. If someone edits one formula, this fails.

    Scoped to FEATURE_INPUTS on purpose: `build_features` holds the seven SCORED
    features and nothing else, so iterating every entry in the detail response
    would `KeyError` on the descriptive `revenue_earnings` card the moment Task 7
    lands.
    """
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    feats = build_features(PANEL)["NVDA"]
    for detail in out["features"]:
        if detail["feature"] not in FEATURE_INPUTS:
            continue
        for i, period in enumerate(out["period_ends"]):
            expected = feats[period][detail["feature"]]
            got = detail["ratio"][i]
            if expected is None:
                assert got is None, (detail["feature"], period)
            else:
                assert got == pytest.approx(expected, rel=1e-12), (
                    detail["feature"], period)


def test_ttm_features_are_none_before_four_quarters():
    """`_ttm` yields None until four quarters exist; the detail must not paper
    over that with a partial sum."""
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == "roe")
    assert detail["basis"] == "mixed"
    assert detail["ratio"][:3] == [None, None, None]
    assert detail["ratio"][-1] is not None


def test_currency_is_reported_not_assumed():
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    assert out["reported_currency"] == "USD"


def test_quarters_limit_takes_the_most_recent():
    out = build_feature_details(PANEL["NVDA"], quarters=2)
    assert out["period_ends"] == ["2026-01-31", "2026-04-30"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fundamentals/test_feature_details.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_feature_details'`

- [ ] **Step 3: Write the implementation**

Append to `src/uw_scan/fundamentals/features.py`, after `build_features`:

```python
# Fields worth showing that are NOT inputs to the ratio. They render dimmed and
# labelled `context`, and are excluded from the reconciliation invariant by
# construction — only role="input" series participate in it.
FEATURE_CONTEXT: dict[str, tuple[str, ...]] = {
    "gross_margin": ("cost_of_revenue",),
    "op_margin": ("research_and_development", "selling_general_and_administrative"),
}

_LABELS: dict[str, str] = {
    "total_revenue": "revenue",
    "gross_profit": "gross profit",
    "cost_of_revenue": "cost of revenue",
    "operating_income": "operating income",
    "research_and_development": "R&D",
    "selling_general_and_administrative": "SG&A",
    "operating_cashflow": "operating cash flow",
    "capital_expenditures": "capex",
    "net_income": "net income",
    "total_shareholder_equity": "shareholder equity",
    "short_long_term_debt_total": "total debt",
    "cash_and_cash_equivalents": "cash",
    "ebitda": "EBITDA",
    "total_assets": "total assets",
    "rev_ttm_prev": "revenue TTM, 4q earlier",
}

# Statement each raw field is read from, so a series resolves without guessing.
_SOURCE: dict[str, str] = {
    "total_revenue": "income", "gross_profit": "income", "cost_of_revenue": "income",
    "operating_income": "income", "research_and_development": "income",
    "selling_general_and_administrative": "income", "net_income": "income",
    "ebitda": "income",
    "operating_cashflow": "cash_flow", "capital_expenditures": "cash_flow",
    "total_shareholder_equity": "balance", "total_assets": "balance",
    "short_long_term_debt_total": "balance", "cash_and_cash_equivalents": "balance",
}

# Fields summed over four quarters rather than read per quarter. Mirrors the
# `_ttm(...)` calls in `build_features`; edit the two together.
_TTM_FIELDS: dict[str, frozenset[str]] = {
    "rev_growth": frozenset({"total_revenue"}),
    "gross_margin": frozenset(),
    "op_margin": frozenset(),
    "fcf_margin": frozenset(
        {"operating_cashflow", "capital_expenditures", "total_revenue"}
    ),
    "roe": frozenset({"net_income"}),
    "neg_net_debt_ebitda": frozenset({"ebitda"}),
    "asset_turnover": frozenset({"total_revenue"}),
}


def feature_basis(feature: str) -> str:
    """"ttm" | "quarterly" | "mixed", DERIVED rather than hand-listed.

    An earlier draft carried a `FEATURE_BASIS` dict alongside `_TTM_FIELDS`. Two
    hand-maintained maps describing one fact drift; this one cannot. Adding a
    field to `_TTM_FIELDS` now moves the label automatically, which is the
    behaviour you want when the arithmetic is what changed.
    """
    ttm = _TTM_FIELDS[feature]
    total = len(FEATURE_INPUTS[feature])
    if len(ttm) == total:
        return "ttm"
    if not ttm:
        return "quarterly"
    return "mixed"


def build_feature_details(
    uw: Mapping[str, Any], quarters: int = 20
) -> dict[str, Any]:
    """Per feature: the component series its ratio is computed from, plus the ratio.

    Serves the card's back side. Lives beside `build_features` and reuses `_f`
    and `_ttm` deliberately — the back states the figures behind the front's
    number, so the two must be one definition rather than two that agree today.

    `uw` is ONE ticker's entry from `FundamentalObsRepository.statement_panel`.
    """
    inc = uw["income-statements"]
    bs = uw["balance-sheets"]
    cf = uw["cash-flows"]
    by_source = {"income": inc, "balance": bs, "cash_flow": cf}

    all_periods = sorted(inc)
    keep = all_periods[-quarters:] if quarters > 0 else all_periods
    offset = len(all_periods) - len(keep)

    currency = None
    for p in reversed(all_periods):
        currency = _f_str(inc.get(p), "reported_currency")
        if currency:
            break

    def value(field: str, feature: str, i_all: int) -> float | None:
        src = by_source[_SOURCE[field]]
        if field in _TTM_FIELDS[feature]:
            return _ttm(src, all_periods, i_all, field)
        return _f(src.get(all_periods[i_all]), field)

    ratios = build_features({"_": uw})["_"]

    features: list[dict[str, Any]] = []
    for feature, fields in FEATURE_INPUTS.items():
        series: list[dict[str, Any]] = []
        for field in fields:
            # The SAME field is quarterly under one feature and a four-quarter
            # sum under another — `total_revenue` is per-quarter for
            # `gross_margin` and TTM for `asset_turnover`, figures differing by
            # ~4x. So the KEY carries the basis, not just the label: a series
            # keyed `total_revenue` holding a TTM sum is mislabelled data, and a
            # consumer joining on that key would be silently wrong.
            is_ttm = field in _TTM_FIELDS[feature]
            series.append(
                {
                    "key": f"{field}_ttm" if is_ttm else field,
                    "label": _LABELS.get(field, field) + (" TTM" if is_ttm else ""),
                    "role": "input",
                    "unit": "currency",
                    "values": [
                        value(field, feature, offset + i) for i in range(len(keep))
                    ],
                }
            )
        if feature == "rev_growth":
            # The denominator is the SAME field four quarters back, so it needs a
            # distinct key or it would collide with the numerator's series.
            series.append(
                {
                    "key": "rev_ttm_prev",
                    "label": _LABELS["rev_ttm_prev"],
                    "role": "input",
                    "unit": "currency",
                    "values": [
                        _ttm(inc, all_periods, offset + i - 4, "total_revenue")
                        if offset + i >= 7
                        else None
                        for i in range(len(keep))
                    ],
                }
            )
        for field in FEATURE_CONTEXT.get(feature, ()):
            series.append(
                {
                    "key": field,
                    "label": _LABELS.get(field, field),
                    "role": "context",
                    "unit": "currency",
                    "values": [
                        _f(by_source[_SOURCE[field]].get(all_periods[offset + i]), field)
                        for i in range(len(keep))
                    ],
                }
            )
        features.append(
            {
                "feature": feature,
                "basis": feature_basis(feature),
                "unit": FEATURE_UNITS[feature],
                "series": series,
                "ratio": [ratios[p][feature] for p in keep],
            }
        )

    return {
        "period_ends": list(keep),
        "reported_currency": currency,
        "features": features,
    }


def _f_str(row: dict | None, key: str) -> str | None:
    if not row:
        return None
    v = row.get(key)
    return str(v) if v not in (None, "") else None
```

Add `Mapping` to the module's `typing` import if absent.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/fundamentals/test_feature_details.py -v`
Expected: 13 passed (the reconciliation test is parametrized over all seven features).

Then confirm nothing regressed:
Run: `uv run pytest tests/unit/fundamentals/ -q`
Expected: all pass, including the existing `test_self_checks_run.py`.

- [ ] **Step 5: Commit** *(run only when the operator asks)*

```bash
git add src/uw_scan/fundamentals/features.py tests/unit/fundamentals/test_feature_details.py
git commit -m "feat(fundamentals): resolve each feature's own input components"
```

---

### Task 2: API models and endpoint

**Files:**
- Modify: `src/uw_scan/models/fundamentals.py`
- Modify: `src/uw_scan/models/__init__.py`
- Modify: `src/uw_scan/api/routers/stock.py`
- Test: `tests/integration/api/test_fundamental_statements_endpoint.py` (create)

**Interfaces:**
- Consumes: `build_feature_details` (Task 1); existing `FundamentalObsRepository.statement_panel(tickers=[t])`.
- Produces: `GET /api/stock/{ticker}/fundamentals/statements?quarters=20` → `FundamentalStatementsResponse`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/api/test_fundamental_statements_endpoint.py
"""The back-side endpoint, exercised against a real schema.

Asserts the two things a unit test on the compute cannot: that the route is
reachable under the same 404 contract as the card, and that a RESTATED period
resolves to the newest observation. The second matters because
`statement_panel` is now shared with the scoring path — if the two ever
disagreed on which row is current, the back would contradict the front.
"""

from __future__ import annotations

from datetime import date

from uw_scan.fundamentals.statements import content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository

PERIODS = ["2025-04-30", "2025-07-31", "2025-10-31", "2026-01-31", "2026-04-30"]

# NVDA's real figures, frozen 2026-08-12. Held flat across periods except
# revenue/gross profit, which carry the real quarterly values.
REV = dict(zip(PERIODS, ["44062000000", "46743000000", "57006000000",
                         "68127000000", "81615000000"], strict=True))
GP = dict(zip(PERIODS, ["26668000000", "33853000000", "41849000000",
                        "51093000000", "61157000000"], strict=True))


def _row(ticker: str, period: str, statement: str, payload: dict) -> dict:
    """Build one `record_statements` row the way the ingest job does.

    Goes through `normalize` + `content_hash` rather than a raw INSERT so the
    identity is computed by the same code the production path uses — a
    hand-written hash would let this test pass while real ingest diverged.
    """
    full = {"ticker": ticker, "fiscal_date_ending": period,
            "report_type": "quarterly", "reported_currency": "USD", **payload}
    norm = normalize(full)
    return {
        "source": "uw", "ticker": ticker, "period_end": date.fromisoformat(period),
        "period_type": "quarterly", "statement": statement,
        "content_hash": content_hash(norm), "raw_jsonb": norm,
        "field_map_version": "uw_v1", "provider_record_id": None,
        "filing_accession": None, "filing_published_at": None,
    }


def _seed(db, *, restate_last: bool = False) -> None:
    obs = FundamentalObsRepository(db.conn, schema=db._schema)
    rows = []
    for p in PERIODS:
        rows.append(_row("NVDA", p, "income", {
            "total_revenue": REV[p], "gross_profit": GP[p],
            "operating_income": "21638000000", "net_income": "18775000000",
            "ebitda": "22000000000"}))
        rows.append(_row("NVDA", p, "balance", {
            "total_shareholder_equity": "100000000000",
            "total_assets": "150000000000",
            "short_long_term_debt_total": "8500000000",
            "cash_and_cash_equivalents": "15000000000"}))
        rows.append(_row("NVDA", p, "cash_flow", {
            "operating_cashflow": "30000000000",
            "capital_expenditures": "-1200000000"}))
    if restate_last:
        # Same period, different reported figure -> different content hash ->
        # an ADDITIONAL immutable row, which is the shape a real restatement has.
        rows.append(_row("NVDA", PERIODS[-1], "income", {
            "total_revenue": REV[PERIODS[-1]], "gross_profit": "60000000000",
            "operating_income": "21638000000", "net_income": "18775000000",
            "ebitda": "22000000000"}))
    obs.record_statements(rows)  # commits internally


def test_ticker_with_no_statements_is_404(client):
    """404 means "no statements ingested" here, NOT "outside the tier-1
    universe" — that is the CARD endpoint's condition and the two can legitimately
    disagree. See design section 8."""
    r = client.get("/api/stock/ZZZZ/fundamentals/statements")
    assert r.status_code == 404


def test_returns_components_for_a_seeded_ticker(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    body = client.get("/api/stock/NVDA/fundamentals/statements?quarters=5").json()
    assert body["ticker"] == "NVDA"
    assert body["period_ends"] == PERIODS
    assert body["reported_currency"] == "USD"
    gm = next(f for f in body["features"] if f["feature"] == "gross_margin")
    gp = next(s for s in gm["series"] if s["key"] == "gross_profit")
    assert gp["values"][-1] == 61157000000.0


def test_restated_period_returns_the_newest_observation(client, seeded_db_empty_cards):
    """`statement_panel` resolves the highest obs_id. If the back ever used a
    different rule from the scoring path, it would chart a filing the headline
    value never saw."""
    _seed(seeded_db_empty_cards, restate_last=True)
    body = client.get("/api/stock/NVDA/fundamentals/statements?quarters=5").json()
    gm = next(f for f in body["features"] if f["feature"] == "gross_margin")
    gp = next(s for s in gm["series"] if s["key"] == "gross_profit")
    assert gp["values"][-1] == 60000000000.0  # restated, not 61157000000


def test_quarters_is_bounded(client):
    assert client.get(
        "/api/stock/NVDA/fundamentals/statements?quarters=0").status_code == 422
    assert client.get(
        "/api/stock/NVDA/fundamentals/statements?quarters=41").status_code == 422
```

The fixture is **`seeded_db_empty_cards`** (from `tests/integration/conftest.py`),
not `seeded` — `seeded` is only the local parameter name of the `_seed` helper in
`test_fundamentals_endpoint.py`, and taking it as a fixture fails at collection.
It is a `Repository` exposing `.conn` and `._schema`. `client` comes from
`tests/integration/api/conftest.py`. Do not add a conftest.

- [ ] **Step 2: Run test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=$(whoami) UW_SCAN_DB_NAME=option_wizard_test TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_fundamental_statements_endpoint.py -v`
Expected: FAIL — 404 on every route (the endpoint does not exist).

> The DB env overrides are required on a MacBook: without them the schema-owner check fails with `must be owner of schema uw_scan`.

- [ ] **Step 3: Add the models**

Append to `src/uw_scan/models/fundamentals.py`, before `_preserve_public_module`:

```python
class FundamentalComponentSeries(_UwBase):
    """One plotted series on a card's back.

    `role` separates the figures the ratio is COMPUTED FROM from those merely
    shown alongside it. Only `input` series participate in the reconciliation
    invariant, so a renderer must not blend the two into one visual class.
    """

    key: str
    label: str
    # "input" | "context"
    role: str
    # "currency" | "ratio" | "turns"
    unit: str
    values: list[float | None]


class FundamentalFeatureDetail(_UwBase):
    """One feature's components and the ratio they produce.

    `basis` is stated per feature because it is not uniform: `gross_margin` and
    `op_margin` are quarterly, the rest are TTM or mix a TTM flow with a
    point-in-time balance. An unlabelled shared axis would invite a comparison
    none of them support.
    """

    feature: str
    # "ttm" | "quarterly" | "mixed"
    basis: str
    unit: str
    series: list[FundamentalComponentSeries]
    # Oldest-first, aligned to `period_ends`. Null where an input was absent —
    # never 0, which is a figure rather than an absence.
    ratio: list[float | None]


class FundamentalStatementsResponse(_UwBase):
    """The back-side payload for one ticker.

    Components are resolved server-side and the client performs no ratio math.
    A client-side re-derivation would be a second copy of `build_features`, and
    the two would drift until the back silently contradicted the front.
    """

    ticker: str
    period_ends: list[str]
    # Per the filer. TSM files TWD against a USD ADR quote, so an unlabelled
    # axis is the same defect that produced a negative enterprise value here.
    reported_currency: str | None
    features: list[FundamentalFeatureDetail]
```

Add all three to the `_preserve_public_module(...)` call, then export them from `src/uw_scan/models/__init__.py` (both the import block and `__all__`).

- [ ] **Step 4: Add the route**

In `src/uw_scan/api/routers/stock.py`, after `get_stock_fundamentals`:

```python
@router.get(
    "/stock/{ticker}/fundamentals/statements",
    response_model=FundamentalStatementsResponse,
)
def get_stock_fundamental_statements(
    ticker: str,
    quarters: int = Query(20, ge=1, le=40),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> FundamentalStatementsResponse:
    """Per-feature input components behind the card's ratios.

    Served separately from the card rather than folded into it: the payload is
    only needed when a card is flipped, so first paint stays unchanged.

    Reads through `statement_panel`, the same path the scoring job uses, so
    "which observation is current" cannot diverge between the front of a card
    and its back.
    """
    from uw_scan.fundamentals.features import build_feature_details
    from uw_scan.storage.fundamental_obs import FundamentalObsRepository

    t = ticker.upper()
    obs = FundamentalObsRepository(repo.conn, schema=settings.db_schema)
    panel = obs.statement_panel([t])
    entry = panel.get(t)
    if not entry or not entry["income-statements"]:
        raise HTTPException(status_code=404, detail=f"no statements for {t}")

    detail = build_feature_details(entry, quarters=quarters)
    return FundamentalStatementsResponse(ticker=t, **detail)
```

Add `FundamentalStatementsResponse` to the router's existing `from uw_scan.models import (...)` block.

- [ ] **Step 5: Run tests to verify they pass**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=$(whoami) UW_SCAN_DB_NAME=option_wizard_test TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_fundamental_statements_endpoint.py -v`
Expected: 4 passed.

- [ ] **Step 6: Refresh the OpenAPI snapshot**

A new endpoint changes the committed snapshot. It lives at
`tests/integration/api/openapi.snapshot.json` and its guard is
`tests/integration/api/test_openapi_snapshot.py` — an **integration** test, so it
needs the DB env overrides:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=$(whoami) UW_SCAN_DB_NAME=option_wizard_test \
  TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```

Expected: FAIL on drift. Regenerate per that test's own documented instructions —
read the file first; a hand-edited snapshot is how the checked-in contract stops
matching the served one. Then re-run to green.

Also confirm the export surface the new models just joined:
Run: `uv run pytest tests/unit/test_models_exports.py -v`

- [ ] **Step 7: Commit** *(run only when the operator asks)*

```bash
git add src/uw_scan/models/ src/uw_scan/api/routers/stock.py tests/integration/api/
git commit -m "feat(api): serve per-feature statement components for the card back"
```

---

### Task 3: Client types and fetcher

**Files:**
- Regenerate: `web/lib/types.ts`
- Modify: `web/lib/api.ts`

**Interfaces:**
- Consumes: the Task 2 endpoint.
- Produces: `api.fundamentalStatements(ticker, quarters?)` → `FundamentalStatementsResponse`.

- [ ] **Step 1: Regenerate types**

With the API running on :8400:

Run: `cd web && npm run gen:types`
Expected: `lib/types.ts` gains `FundamentalStatementsResponse`, `FundamentalFeatureDetail`, `FundamentalComponentSeries`.

- [ ] **Step 2: Add the fetcher**

In `web/lib/api.ts`, beside the existing `fundamentals` entry at line 163:

```ts
  fundamentalStatements: (
    ticker: string,
    quarters = 20,
  ): Promise<components["schemas"]["FundamentalStatementsResponse"]> =>
    _fetch(`/api/stock/${ticker}/fundamentals/statements?quarters=${quarters}`),
```

- [ ] **Step 3: Verify**

Run: `cd web && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit** *(run only when the operator asks)*

```bash
git add web/lib/types.ts web/lib/api.ts
git commit -m "chore(web): regenerate types for the statements endpoint"
```

---

### Task 4: `FundamentalBarChart`

**Files:**
- Create: `web/components/stock/panels/FundamentalBarChart.tsx`
- Test: `web/tests/components/fundamentalBarChart.test.tsx` (create)

**Interfaces:**
- Consumes: `linearScale`, `finiteDomain`, `pathFromNullablePoints` from `@/lib/svgChart`.
- Produces: `FundamentalBarChart({ series, ratio, periods, ratioUnit, ratioStroke, width?, height? })`, where `series: {key, label, role, values}[]`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/components/fundamentalBarChart.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FundamentalBarChart } from "@/components/stock/panels/FundamentalBarChart";

// NVDA's real last five fiscal quarters, frozen 2026-08-12.
const PERIODS = ["2025-04-30", "2025-07-31", "2025-10-31", "2026-01-31", "2026-04-30"];
const REV = [44062000000, 46743000000, 57006000000, 68127000000, 81615000000];
const GP = [26668000000, 33853000000, 41849000000, 51093000000, 61157000000];

const props = {
  periods: PERIODS,
  series: [
    { key: "gross_profit", label: "gross profit", role: "input", values: GP },
    { key: "total_revenue", label: "revenue", role: "input", values: REV },
  ],
  ratio: GP.map((g, i) => g / REV[i]),
  ratioUnit: "ratio" as const,
};

describe("FundamentalBarChart", () => {
  it("draws one bar per period per series", () => {
    const { container } = render(<FundamentalBarChart {...props} />);
    expect(container.querySelectorAll("rect[data-series]")).toHaveLength(10);
  });

  it("marks context series distinctly from inputs", () => {
    // Load-bearing: a context field is NOT part of the ratio, so it must not
    // read as one of the figures the line was computed from.
    const { container } = render(
      <FundamentalBarChart
        {...props}
        series={[
          ...props.series,
          { key: "cost_of_revenue", label: "cost of revenue", role: "context",
            values: REV.map((r, i) => r - GP[i]) },
        ]}
      />,
    );
    const ctx = container.querySelectorAll('rect[data-role="context"]');
    expect(ctx).toHaveLength(5);
    expect(ctx[0].getAttribute("fill-opacity")).toBe("0.35");
  });

  it("draws a gap rather than interpolating a null period", () => {
    const withGap = { ...props, ratio: [0.6, null, 0.73, 0.75, 0.749] };
    const { container } = render(<FundamentalBarChart {...withGap} />);
    const d = container.querySelector("path[data-ratio]")?.getAttribute("d") ?? "";
    expect((d.match(/M/g) ?? []).length).toBeGreaterThan(1);
  });

  it("omits a bar for a null value instead of drawing zero", () => {
    const withNull = {
      ...props,
      series: [{ key: "gross_profit", label: "gross profit", role: "input",
                 values: [null, ...GP.slice(1)] }],
    };
    const { container } = render(<FundamentalBarChart {...withNull} />);
    expect(container.querySelectorAll("rect[data-series]")).toHaveLength(4);
  });

  it("is labelled for assistive tech", () => {
    const { container } = render(<FundamentalBarChart {...props} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("role")).toBe("img");
    expect(container.querySelector("title")?.textContent).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/components/fundamentalBarChart.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

```tsx
// web/components/stock/panels/FundamentalBarChart.tsx
import type { Point } from "@/lib/svgChart";
import { finiteDomain, linearScale, pathFromNullablePoints } from "@/lib/svgChart";

export type ComponentSeries = {
  key: string;
  label: string;
  role: string;
  values: (number | null)[];
};

const INPUT_FILLS = [
  "var(--accent-bg)",
  "var(--accent-warm)",
  "var(--accent-vol)",
];

/**
 * Grouped bars for a feature's components, with its ratio as a line.
 *
 * Hand-rolled SVG per the repo's charting rule — `lightweight-charts` has two
 * documented exceptions and a static bar series is not one of them.
 *
 * Three choices that carry meaning rather than style:
 *
 * - **Context series are visually subordinate.** A `context` field is shown
 *   because it is informative, not because the ratio uses it. Rendering it like
 *   an input would imply it reconciles with the line, and it does not.
 * - **A null is a gap, never a zero bar.** Zero is a figure; absence is not.
 * - **The ratio stroke is caller-supplied.** Three of the seven features have no
 *   validated direction, so this component must not choose a colour that implies
 *   one — see FEATURE_DIRECTION in fundamentals/features.py.
 */
export function FundamentalBarChart({
  series,
  ratio,
  periods,
  ratioUnit,
  ratioStroke = "var(--text-secondary)",
  width = 640,
  height = 220,
}: {
  series: ComponentSeries[];
  ratio: (number | null)[];
  periods: string[];
  ratioUnit: "ratio" | "turns";
  ratioStroke?: string;
  width?: number;
  height?: number;
}) {
  const PAD = { top: 12, right: 46, bottom: 22, left: 52 };
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;

  // `finiteDomain(values)` takes ONE argument and returns `{lo, hi, count}` or
  // **null** when fewer than two finite values exist — it has no fallback
  // parameters. Both null cases are real here: a brand-new ticker has one
  // quarter, and a fully-suppressed feature has an all-null ratio.
  const bars = finiteDomain(series.flatMap((s) => s.values));
  const rat = finiteDomain(ratio);
  // Fewer than two finite bar values is a real state — a newly-covered ticker
  // with one quarter, or a fully-suppressed feature. Say so; returning null
  // would leave a silent blank that reads as a layout bug.
  if (!bars) {
    return (
      <div style={{ fontSize: 11, color: "var(--text-muted)", padding: "12px 0" }}>
        Not enough reported history to chart these components.
      </div>
    );
  }

  // `linearScale(domain, range)` takes two TUPLES, not four scalars.
  // Range is [plotH, 0] so larger values sit higher on screen.
  const yBar = linearScale([Math.min(0, bars.lo), bars.hi], [plotH, 0]);
  const yRatio = rat ? linearScale([rat.lo, rat.hi], [plotH, 0]) : null;

  const slot = plotW / Math.max(periods.length, 1);
  const barW = Math.max(2, (slot * 0.7) / Math.max(series.length, 1));

  // `Point` is a TUPLE `[x, y]`, and `pathFromNullablePoints` takes
  // `ReadonlyArray<Point | null>` — a null entry breaks the line into a new
  // subpath, which is exactly the gap behaviour we want.
  const ratioPoints: (Point | null)[] =
    yRatio == null
      ? []
      : ratio.map((v, i) =>
          v == null
            ? null
            : ([PAD.left + slot * (i + 0.5), PAD.top + yRatio(v)] as Point),
        );

  const fmtAxis = (v: number) =>
    ratioUnit === "ratio" ? `${(v * 100).toFixed(0)}%` : `${v.toFixed(1)}x`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      style={{ maxWidth: "100%", height: "auto" }}
    >
      <title>
        {series.map((s) => s.label).join(", ")} over {periods.length} quarters
      </title>

      {series.map((s, si) =>
        s.values.map((v, i) =>
          v == null ? null : (
            <rect
              key={`${s.key}-${i}`}
              data-series={s.key}
              data-role={s.role}
              x={PAD.left + slot * i + slot * 0.15 + barW * si}
              y={PAD.top + yBar(Math.max(v, 0))}
              width={barW}
              height={Math.abs(yBar(v) - yBar(0))}
              fill={
                s.role === "context"
                  ? "var(--text-muted)"
                  : INPUT_FILLS[si % INPUT_FILLS.length]
              }
              fillOpacity={s.role === "context" ? 0.35 : 0.85}
            />
          ),
        ),
      )}

      <path
        data-ratio=""
        d={pathFromNullablePoints(ratioPoints)}
        fill="none"
        stroke={ratioStroke}
        strokeWidth={1.5}
      />

      {rat ? (
        <>
          <text
            x={width - PAD.right + 6}
            y={PAD.top + 4}
            fill="var(--text-muted)"
            fontSize={9}
          >
            {fmtAxis(rat.hi)}
          </text>
          <text
            x={width - PAD.right + 6}
            y={PAD.top + plotH}
            fill="var(--text-muted)"
            fontSize={9}
          >
            {fmtAxis(rat.lo)}
          </text>
        </>
      ) : null}

      <text x={2} y={PAD.top + 8} fill="var(--text-muted)" fontSize={9}>
        {(bars.hi / 1e9).toFixed(0)}B
      </text>
      <text x={2} y={PAD.top + plotH} fill="var(--text-muted)" fontSize={9}>
        0
      </text>

      <text x={PAD.left} y={height - 6} fill="var(--text-muted)" fontSize={9}>
        {periods[0]}
      </text>
      <text
        x={PAD.left + plotW}
        y={height - 6}
        textAnchor="end"
        fill="var(--text-muted)"
        fontSize={9}
      >
        {periods[periods.length - 1]}
      </text>
    </svg>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/components/fundamentalBarChart.test.tsx`
Expected: 5 passed. The three helper signatures used above were read from
`web/lib/svgChart.ts` on 2026-08-12 and are exact: `linearScale(domain, range)`
takes two tuples, `finiteDomain(values)` takes one argument and returns
`{lo, hi, count} | null`, and `Point` is the tuple `[number, number]`.

- [ ] **Step 5: Commit** *(run only when the operator asks)*

```bash
git add web/components/stock/panels/FundamentalBarChart.tsx web/tests/components/fundamentalBarChart.test.tsx
git commit -m "feat(web): grouped bar chart for fundamental components"
```

---

### Task 5: `FundamentalCardBack`

**Files:**
- Create: `web/components/stock/panels/FundamentalCardBack.tsx`
- Test: `web/tests/components/fundamentalCardBack.test.tsx` (create)

**Interfaces:**
- Consumes: `FundamentalBarChart` (Task 4); `FundamentalFeatureDetail` from `@/lib/types`.
- Produces: `FundamentalCardBack({ detail, periods, currency, label, onClose })`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/components/fundamentalCardBack.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FundamentalCardBack } from "@/components/stock/panels/FundamentalCardBack";

const PERIODS = ["2025-04-30", "2025-07-31", "2025-10-31", "2026-01-31", "2026-04-30"];
const REV = [44062000000, 46743000000, 57006000000, 68127000000, 81615000000];
const GP = [26668000000, 33853000000, 41849000000, 51093000000, 61157000000];

const detail = {
  feature: "gross_margin",
  basis: "quarterly",
  unit: "ratio",
  series: [
    { key: "gross_profit", label: "gross profit", role: "input", unit: "currency", values: GP },
    { key: "total_revenue", label: "revenue", role: "input", unit: "currency", values: REV },
  ],
  ratio: GP.map((g, i) => g / REV[i]),
};

const props = {
  detail,
  periods: PERIODS,
  currency: "USD",
  label: "Gross margin",
  onClose: () => {},
};

describe("FundamentalCardBack", () => {
  it("states the basis, because it is not uniform across features", () => {
    render(<FundamentalCardBack {...props} />);
    expect(screen.getByText(/quarterly/)).toBeTruthy();
  });

  it("states the reported currency", () => {
    // TSM files TWD against a USD quote; an unlabelled axis is how that becomes
    // a wrong number that looks right.
    render(<FundamentalCardBack {...props} />);
    expect(screen.getByText(/USD/)).toBeTruthy();
  });

  it("renders a TWD fixture as TWD", () => {
    render(<FundamentalCardBack {...props} currency="TWD" />);
    expect(screen.getByText(/TWD/)).toBeTruthy();
  });

  it("labels each series", () => {
    render(<FundamentalCardBack {...props} />);
    expect(screen.getByText("gross profit")).toBeTruthy();
    expect(screen.getByText("revenue")).toBeTruthy();
  });

  it("gives a no-direction feature a neutral ratio stroke", () => {
    // gross_margin measured INVERTED; the back must not undo the front's rule.
    const { container } = render(<FundamentalCardBack {...props} />);
    const stroke = container
      .querySelector("path[data-ratio]")
      ?.getAttribute("stroke");
    expect(stroke).toBe("var(--text-secondary)");
  });

  it("gives a directional feature its own stroke", () => {
    const { container } = render(
      <FundamentalCardBack
        {...props}
        detail={{ ...detail, feature: "fcf_margin" }}
        label="FCF margin"
      />,
    );
    expect(
      container.querySelector("path[data-ratio]")?.getAttribute("stroke"),
    ).toBe("var(--accent-bg)");
  });

  it("closes on the close control", async () => {
    const onClose = vi.fn();
    render(<FundamentalCardBack {...props} onClose={onClose} />);
    screen.getByRole("button", { name: /close/i }).click();
    expect(onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/components/fundamentalCardBack.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

```tsx
// web/components/stock/panels/FundamentalCardBack.tsx
import type { components } from "@/lib/types";
import { FundamentalBarChart } from "./FundamentalBarChart";

type Detail = components["schemas"]["FundamentalFeatureDetail"];

/**
 * Features with no validated direction. `gross_margin` and `op_margin` measured
 * INVERTED in the 2026-08-12 validation and `roe` is named by no rubric row, so
 * their ratio line gets a neutral stroke. The front already refuses to imply a
 * direction for these three; the back must not quietly reintroduce one.
 */
const NO_DIRECTION = new Set(["gross_margin", "op_margin", "roe"]);

const BASIS_NOTE: Record<string, string> = {
  ttm: "trailing twelve months",
  quarterly: "per quarter",
  // Deliberately direction-neutral. `roe` and `asset_turnover` put a TTM flow
  // OVER a point-in-time balance, while `neg_net_debt_ebitda` puts point-in-time
  // debt and cash over a TTM EBITDA — the other way round. One note has to be
  // true for all three, so it names the mix rather than an order.
  mixed: "mixes a four-quarter flow with a point-in-time balance",
};

export function FundamentalCardBack({
  detail,
  periods,
  currency,
  label,
  onClose,
}: {
  detail: Detail;
  periods: string[];
  currency: string | null;
  label: string;
  onClose: () => void;
}) {
  const inputs = detail.series.filter((s) => s.role === "input");
  const context = detail.series.filter((s) => s.role === "context");

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted)",
          }}
        >
          {label} · components
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          style={{
            background: "none",
            border: "1px solid var(--border-dim)",
            borderRadius: 3,
            color: "var(--text-muted)",
            cursor: "pointer",
            fontSize: 10,
            padding: "2px 8px",
          }}
        >
          close
        </button>
      </div>

      <div style={{ fontSize: 10, color: "var(--text-muted)", margin: "4px 0 8px" }}>
        {`${detail.basis} · ${BASIS_NOTE[detail.basis] ?? detail.basis} · figures in ${currency ?? "an unreported currency"}`}
      </div>

      <FundamentalBarChart
        series={detail.series}
        ratio={detail.ratio}
        periods={periods}
        ratioUnit={detail.unit === "turns" ? "turns" : "ratio"}
        ratioStroke={
          NO_DIRECTION.has(detail.feature)
            ? "var(--text-secondary)"
            : "var(--accent-bg)"
        }
      />

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          fontSize: 10,
          color: "var(--text-muted)",
          marginTop: 6,
        }}
      >
        {inputs.map((s) => (
          <span key={s.key}>{s.label}</span>
        ))}
        {context.map((s) => (
          <span key={s.key} style={{ opacity: 0.6 }}>
            {s.label} (context)
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/components/fundamentalCardBack.test.tsx`
Expected: 7 passed.

- [ ] **Step 5: Commit** *(run only when the operator asks)*

```bash
git add web/components/stock/panels/FundamentalCardBack.tsx web/tests/components/fundamentalCardBack.test.tsx
git commit -m "feat(web): card back showing a feature's own components"
```

---

### Task 6: Flip interaction and expansion

**Files:**
- Modify: `web/components/stock/tabs/FundamentalsTab.tsx`
- Test: `web/tests/components/fundamentalsTabFlip.test.tsx` (create)

**Interfaces:**
- Consumes: `FundamentalCardBack` (Task 5); `api.fundamentalStatements` (Task 3).
- Produces: flip state in `FundamentalsTab`; `SubscoreTile` gains `onOpen`, `open`, `detail`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/components/fundamentalsTabFlip.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const CARD = {
  ticker: "NVDA",
  composite: 0.42,
  composite_series: [],
  composite_percentile: null,
  series_dates: ["2026-04-30"],
  panel_size: 233,
  subscores: [
    { feature: "gross_margin", value: 0.7493, unit: "ratio", direction: null,
      suppressed_by: [], series: [0.7493], percentile: null },
  ],
  anchors: null,
  coverage: { features_present: 1, features_total: 7, missing: [], suppressed: [] },
  provenance: {
    engine_version: "e1", inputs_hash: "abc123", as_of: "2026-04-30",
    period_end: "2026-04-30", knowledge_date: "2026-06-14",
    filing_date_known: true, source_obs_count: 3,
  },
};

const STATEMENTS = {
  ticker: "NVDA",
  period_ends: ["2026-01-31", "2026-04-30"],
  reported_currency: "USD",
  features: [
    {
      feature: "gross_margin", basis: "quarterly", unit: "ratio",
      series: [
        { key: "gross_profit", label: "gross profit", role: "input",
          unit: "currency", values: [51093000000, 61157000000] },
        { key: "total_revenue", label: "revenue", role: "input",
          unit: "currency", values: [68127000000, 81615000000] },
      ],
      ratio: [0.75, 0.7493],
    },
  ],
};

vi.mock("@/lib/api", () => ({
  api: {
    fundamentals: vi.fn(() => Promise.resolve(CARD)),
    fundamentalStatements: vi.fn(() => Promise.resolve(STATEMENTS)),
  },
}));

import { api } from "@/lib/api";
import { FundamentalsTab } from "@/components/stock/tabs/FundamentalsTab";

describe("FundamentalsTab flip", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fetches statements once on mount, so the eighth card is never blank", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    await screen.findByTestId("subscore-gross_margin");
    await waitFor(() =>
      expect(api.fundamentalStatements).toHaveBeenCalledWith("NVDA"),
    );
    expect(api.fundamentalStatements).toHaveBeenCalledTimes(1);
  });

  it("opens the back on click", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
  });

  it("drops the open card and the previous ticker's data on a ticker change", async () => {
    // The stale-data bug: without a reset, the back keeps rendering NVDA's
    // components under AAPL's header.
    const { rerender } = render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
    rerender(<FundamentalsTab ticker="AAPL" />);
    await waitFor(() => expect(screen.queryByText(/components/i)).toBeNull());
    expect(api.fundamentalStatements).toHaveBeenLastCalledWith("AAPL");
  });

  it("opens on Enter and on Space", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-gross_margin");
    fireEvent.keyDown(tile, { key: "Enter" });
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
  });

  it("closes on Escape", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByText(/components/i)).toBeNull(),
    );
  });

  it("keeps the tile a real button for keyboard and assistive tech", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-gross_margin");
    expect(tile.tagName).toBe("BUTTON");
  });

  it("opens one card at a time", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    fireEvent.click(await screen.findByTestId("subscore-gross_margin"));
    await waitFor(() => expect(screen.getByText(/components/i)).toBeTruthy());
    expect(screen.getAllByText(/components/i)).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/components/fundamentalsTabFlip.test.tsx`
Expected: FAIL — the tile is a `div`, no back renders.

- [ ] **Step 3: Implement the flip**

In `FundamentalsTab.tsx`:

1. Add state beside the existing `card` / `error`:

```tsx
  const [openFeature, setOpenFeature] = useState<string | null>(null);
  const [statements, setStatements] = useState<
    components["schemas"]["FundamentalStatementsResponse"] | null
  >(null);
  const [statementsFailed, setStatementsFailed] = useState(false);
```

Then derive the value the render actually uses, rather than reading `statements`
directly:

```tsx
  // The effect below resets state, but effects run AFTER render — so the first
  // frame under a new ticker would still hold the previous ticker's payload.
  // The response carries its own ticker, so gate on that and the stale frame
  // becomes unrepresentable rather than merely short.
  const stmts = statements?.ticker === ticker ? statements : null;
```

2. Fetch statements on mount, keyed to the ticker, and close on Escape:

```tsx
  useEffect(() => {
    let live = true;
    // Reset BOTH on a ticker change. Without this, navigating NVDA -> AAPL
    // while a card is open leaves the previous ticker's components rendered
    // under the new ticker's header — a wrong chart that looks right.
    setOpenFeature(null);
    setStatements(null);
    setStatementsFailed(false);
    void (async () => {
      try {
        const s = await api.fundamentalStatements(ticker);
        if (live) setStatements(s);
      } catch {
        // A missing back is not a broken card: the front still states every
        // ratio. But it must render as UNAVAILABLE, not as loading — leaving
        // `statements` null with no failure flag spins "Loading components…"
        // forever, which claims progress that will never come.
        if (live) setStatementsFailed(true);
      }
    })();
    return () => {
      live = false;
    };
  }, [ticker]);

  useEffect(() => {
    if (openFeature == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenFeature(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [openFeature]);
```

> **Why eager, not lazy on first flip.** An earlier draft deferred this fetch
> until a card was opened. That is a real defect, not an optimisation: the eighth
> card's headline comes from this payload, so it would render an em dash until
> the user happened to flip some *other* card — the new card would be blank on
> arrival, which is the opposite of what it is for. The payload is a few hundred
> numbers for one ticker, so the deferral bought nothing and cost the feature its
> default state. Eager also deletes the lazy branch entirely.

3. Change `SubscoreTile`'s root from `<div>` to `<button type="button">`, add `onClick`, and reset the button's default styling:

```tsx
function SubscoreTile({
  s,
  dates,
  onOpen,
}: {
  s: Subscore;
  dates: string[];
  onOpen: () => void;
}) {
  const suppressed = s.suppressed_by.length > 0;
  const series = s.series ?? [];
  return (
    <button
      type="button"
      onClick={onOpen}
      style={{
        ...panelStyle,
        padding: 12,
        textAlign: "left",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
        width: "100%",
      }}
      data-testid={`subscore-${s.feature}`}
    >
```

Close it with `</button>`. A native button gives Enter and Space, focus, and the
right role for free — reimplementing them on a div is how those get missed.

4. In the grid, render the open card's back full-width:

```tsx
        {card.subscores.map((s) => {
          const detail = stmts?.features.find((f) => f.feature === s.feature);
          if (openFeature === s.feature) {
            return (
              <div
                key={s.feature}
                style={{ ...panelStyle, padding: 12, gridColumn: "1 / -1" }}
                data-testid={`subscore-back-${s.feature}`}
              >
                {detail && stmts ? (
                  <FundamentalCardBack
                    detail={detail}
                    periods={stmts.period_ends}
                    currency={stmts.reported_currency}
                    label={LABELS[s.feature] ?? s.feature}
                    onClose={() => setOpenFeature(null)}
                  />
                ) : (
                  <BackPlaceholder
                    failed={statementsFailed}
                    onClose={() => setOpenFeature(null)}
                  />
                )}
              </div>
            );
          }
          return (
            <SubscoreTile
              key={s.feature}
              s={s}
              dates={dates}
              onOpen={() => setOpenFeature(s.feature)}
            />
          );
        })}
```

5. Add the placeholder component to the same file, above `SubscoreTile`:

```tsx
/** The back before its data arrives — or after the fetch failed.
 *
 * These are different states and must read differently. A failed fetch left
 * showing "Loading…" claims progress that will never arrive, and the reader
 * waits instead of reloading. */
function BackPlaceholder({
  failed,
  onClose,
}: {
  failed: boolean;
  onClose: () => void;
}) {
  return (
    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
      {failed ? (
        <>
          <strong style={{ color: "var(--warning)" }}>
            Components unavailable.
          </strong>{" "}
          The statement history did not load. The ratio on the front of the card
          is unaffected.
        </>
      ) : (
        "Loading components…"
      )}
      <button
        type="button"
        onClick={onClose}
        aria-label="Close details"
        style={{
          background: "none",
          border: "1px solid var(--border-dim)",
          borderRadius: 3,
          color: "var(--text-muted)",
          cursor: "pointer",
          fontSize: 10,
          marginLeft: 8,
          padding: "2px 8px",
        }}
      >
        close
      </button>
    </div>
  );
}
```

6. Add the reduced-motion-safe transition to `web/app/globals.css`:

```css
/* The back replaces the front on flip. The rotation is decoration; the state
   change is not, so it must not depend on the animation running. */
@media (prefers-reduced-motion: no-preference) {
  [data-testid^="subscore-back-"] {
    animation: card-flip-in 180ms ease-out;
  }
}
@keyframes card-flip-in {
  from { transform: rotateY(-12deg); opacity: 0; }
  to { transform: none; opacity: 1; }
}
```

- [ ] **Step 4: Update the EXISTING FundamentalsTab test's mock**

`web/tests/components/fundamentalsTab.test.tsx` already exists and holds 15
tests. Its mock defines **only** `api.fundamentals`:

```ts
vi.mock("@/lib/api", () => ({
  api: {
    fundamentals: async () => {
      if (nextError) throw nextError;
      return nextCard;
    },
  },
}));
```

The mount fetch added in Step 2 calls `api.fundamentalStatements`, which that
mock does not define — so every one of those 15 tests would hit
`TypeError: api.fundamentalStatements is not a function`. The component's
`catch` swallows it, so **the suite would still pass while silently exercising
the failure path in all 15**. Add the second key:

```ts
vi.mock("@/lib/api", () => ({
  api: {
    fundamentals: async () => {
      if (nextError) throw nextError;
      return nextCard;
    },
    // Mount-time fetch for the card backs. Returns an empty payload: these
    // tests are about the FRONTS, and a null-ish statements payload is a state
    // the tab must render cleanly anyway.
    fundamentalStatements: async () => ({
      ticker: "CEG",
      period_ends: [],
      reported_currency: null,
      features: [],
    }),
  },
}));
```

> Keep both as plain `async` functions, not `vi.fn()`. That file's own comment
> records why: vitest's mock result-tracking attaches a handler to the returned
> promise with no rejection branch, so a `vi.fn()` that rejects is reported as an
> unhandled rejection even when the component catches it. The new test files in
> Tasks 6 and 7 may use `vi.fn()` **because theirs only ever resolve** — do not
> add a rejecting `vi.fn()` to any of them.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run tests/components/fundamentalsTabFlip.test.tsx`
Expected: 7 passed.

Then the whole suite, since `SubscoreTile` changed element type and the existing
tab test's mock changed:
Run: `cd web && npm run test`
Expected: all pass, including the 15 pre-existing `fundamentalsTab.test.tsx`
tests. If one asserted a `div`, update that assertion — the element genuinely
changed and `button` is the correct type.

- [ ] **Step 6: Commit** *(run only when the operator asks)*

```bash
git add web/components/stock/tabs/FundamentalsTab.tsx web/app/globals.css \
  web/tests/components/fundamentalsTabFlip.test.tsx \
  web/tests/components/fundamentalsTab.test.tsx
git commit -m "feat(web): flip a fundamental card to its components"
```

---

### Task 7: The eighth card — Revenue & earnings

**Files:**
- Modify: `src/uw_scan/fundamentals/features.py` (add the descriptive block)
- Modify: `src/uw_scan/models/fundamentals.py`
- Modify: `web/components/stock/tabs/FundamentalsTab.tsx`
- Test: `tests/unit/fundamentals/test_feature_details.py` (extend)
- Test: `web/tests/components/fundamentalsTabEighthCard.test.tsx` (create)

**Interfaces:**
- Consumes: `build_feature_details` (Task 1).
- Produces: a `revenue_earnings` entry in the response's `features` list, with `basis: "ttm"`, `unit: "currency"`, and an empty `ratio`.

- [ ] **Step 1: Write the failing Python test**

Append to `tests/unit/fundamentals/test_feature_details.py`:

```python
def test_revenue_earnings_is_descriptive_and_carries_no_ratio():
    """The eighth card enters no score, so it has no ratio to reconcile. It must
    still be a first-class entry rather than something the UI assembles by hand,
    or its TTM sums would be a second implementation of `_ttm`."""
    out = build_feature_details(PANEL["NVDA"], quarters=20)
    detail = next(f for f in out["features"] if f["feature"] == "revenue_earnings")
    assert detail["basis"] == "ttm"
    assert detail["unit"] == "currency"
    assert all(r is None for r in detail["ratio"])
    assert {s["key"] for s in detail["series"]} == {
        "total_revenue_ttm", "net_income_ttm", "fcf_ttm"}
    # Real NVDA TTM revenue over the five frozen quarters.
    rev = next(s for s in detail["series"] if s["key"] == "total_revenue_ttm")
    assert rev["values"][-1] == pytest.approx(
        46743000000 + 57006000000 + 68127000000 + 81615000000
    )
    assert rev["values"][0] is None  # fewer than four quarters available


def test_revenue_earnings_is_not_in_feature_inputs():
    """It must never join the scored set: the composite's measured verdicts cover
    exactly the seven in FEATURE_INPUTS."""
    assert "revenue_earnings" not in FEATURE_INPUTS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fundamentals/test_feature_details.py -v`
Expected: FAIL — `StopIteration` on the `revenue_earnings` lookup.

- [ ] **Step 3: Add the descriptive block**

In `build_feature_details`, after the `for feature, fields in FEATURE_INPUTS.items()` loop and before the `return`:

```python
    # The eighth card. Descriptive: it enters no composite and has no ratio, so
    # `ratio` is all-None rather than absent — one shape for every entry keeps
    # the client from special-casing it.
    def _ttm_series(src: dict, field: str) -> list[float | None]:
        return [_ttm(src, all_periods, offset + i, field) for i in range(len(keep))]

    ocf = _ttm_series(cf, "operating_cashflow")
    capex = _ttm_series(cf, "capital_expenditures")
    features.append(
        {
            "feature": "revenue_earnings",
            "basis": "ttm",
            "unit": "currency",
            "series": [
                {"key": "total_revenue_ttm", "label": "revenue TTM", "role": "input",
                 "unit": "currency", "values": _ttm_series(inc, "total_revenue")},
                {"key": "net_income_ttm", "label": "net income TTM", "role": "input",
                 "unit": "currency", "values": _ttm_series(inc, "net_income")},
                {"key": "fcf_ttm", "label": "free cash flow TTM", "role": "input",
                 "unit": "currency",
                 "values": [
                     None if o is None or c is None else o - abs(c)
                     for o, c in zip(ocf, capex, strict=True)
                 ]},
            ],
            "ratio": [None] * len(keep),
        }
    )
```

- [ ] **Step 4: Run the Python tests**

Run: `uv run pytest tests/unit/fundamentals/test_feature_details.py -v`
Expected: 15 passed.

- [ ] **Step 5: Write the failing web test**

```tsx
// web/tests/components/fundamentalsTabEighthCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const CARD = {
  ticker: "NVDA", composite: 0.42, composite_series: [],
  composite_percentile: null, series_dates: ["2026-04-30"], panel_size: 233,
  subscores: [
    { feature: "gross_margin", value: 0.7493, unit: "ratio", direction: null,
      suppressed_by: [], series: [0.7493],
      percentile: { percentile: 0.9, n: 233 } },
  ],
  anchors: null,
  coverage: { features_present: 1, features_total: 7, missing: [], suppressed: [] },
  provenance: {
    engine_version: "e1", inputs_hash: "abc123", as_of: "2026-04-30",
    period_end: "2026-04-30", knowledge_date: "2026-06-14",
    filing_date_known: true, source_obs_count: 3,
  },
};

const STATEMENTS = {
  ticker: "NVDA",
  period_ends: ["2026-01-31", "2026-04-30"],
  reported_currency: "USD",
  features: [
    {
      feature: "revenue_earnings", basis: "ttm", unit: "currency",
      series: [
        { key: "total_revenue_ttm", label: "revenue TTM", role: "input", unit: "currency",
          values: [220000000000, 253491000000] },
        { key: "net_income_ttm", label: "net income TTM", role: "input", unit: "currency",
          values: [130000000000, 159613000000] },
        { key: "fcf_ttm", label: "free cash flow TTM", role: "input",
          unit: "currency", values: [110000000000, 115200000000] },
      ],
      ratio: [null, null],
    },
  ],
};

vi.mock("@/lib/api", () => ({
  api: {
    fundamentals: vi.fn(() => Promise.resolve(CARD)),
    fundamentalStatements: vi.fn(() => Promise.resolve(STATEMENTS)),
  },
}));

import { FundamentalsTab } from "@/components/stock/tabs/FundamentalsTab";

describe("the eighth card", () => {
  it("renders alongside the subscores", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    expect(await screen.findByTestId("subscore-revenue_earnings")).toBeTruthy();
  });

  it("says it is not scored, and shows no percentile", async () => {
    // The seven around it are members of a validated set. A tile that looked
    // identical would be read as an eighth measured feature, which the
    // composite's verdicts do not cover.
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-revenue_earnings");
    expect(tile.textContent).toMatch(/not scored/i);
    expect(tile.textContent).not.toMatch(/of 233/);
  });

  it("shows all three TTM figures, not just revenue", async () => {
    // Design §2 names revenue, net income and free cash flow. Revenue alone
    // makes the card a decoration rather than the summary it is meant to be.
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-revenue_earnings");
    expect(tile.textContent).toMatch(/\$253\.5B/); // revenue TTM
    expect(tile.textContent).toMatch(/net income \$159\.6B/);
    expect(tile.textContent).toMatch(/FCF \$115\.2B/);
  });

  it("draws the mini series", async () => {
    render(<FundamentalsTab ticker="NVDA" />);
    const tile = await screen.findByTestId("subscore-revenue_earnings");
    expect(tile.querySelector("svg")).toBeTruthy();
  });
});
```

- [ ] **Step 6: Render the eighth card**

In `FundamentalsTab.tsx`, after the `card.subscores.map(...)` block inside the grid:

```tsx
        {(() => {
          const re = stmts?.features.find(
            (f) => f.feature === "revenue_earnings",
          );
          if (openFeature === "revenue_earnings") {
            return (
              <div
                style={{ ...panelStyle, padding: 12, gridColumn: "1 / -1" }}
                data-testid="subscore-back-revenue_earnings"
              >
                {re && stmts ? (
                  <FundamentalCardBack
                    detail={re}
                    periods={stmts.period_ends}
                    currency={stmts.reported_currency}
                    label="Revenue & earnings"
                    onClose={() => setOpenFeature(null)}
                  />
                ) : (
                  <BackPlaceholder
                    failed={statementsFailed}
                    onClose={() => setOpenFeature(null)}
                  />
                )}
              </div>
            );
          }
          // By KEY, never by position — series order is the compute's business,
          // and a positional index silently charts net income as revenue the
          // day that order changes.
          const pick = (k: string) =>
            re?.series.find((s) => s.key === k)?.values ?? [];
          const rev = pick("total_revenue_ttm");
          const ni = pick("net_income_ttm");
          const fcf = pick("fcf_ttm");
          return (
            <button
              type="button"
              onClick={() => setOpenFeature("revenue_earnings")}
              style={{
                ...panelStyle, padding: 12, textAlign: "left", cursor: "pointer",
                font: "inherit", color: "inherit", width: "100%",
              }}
              data-testid="subscore-revenue_earnings"
            >
              <span style={labelStyle}>Revenue &amp; earnings</span>
              <div
                style={{
                  fontSize: 22, fontWeight: 700, margin: "6px 0",
                  color: "var(--text-primary)",
                }}
              >
                {fmtCompactUsd(rev.at(-1))}
              </div>
              {/* The mini series. Reuses FundamentalSparkline so the eighth
                  card's chart cannot drift from the seven beside it. */}
              {rev.filter((v) => v != null).length >= 2 ? (
                <FundamentalSparkline
                  values={rev}
                  dates={stmts?.period_ends ?? []}
                  label="Revenue TTM"
                  stroke="var(--text-secondary)"
                />
              ) : null}
              <div
                style={{
                  display: "flex", gap: 12, fontSize: 10,
                  color: "var(--text-muted)", marginTop: 6,
                }}
              >
                <span>net income {fmtCompactUsd(ni.at(-1))}</span>
                <span>FCF {fmtCompactUsd(fcf.at(-1))}</span>
              </div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
                descriptive · not scored
              </div>
            </button>
          );
        })()}
```

Add the formatter to the same file, above `SubscoreTile`:

```tsx
/** 253491000000 -> "$253.5B". Nulls render as an em dash, never as $0. */
function fmtCompactUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toFixed(0)}`;
}
```

The headline reads `—` only while the mount fetch is in flight, or if it failed.
Task 6 fetches on mount precisely so this card is populated on arrival; an em
dash as its resting state would make the eighth card decorative.

- [ ] **Step 7: Run the web tests**

Run: `cd web && npx vitest run tests/components/fundamentalsTabEighthCard.test.tsx`
Expected: 4 passed.

Run: `cd web && npm run test && npm run typecheck && npm run lint`
Expected: all pass.

- [ ] **Step 8: Commit** *(run only when the operator asks)*

```bash
git add src/uw_scan/fundamentals/features.py tests/unit/fundamentals/test_feature_details.py web/components/stock/tabs/FundamentalsTab.tsx web/tests/components/fundamentalsTabEighthCard.test.tsx
git commit -m "feat: add the descriptive revenue & earnings card"
```

---

### Task 8: End-to-end proof, CHANGELOG, and full verification

**Files:**
- Create: `web/tests/e2e/fundamentals-card-flip.spec.ts`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no new API surface.

- [ ] **Step 1: Write the e2e spec**

```ts
// web/tests/e2e/fundamentals-card-flip.spec.ts
import { expect, test } from "@playwright/test";

// The tab is a path segment, not a query param.
const URL = "/stock/NVDA/fundamentals";

test("a fundamental card flips to its own components", async ({ page }) => {
  await page.goto(URL);
  const tile = page.getByTestId("subscore-gross_margin");
  await expect(tile).toBeVisible();

  await tile.click();

  const back = page.getByTestId("subscore-back-gross_margin");
  await expect(back).toBeVisible();
  // The bars are the point: assert the chart drew, not merely that text changed.
  await expect(back.locator("rect[data-series]").first()).toBeVisible();
  await expect(back.getByText(/quarterly/)).toBeVisible();
  await expect(back.getByText(/USD/)).toBeVisible();
  await expect(tile).toBeHidden();

  await back.getByRole("button", { name: /close/i }).click();
  await expect(page.getByTestId("subscore-gross_margin")).toBeVisible();
});

test("the eighth card renders and is marked not scored", async ({ page }) => {
  await page.goto(URL);
  const eighth = page.getByTestId("subscore-revenue_earnings");
  await expect(eighth).toBeVisible();
  await expect(eighth).toContainText(/not scored/i);
});
```

- [ ] **Step 2: Run the e2e spec**

With the stack up (`bash scripts/dev.sh`):

Run: `cd web && npx playwright test tests/e2e/fundamentals-card-flip.spec.ts`
Expected: 2 passed. Screenshots on failure land under `output/playwright/`.

- [ ] **Step 3: Add the CHANGELOG entry**

Under `## [Unreleased]` → `### Added` in `CHANGELOG.md`:

```markdown
- **Fundamental cards flip to the figures behind them.** Clicking any card on the
  Fundamentals tab expands it to a 20-quarter chart of the components its ratio
  was computed from — `gross_profit` against `total_revenue` for gross margin,
  operating cash flow against capex for FCF margin, and so on — served by a new
  `GET /stock/{ticker}/fundamentals/statements`. The components are resolved
  server-side in `build_feature_details`, beside `build_features` and sharing its
  helpers, so the back cannot drift from the front; a test asserts the plotted
  line equals the plotted input bars for every feature. Each back states its own
  **basis** (`gross_margin` and `op_margin` are quarterly where the rest are TTM,
  and three ratios divide a TTM flow by a point-in-time balance) and its
  **reported currency**, since TSM files TWD against a USD quote. The three
  features with no validated direction keep a neutral line — the front's rule
  holds on the back.
- **An eighth, descriptive card: revenue & earnings.** TTM revenue, net income and
  free cash flow. It enters no composite and carries no percentile, and says
  `descriptive · not scored` where a subscore tile states its direction — the
  seven around it are a validated set and a tile that looked identical would be
  read as an eighth measured feature.
```

- [ ] **Step 4: Full verification**

```bash
uv run pytest -q
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=$(whoami) UW_SCAN_DB_NAME=option_wizard_test \
  TEST_DB_NAME=option_wizard_test uv run pytest tests/integration -q
uv run ruff check . && uv run ruff format --check .
cd web && npm run typecheck && npm run lint && npm run test
```

Expected: all green. The `lint + unit` CI job runs more than ruff and pytest — reproduce the full job locally before pushing.

- [ ] **Step 5: Commit** *(run only when the operator asks)*

```bash
git add web/tests/e2e/fundamentals-card-flip.spec.ts CHANGELOG.md
git commit -m "test(web): e2e proof of the card flip, plus changelog"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §2 eighth card | 7 |
| §3 flip, keyboard, reduced motion, expansion | 6 |
| §4 20 quarters, no derived annuals | 1 (`quarters` slice), 2 (`le=40` bound) |
| §5 reconciliation invariant | 1 (test), 4 (role rendering) |
| §5.1 basis stated per feature | 1 (`feature_basis()`), 5 (rendered) |
| §5.2 context series | 1 (`FEATURE_CONTEXT`), 4 (dimmed), 5 (legend) |
| §6 endpoint, computed components | 2 |
| §6.1 restatements via `statement_panel` | 2 (integration test) |
| §6.2 currency rendered | 5 (two tests) |
| §7 hand-rolled SVG | 4 |
| §8 tests | 1, 2, 4, 5, 6, 7, 8 |
| §9 branch strategy | plan preamble; merge #331 first |

No gaps.

**Placeholder scan:** none. Every code step carries runnable code; every test step carries real assertions against frozen NVDA figures.

**Verified against the real repo on 2026-08-12** (not assumed):

| Claim | Evidence |
|---|---|
| `linearScale(domain, range)` takes two tuples | `web/lib/svgChart.ts:6` |
| `finiteDomain(values)` returns `{lo,hi,count} \| null`, one arg, no fallbacks | `web/lib/svgChart.ts:156` |
| `Point` is `[number, number]` | `web/lib/svgChart.ts:4` |
| `statement_panel` resolves restatements by `obs_id DESC` | `storage/fundamental_obs.py:284-291` |
| `record_statements` row keys | `storage/fundamental_obs.py:92-103` |
| `FEATURE_INPUTS` matches §5.1's component map | `fundamentals/features.py:41-53` |
| Integration fixture is `seeded_db_empty_cards`, not `seeded` | `tests/integration/conftest.py:181`; `seeded` is only `_seed`'s local parameter name |
| OpenAPI snapshot path | `tests/integration/api/openapi.snapshot.json` |
| `fundamentalsTab.test.tsx` exists with 15 tests and mocks only `fundamentals` | that file, lines 10-17 |
| Fixture figures are NVDA's real 10 quarters | queried from `uw_scan.fundamental_statement_obs` |

**Type consistency:** `build_feature_details` returns the dict consumed unchanged by `FundamentalStatementsResponse(ticker=t, **detail)` — keys `period_ends`, `reported_currency`, `features` match the model's fields exactly. `ComponentSeries` in Task 4 matches the `role`/`values` shape the Task 2 model emits. `openFeature` / `setOpenFeature` / `statements` are named identically in Tasks 6 and 7.

**Module size:** `FundamentalsTab.tsx` grows by roughly 180 lines across Tasks 6-7
(flip state, `BackPlaceholder`, the eighth card, `fmtCompactUsd`). Measure it
after Task 7 with `wc -l`. It should land near 450 and the repo budget is 500 —
if it exceeds 500, stop and extract `SubscoreTile` + the eighth card into
`panels/` before continuing, per the standing module-size rule.

**Tribunal findings folded in (2026-08-12):** the five-quarter fixture could not
produce `rev_growth` at all (needs eight); the reconciliation oracle treated a
zero numerator as missing; TTM series were keyed by raw field name; Task 7 would
have broken Task 1's anti-drift test with a `KeyError`; the ticker reset left one
stale frame; a failed fetch spun "Loading" forever; and the eighth card rendered
only one of its three required figures.
