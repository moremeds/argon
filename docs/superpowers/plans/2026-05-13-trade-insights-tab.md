# Trade Insights Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `Trade Insights` stock-detail tab that turns existing UW volatility, flow, and option-chain data into deterministic research-grade trade ideas, with an optional Codex commentary path left for a follow-up.

**Architecture:** Backend adds normalized trade-insight models, an OCC/OSI option-symbol parser, a deterministic assembler, persistence for deterministic research snapshots/candidate rows, and a `GET /api/stock/{ticker}/trade-insights` endpoint. Frontend adds a new tab route, API helper, and focused panels for source reconciliation, source/data quality, signal stack, chain/flow read, term structure, candidate structures, and synthesis. V1 does not run Codex; it makes the deterministic JSON stable and logged first, with optional AI-analysis work planned as V1.5.

**Naming contract:** use `Trade Insights` for the visible tab label and `/trade-insights` for browser/API routes. Internal filenames should use `trade_insights.py`. Do not expose `Trade Ideas` or `Trading Insights` in navigation, URLs, API paths, or user-facing copy.

**Tech Stack:** Python 3.13 + FastAPI + Pydantic + psycopg-backed repository; Next.js 16 + React 19 + TypeScript; pytest integration/unit tests; vitest component tests.

**Specs:**
- `docs/superpowers/specs/2026-05-13-trade-insights-tab-design.md`
- `docs/superpowers/research/2026-05-13-vol-neutral-mean-reversion-strategy-research.md`

---

## Lessons from shipped tabs (2026-05 Playwright audit)

These constraints come from auditing the live `/stock/SPY/{market-structure, volatility, flow, trade-plan}` pages against the most recent shipped implementations (Volatility v2, Flow+Tables merge, Market Structure). Every rule here exists to keep `Trade Insights` visually and behaviorally consistent with what landed in commits `30da5a7`, `833e186`, and `e996b5e`.

1. **The layout already supplies the ticker header.** `web/app/stock/[ticker]/layout.tsx` calls `api.stock(ticker)` once and renders `<DetailHeader>` (ticker, spot, IV, setup badge) plus `<TabBar>` above every tab's `{children}`. The tab body must NOT re-render the ticker or spot. The Trade Insights "header" panel only owns the bias/setup/confidence/data-quality row plus badges. Rename the **React component** `TradeInsightsHeader` → `TradeInsightsBiasBanner` and drop the `ticker` prop. (See revised Task 4.1.)
   > Note: the **Python Pydantic model** `TradeInsightsHeader` in `models.py` keeps its name — it's the API response shape (`response.header: TradeInsightsHeader`), not the UI component. The rename is React-only.

2. **Section heading style is `fontSize: 9, letterSpacing: 1`**, uppercased mono, `color: var(--text-muted)` — not `fontSize: 10` as earlier drafts of this plan said. Verified against `VolatilityTabClient.tsx` lines 79–88. Match this exactly so the new tab doesn't look one font-step heavier than its neighbors.

3. **Two-column grid is the established density pattern.** Volatility v2 uses `gridTemplateColumns: "1fr 1fr"` for chart pairs (`IvOfIvChart | RvSpyCorrChart`, `RegimeQuadrantChart | DivergenceOverlay`). Market Structure pairs `ExpectedRangeBar | DirectionalBiasPanel`. Trade Insights must not be a single-column stack — that wastes ~50% of the viewport. Suggested pairings:
   - `SourceReconciliationPanel | SignalStackPanel`
   - `ChainFlowReadPanel | TermMovePanel`
   - `CandidateStructuresPanel` (full-width — multi-card grid)
   - `InsightsSynthesisPanel` (full-width)

4. **Extract a shared `InsightPanel.tsx` shell first.** Volatility v2 lifted `AnalyticalSeriesPanel.tsx` to avoid duplicating panel chrome across nine panel files. Trade Insights builds seven panels in V1 — extract the shell up front (see new Task 4.0). Each panel then just accepts `{ heading, subheading?, children }` instead of duplicating the border/background/padding block seven times.

5. **Degraded-state dashed banner.** Volatility v2 renders a dashed-border `"Building 1-year history… (≤30s)"` notice when `backfill_status === "running"`. Trade Insights doesn't poll, but adopt the same dashed-banner shape for "No iv_term_snapshots for this run" and "No option chain rows" so empty states match the visual vocabulary of the rest of the app.

6. **Loading and error boundaries are missing in the stock route.** `web/app/stock/[ticker]/{loading,error}.tsx` do not exist today; the existing tabs survive because the parent layout awaits `api.stock(ticker)` before paint and the tab bodies are server-rendered fast enough. Trade Insights adds a second sequential `await api.tradeInsights(ticker)` which makes a freeze visible. Add minimal `loading.tsx` and `error.tsx` siblings in Phase 3. (See new Task 3.3.)

7. **Filter selectors are an established Flow pattern** (`EXPIRIES: [4 selected ▾]`, `STRIKE RANGE: [±30% ▾]` from `FlowTab.tsx`). V1 of Trade Insights does NOT implement these — every strike row renders. Listed under "Known V1 limitations" with the V1.1 patch hook so the gap is visible.

## Visual consistency requirements

`Trade Insights` must look like a native stock-detail tab, not a new app surface.

Follow these existing patterns:

| Existing file | Reuse / match |
|---|---|
| `web/components/stock/tabs/VolatilityTabClient.tsx` (lines 79–88) | Section heading style: uppercase mono, **9px**, `var(--text-muted)`, 1px letter spacing, `marginTop: 4`. This is the current pattern — newer than `TradePlanTab.tsx`'s 10px style. |
| `web/components/stock/panels/MetricGrid.tsx` | Metric density and small label/value hierarchy. |
| `web/components/stock/panels/DataTable.tsx` | Table styling for flow and term-structure rows. |
| `web/components/stock/panels/AnalyticalSeriesPanel.tsx` | Panel shell visual language: `var(--bg-panel)`, `var(--border-dim)`, compact padding. |
| `web/app/globals.css` | Existing color tokens only; do not introduce a separate palette. |
| `web/components/stock/TabBar.tsx` | Existing tab typography, active border, and spacing. |

Rules:

- Use `var(--bg-panel)`, `var(--border-dim)`, `var(--text-primary)`, `var(--text-secondary)`, `var(--text-muted)`, `var(--accent-bg)`, `var(--warning)`, `var(--positive)`, and `var(--negative)`.
- Do not use new gradients, decorative backgrounds, oversized hero elements, or marketing-style cards.
- Do not nest cards inside cards.
- Keep cards at the same compact radius and border style as existing panels.
- Use `DataTable` for tabular data unless a specific card layout is clearer.
- Use the same `sectionHeading` object from `TradePlanTab.tsx` or extract a shared equivalent if duplication becomes annoying.
- Candidate structure cards should be compact operational cards, not large narrative tiles.
- Empty states should match the current small mono style used by existing tabs.
- The `Run AI Analysis` follow-up button, when implemented later, should be a secondary utility control and not visually dominate the deterministic panels.

## File structure

### New backend files

| Path | Responsibility |
|---|---|
| `src/uw_scan/storage/migrations/016_trade_insights.sql` | Persist idempotent Trade Insights snapshots and queryable candidate rows for later validation/backtests. |
| `src/uw_scan/reports/trade_insights.py` | Deterministic assembler for `TradeInsightsResponse`: parse contracts, build source reconciliation, signal stack, flow rows, term rows, candidate structures, synthesis, and quality badges. |
| `src/uw_scan/api/routers/trade_insights.py` | FastAPI router for `GET /api/stock/{ticker}/trade-insights`. |
| `tests/test_trade_insights.py` | Unit tests for option-symbol parsing, candidate math, data-quality flags, source reconciliation, and synthesis status rules. |
| `tests/integration/api/test_trade_insights_endpoint.py` | API shape and empty-state integration tests. |
| `web/components/stock/tabs/TradeInsightsTab.tsx` | Main server/client tab component that fetches and composes Trade Insights panels. |
| `web/components/stock/panels/InsightPanel.tsx` | Shared panel shell + dashed status banner used by every Trade Insights panel. |
| `web/components/stock/panels/TradeInsightsBiasBanner.tsx` | Bias / setup / confidence / data-quality row + badges. Does NOT render the ticker (the layout's `DetailHeader` already does). |
| `web/components/stock/panels/SourceReconciliationPanel.tsx` | Source agreement table and decision on IV/price trust. |
| `web/components/stock/panels/SignalStackPanel.tsx` | Deterministic lens table: vol level, vol stability, realized regime, correlation, flow, structure. |
| `web/components/stock/panels/ChainFlowReadPanel.tsx` | Strike-level call/put volume/OI table with T+1 OI confirmation caveat. |
| `web/components/stock/panels/TermMovePanel.tsx` | Expiry-level ATM straddle, implied move, daily implied move table. |
| `web/components/stock/panels/CandidateStructuresPanel.tsx` | Candidate cards for credit spreads, iron condor, long straddle, and calendar. |
| `web/components/stock/panels/InsightsSynthesisPanel.tsx` | Dominant story, preferred expression, avoid list, and required checks. |
| `web/tests/unit/tradeInsightsPanels.test.tsx` | Vitest render tests for panels and empty states. |

### Modified backend files

| Path | What changes |
|---|---|
| `src/uw_scan/models.py` | Add `TradeInsightsResponse` and submodels. |
| `src/uw_scan/storage/repository.py` | Add richer current-run fetch for option contracts with ask/bid volume and `prev_oi`; add latest volatility-series helper if needed; add idempotent Trade Insights persistence helpers. |
| `src/uw_scan/pipeline.py` | Persist a Trade Insights snapshot at the end of successful single-stock scans so validation does not depend on a user opening the tab. |
| `src/uw_scan/api/server.py` | Mount the new `trade_insights` router. |

### Modified frontend files

| Path | What changes |
|---|---|
| `web/components/stock/TabBar.tsx` | Add `["trade-insights", "Trade Insights"]` between `Flow` and `Trade Plan`. Final order: Market Structure / Volatility / Flow / Trade Insights / Trade Plan. The `Tables` tab no longer exists (merged into `Flow` in 2026-05). |
| `web/app/stock/[ticker]/[tab]/page.tsx` | Add `trade-insights` case. |
| `web/lib/api.ts` | Add `api.tradeInsights(ticker)` helper and export `TradeInsightsResponse`. |
| `web/lib/types.ts` | Regenerate from OpenAPI after backend endpoint lands. |

---

## Phase 1 — Backend types and deterministic helpers

### Task 1.1: Add response models

**Files:**
- Modify: `src/uw_scan/models.py`
- Test: `tests/test_trade_insights.py`

- [x] **Step 1: Add model imports if missing**

In `src/uw_scan/models.py`, keep using existing imports:

```python
from datetime import date as _date
from datetime import date, datetime
from decimal import Decimal
```

- [x] **Step 2: Add Trade Insights models before `SingleStockReport` or after `VolatilitySeriesResponse`**

Add this block:

```python
class InsightBadge(_UwBase):
    code: str
    label: str
    severity: str = "info"


class TradeInsightsHeader(_UwBase):
    dominant_bias: str = "NEUTRAL"
    primary_setup: str = "NO_CLEAR_SETUP"
    confidence_label: str = "LOW"
    data_quality_label: str = "INSUFFICIENT"
    idea_count: int = 0
    preferred_idea_id: str | None = None
    badges: list[InsightBadge] = []


class SourceReconciliationRow(_UwBase):
    source_pair: str
    price_agreement: str = ""
    iv_agreement: str = ""
    decision: str = ""
    strike: Decimal | None = None
    source_a_call_iv: Decimal | None = None
    source_b_call_iv: Decimal | None = None
    iv_diff: Decimal | None = None


class SourceReconciliation(_UwBase):
    status: str = "UNKNOWN"
    headline: str = "Source reconciliation unavailable"
    primary_iv_source: str | None = None
    relative_shape_source: str | None = None
    rows: list[SourceReconciliationRow] = []
    decision: str = "Use deterministic data only where source agreement is understood."


class InsightSignalRow(_UwBase):
    lens: str
    read: str
    evidence: list[str] = []
    conflicts: list[str] = []


class ChainFlowReadRow(_UwBase):
    strike: Decimal
    call_volume: int | None = None
    call_open_interest: int | None = None
    put_volume: int | None = None
    put_open_interest: int | None = None
    call_put_volume_ratio: Decimal | None = None
    volume_oi_note: str = ""
    read: str = ""
    requires_t1_oi_confirmation: bool = False


class TermMoveRow(_UwBase):
    expiry: _date
    dte: int | None = None
    atm_straddle: Decimal | None = None
    implied_move_perc: Decimal | None = None
    daily_implied_move_perc: Decimal | None = None
    read: str = ""


class InsightLeg(_UwBase):
    side: str
    option_symbol: str
    option_right: str
    expiry: _date
    strike: Decimal
    mid: Decimal | None = None


class CandidateStructure(_UwBase):
    idea_id: str
    structure: str
    thesis: str
    expression_type: str
    legs: list[InsightLeg] = []
    net_credit_debit: Decimal | None = None
    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    breakevens: list[Decimal] = []
    profit_zone: str = ""
    edge_source: str = ""
    risk_flags: list[str] = []
    rank: int
    status: str = "candidate"


class InsightsSynthesis(_UwBase):
    dominant_story: str = ""
    preferred_idea_id: str | None = None
    best_risk_reward_idea_id: str | None = None
    avoid: list[str] = []
    required_before_sizing: list[str] = []


class TradeInsightsResponse(_UwBase):
    ticker: str
    as_of: datetime | None = None
    mode: str = "research"
    header: TradeInsightsHeader
    source_reconciliation: SourceReconciliation = SourceReconciliation()
    signal_stack: list[InsightSignalRow] = []
    flow_table: list[ChainFlowReadRow] = []
    term_structure_table: list[TermMoveRow] = []
    candidate_structures: list[CandidateStructure] = []
    synthesis: InsightsSynthesis = InsightsSynthesis()
```

- [x] **Step 3: Add a model serialization test**

Create `tests/test_trade_insights.py` with (the `Decimal` import is needed because every subsequent test in this file uses it):

```python
from decimal import Decimal

from uw_scan.models import (
    CandidateStructure,
    InsightLeg,
    TradeInsightsHeader,
    TradeInsightsResponse,
)


def test_trade_insights_response_serializes_required_shape():
    response = TradeInsightsResponse(
        ticker="TSLA",
        header=TradeInsightsHeader(
            dominant_bias="NEUTRAL_SHORT_VOL",
            primary_setup="IV_RV_SPREAD_MEAN_REVERSION",
            confidence_label="MEDIUM",
            data_quality_label="MIXED",
            idea_count=1,
        ),
        candidate_structures=[
            CandidateStructure(
                idea_id="A",
                structure="call_credit_spread",
                thesis="Front premium is elevated.",
                expression_type="SHORT_VOL",
                rank=1,
                max_loss=Decimal("1.25"),
                legs=[
                    InsightLeg(
                        side="sell",
                        option_symbol="TSLA260515C00430000",
                        option_right="C",
                        expiry="2026-05-15",
                        strike=Decimal("430"),
                        mid=Decimal("9.50"),
                    )
                ],
            )
        ],
    )

    body = response.model_dump(mode="json")
    assert body["ticker"] == "TSLA"
    assert body["header"]["dominant_bias"] == "NEUTRAL_SHORT_VOL"
    assert body["candidate_structures"][0]["legs"][0]["strike"] == "430"
    assert body["source_reconciliation"]["status"] == "UNKNOWN"
```

- [x] **Step 4: Run the test**

Run:

```bash
uv run pytest tests/test_trade_insights.py -q
```

Expected before model block is complete: import or validation failure. Expected after model block: `1 passed`.

- [x] **Step 5: Commit**

```bash
git add src/uw_scan/models.py tests/test_trade_insights.py
git commit -m "Add Trade Insights response models"
```

### Task 1.2: Add OCC/OSI symbol parser and candidate math helpers

**Files:**
- Create/modify: `src/uw_scan/reports/trade_insights.py`
- Test: `tests/test_trade_insights.py`

- [x] **Step 1: Add parser tests**

Append to `tests/test_trade_insights.py`:

```python
from datetime import date

from uw_scan.reports.trade_insights import (
    ParsedOptionSymbol,
    _credit_spread_math,
    _mid,
    parse_option_symbol,
)


def test_parse_option_symbol_occ_style():
    parsed = parse_option_symbol("TSLA260515C00430000")
    assert parsed == ParsedOptionSymbol(
        root="TSLA",
        expiry=date(2026, 5, 15),
        right="C",
        strike=Decimal("430"),
    )


def test_parse_option_symbol_rejects_bad_symbol():
    assert parse_option_symbol("bad") is None


def test_mid_uses_nbbo_when_present():
    assert _mid({"nbbo_bid": Decimal("1.00"), "nbbo_ask": Decimal("1.20")}) == Decimal(
        "1.10"
    )


def test_mid_falls_back_to_last_price():
    assert _mid({"last_price": Decimal("0.95")}) == Decimal("0.95")


def test_credit_spread_math_caps_loss_by_width_minus_credit():
    net_credit, max_loss, max_profit = _credit_spread_math(
        short_mid=Decimal("1.80"),
        long_mid=Decimal("0.55"),
        width=Decimal("5"),
    )
    assert net_credit == Decimal("1.25")
    assert max_loss == Decimal("3.75")
    assert max_profit == Decimal("1.25")
```

- [x] **Step 2: Implement helpers**

Create `src/uw_scan/reports/trade_insights.py` with:

```python
"""Deterministic Trade Insights assembler.

V1 is intentionally rule-based. Codex/LLM commentary is a later optional layer
that consumes this structured output but does not alter status or risk checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ParsedOptionSymbol:
    root: str
    expiry: date
    right: str
    strike: Decimal


def parse_option_symbol(symbol: str) -> ParsedOptionSymbol | None:
    """Parse OCC/OSI-style compact symbols like TSLA260515C00430000."""
    if len(symbol) < 15:
        return None
    right_index = max(symbol.rfind("C"), symbol.rfind("P"))
    if right_index < 6:
        return None
    right = symbol[right_index]
    ymd = symbol[right_index - 6 : right_index]
    strike_raw = symbol[right_index + 1 :]
    root = symbol[: right_index - 6]
    if not root or len(ymd) != 6 or len(strike_raw) != 8:
        return None
    try:
        expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
        strike = Decimal(str(int(strike_raw))) / Decimal("1000")
    except (ValueError, ArithmeticError):
        return None
    return ParsedOptionSymbol(root=root, expiry=expiry, right=right, strike=strike)


def _dec(v: object) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _mid(contract: dict) -> Decimal | None:
    bid = _dec(contract.get("nbbo_bid"))
    ask = _dec(contract.get("nbbo_ask"))
    if bid is not None and ask is not None and bid >= 0 and ask >= bid:
        return (bid + ask) / Decimal("2")
    return _dec(contract.get("last_price"))


def _credit_spread_math(
    *, short_mid: Decimal, long_mid: Decimal, width: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    net_credit = short_mid - long_mid
    max_profit = net_credit
    max_loss = width - net_credit
    return net_credit, max_loss, max_profit
```

- [x] **Step 3: Run helper tests**

Run:

```bash
uv run pytest tests/test_trade_insights.py -q
```

Expected: all tests pass.

- [x] **Step 4: Commit**

```bash
git add src/uw_scan/reports/trade_insights.py tests/test_trade_insights.py
git commit -m "Add Trade Insights option parser helpers"
```

---

## Phase 2 — Backend assembler and API endpoint

### Task 2.0: Add Trade Insights persistence tables

**Files:**
- Create: `src/uw_scan/storage/migrations/016_trade_insights.sql`
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_repository_trade_insights.py`

- [x] **Step 1: Add migration**

Create `src/uw_scan/storage/migrations/016_trade_insights.sql`:

```sql
-- Persist deterministic Trade Insights outputs for later validation/backtests.
-- The UI renders the current response, but research improvement depends on
-- retaining exactly what the rule engine emitted for each source run.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_snapshots (
    snapshot_id                  BIGSERIAL PRIMARY KEY,
    run_id                       BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker                       TEXT NOT NULL,
    as_of                        TIMESTAMPTZ,
    assembler_version            TEXT NOT NULL,
    input_hash                   TEXT NOT NULL,
    source_reconciliation_status TEXT,
    confidence_label             TEXT,
    data_quality_label           TEXT,
    preferred_idea_id            TEXT,
    payload_jsonb                JSONB NOT NULL,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ticker, assembler_version, input_hash)
);

CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_candidates (
    snapshot_id       BIGINT NOT NULL REFERENCES uw_scan.trade_insight_snapshots(snapshot_id) ON DELETE CASCADE,
    idea_id           TEXT NOT NULL,
    ticker            TEXT NOT NULL,
    run_id            BIGINT NOT NULL,
    structure         TEXT NOT NULL,
    expression_type   TEXT,
    rank              INTEGER NOT NULL,
    status            TEXT NOT NULL,
    net_credit_debit  NUMERIC,
    max_profit        NUMERIC,
    max_loss          NUMERIC,
    edge_source       TEXT,
    risk_flags        TEXT[] NOT NULL DEFAULT '{}',
    legs_jsonb        JSONB NOT NULL DEFAULT '[]'::jsonb,
    candidate_jsonb   JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, idea_id)
);

CREATE INDEX IF NOT EXISTS idx_trade_insight_snapshots_ticker_created
    ON uw_scan.trade_insight_snapshots (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trade_insight_candidates_structure_status
    ON uw_scan.trade_insight_candidates (structure, status, rank);

COMMENT ON TABLE uw_scan.trade_insight_snapshots IS
    'Idempotent deterministic Trade Insights response snapshots used for later validation and backtests.';
COMMENT ON TABLE uw_scan.trade_insight_candidates IS
    'Queryable candidate rows emitted by the deterministic Trade Insights assembler.';
```

- [x] **Step 2: Add repository persistence helper**

In `src/uw_scan/storage/repository.py`, add:

```python
    def upsert_trade_insight_snapshot(
        self,
        *,
        run_id: int,
        ticker: str,
        as_of: datetime | None,
        assembler_version: str,
        input_hash: str,
        payload: dict[str, Any],
    ) -> int:
        header = payload.get("header") or {}
        source_reconciliation = payload.get("source_reconciliation") or {}
        sql = (
            f"INSERT INTO {self._schema}.trade_insight_snapshots "
            "(run_id, ticker, as_of, assembler_version, input_hash, "
            "source_reconciliation_status, confidence_label, data_quality_label, "
            "preferred_idea_id, payload_jsonb) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, assembler_version, input_hash) "
            "DO UPDATE SET payload_jsonb=EXCLUDED.payload_jsonb, "
            "source_reconciliation_status=EXCLUDED.source_reconciliation_status, "
            "confidence_label=EXCLUDED.confidence_label, "
            "data_quality_label=EXCLUDED.data_quality_label, "
            "preferred_idea_id=EXCLUDED.preferred_idea_id "
            "RETURNING snapshot_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    ticker.upper(),
                    as_of,
                    assembler_version,
                    input_hash,
                    source_reconciliation.get("status"),
                    header.get("confidence_label"),
                    header.get("data_quality_label"),
                    header.get("preferred_idea_id"),
                    Jsonb(payload),
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def replace_trade_insight_candidates(
        self,
        *,
        snapshot_id: int,
        run_id: int,
        ticker: str,
        candidates: list[dict[str, Any]],
    ) -> int:
        delete_sql = f"DELETE FROM {self._schema}.trade_insight_candidates WHERE snapshot_id = %s"
        insert_sql = (
            f"INSERT INTO {self._schema}.trade_insight_candidates "
            "(snapshot_id, idea_id, ticker, run_id, structure, expression_type, rank, "
            "status, net_credit_debit, max_profit, max_loss, edge_source, risk_flags, "
            "legs_jsonb, candidate_jsonb) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        with self._conn.cursor() as cur:
            cur.execute(delete_sql, (snapshot_id,))
            for c in candidates:
                cur.execute(
                    insert_sql,
                    (
                        snapshot_id,
                        c["idea_id"],
                        ticker.upper(),
                        run_id,
                        c["structure"],
                        c.get("expression_type"),
                        c["rank"],
                        c["status"],
                        c.get("net_credit_debit"),
                        c.get("max_profit"),
                        c.get("max_loss"),
                        c.get("edge_source"),
                        list(c.get("risk_flags") or []),
                        Jsonb(c.get("legs") or []),
                        Jsonb(c),
                    ),
                )
        return len(candidates)
```

- [x] **Step 3: Add storage integration test**

Create `tests/integration/storage/test_repository_trade_insights.py` with an idempotency check. Use the existing `seeded_db_empty_cards` fixture (returns a fully-migrated `Repository`) — that's the pattern every other storage integration test follows (see `tests/integration/storage/test_repository_vol_v2.py`). There is no `repo` or `migrated_db` fixture in conftest:

```python
from datetime import datetime, timezone


def test_trade_insight_snapshot_upsert_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("TSLA")
    payload = {
        "ticker": "TSLA",
        "header": {
            "confidence_label": "LOW",
            "data_quality_label": "INSUFFICIENT",
            "preferred_idea_id": None,
        },
        "source_reconciliation": {"status": "UNKNOWN"},
        "candidate_structures": [
            {
                "idea_id": "A",
                "structure": "call_credit_spread",
                "expression_type": "SHORT_VOL",
                "rank": 1,
                "status": "needs_check",
                "max_loss": "3.75",
                "risk_flags": ["event_check_required"],
                "legs": [],
            }
        ],
    }

    kwargs = {
        "run_id": run_id,
        "ticker": "TSLA",
        "as_of": datetime(2026, 5, 13, tzinfo=timezone.utc),
        "assembler_version": "trade-insights-v1",
        "input_hash": "abc123",
        "payload": payload,
    }
    first = repo.upsert_trade_insight_snapshot(**kwargs)
    second = repo.upsert_trade_insight_snapshot(**kwargs)
    assert first == second

    written = repo.replace_trade_insight_candidates(
        snapshot_id=first,
        run_id=run_id,
        ticker="TSLA",
        candidates=payload["candidate_structures"],
    )
    assert written == 1
```

- [x] **Step 4: Run migration/storage tests**

```bash
bash scripts/migrate.sh
uv run pytest tests/integration/storage/test_repository_trade_insights.py -q
```

- [x] **Step 5: Commit**

```bash
git add src/uw_scan/storage/migrations/016_trade_insights.sql src/uw_scan/storage/repository.py tests/integration/storage/test_repository_trade_insights.py
git commit -m "Persist Trade Insights research snapshots"
```

### Task 2.1: Add repository fetch for rich option contracts

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/test_trade_insights.py`

- [x] **Step 1: Add a repository-shape test with a fake repo**

Append this test to `tests/test_trade_insights.py` after Task 2.2 adds `assemble_trade_insights`; keep it skipped until the assembler exists by adding it in Task 2.2, not now. No code change in this step.

- [x] **Step 2: Add `fetch_option_contracts_rich`**

In `src/uw_scan/storage/repository.py`, near `fetch_option_contracts`, add:

```python
    def fetch_option_contracts_rich(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT option_symbol, last_price, nbbo_bid, nbbo_ask, "
            "implied_volatility, open_interest, prev_oi, volume, ask_volume, "
            "bid_volume, mid_volume, multi_leg_volume, stock_multi_leg_volume, "
            "floor_volume, sweep_volume, no_side_volume, avg_price, high_price, "
            "low_price, total_premium "
            f"FROM {self._schema}.option_contract_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY total_premium DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

- [x] **Step 2b: Add `fetch_iv_term_rows`**

The Trade Insights assembler needs term-structure rows. `iv_term_snapshots` already exists (migration `001_s1_core_tables.sql`) but has no read helper. Add one in the same module:

```python
    def fetch_iv_term_rows(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT expiry, dte, volatility, implied_move, implied_move_perc "
            f"FROM {self._schema}.iv_term_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY expiry ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker.upper()))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

If the table is empty for a run (e.g., new ticker, no UW term endpoint hit yet), the helper returns `[]` and the assembler emits `term_structure_table: []` with `signal_stack` lens `TERM: MISSING`.

- [x] **Step 3: Run static test target**

Run:

```bash
uv run pytest tests/test_trade_insights.py -q
```

Expected: existing tests still pass.

- [x] **Step 4: Commit**

```bash
git add src/uw_scan/storage/repository.py
git commit -m "Add rich option contract fetch for Trade Insights"
```

### Task 2.2: Assemble deterministic Trade Insights response

**Files:**
- Modify: `src/uw_scan/reports/trade_insights.py`
- Test: `tests/test_trade_insights.py`

- [x] **Step 1: Add assembler tests with a fake repo**

Append to `tests/test_trade_insights.py`:

```python
from datetime import date, datetime, timezone

from uw_scan.reports.trade_insights import assemble_trade_insights


def _contract(
    symbol: str,
    *,
    bid: str,
    ask: str,
    iv: str = "0.52",
    volume: int = 1000,
    oi: int = 800,
):
    return {
        "option_symbol": symbol,
        "last_price": Decimal(bid),
        "nbbo_bid": Decimal(bid),
        "nbbo_ask": Decimal(ask),
        "implied_volatility": Decimal(iv),
        "open_interest": oi,
        "prev_oi": max(oi - 50, 0),
        "volume": volume,
        "ask_volume": int(volume * 0.55),
        "bid_volume": int(volume * 0.35),
        "total_premium": Decimal(bid) * Decimal(volume),
    }


class FakeTradeInsightsRepo:
    def fetch_option_contracts_rich(self, run_id: int, ticker: str):
        return [
            _contract("TSLA260515P00420000", bid="6.10", ask="6.30", volume=450, oi=500),
            _contract("TSLA260515P00425000", bid="8.00", ask="8.20", volume=600, oi=700),
            _contract("TSLA260515P00430000", bid="10.20", ask="10.50", volume=900, oi=850),
            _contract("TSLA260515C00430000", bid="9.40", ask="9.60", volume=1500, oi=1000),
            _contract("TSLA260515C00435000", bid="6.90", ask="7.10", volume=1200, oi=800),
            _contract("TSLA260522C00430000", bid="13.80", ask="14.20", iv="0.48", volume=700, oi=900),
        ]

    def fetch_iv_term_rows(self, run_id: int, ticker: str):
        return [
            {
                "expiry": date(2026, 5, 15),
                "dte": 4,
                "implied_move_perc": Decimal("0.048"),
            },
            {
                "expiry": date(2026, 5, 22),
                "dte": 11,
                "implied_move_perc": Decimal("0.067"),
            }
        ]

    def fetch_source_reconciliation_rows(self, run_id: int, ticker: str):
        return []


def test_assemble_trade_insights_builds_research_response():
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )

    assert response.ticker == "TSLA"
    # V1 only emits MIXED or INSUFFICIENT; READY is reserved for a later patch
    # that wires event/source/liquidity gates fully.
    assert response.header.data_quality_label == "MIXED"
    assert response.signal_stack
    assert response.flow_table
    assert response.term_structure_table
    assert response.candidate_structures
    assert all(c.max_loss is not None for c in response.candidate_structures)
    assert {
        "call_credit_spread",
        "put_credit_spread",
        "iron_condor",
        "long_straddle",
        "calendar_spread",
    }.issubset({c.structure for c in response.candidate_structures})
    assert response.source_reconciliation.status == "UNKNOWN"
    assert response.header.preferred_idea_id is None
    assert response.synthesis.preferred_idea_id is None
    assert all(c.status == "needs_check" for c in response.candidate_structures)


def test_iron_condor_max_loss_matches_width_minus_total_credit():
    """Locks in the corrected formula: max(call_width, put_width) - total_credit.

    With the fake fixture (5-point wings on both sides, ~4.75 total credit),
    max loss should be 0.25 per spread, not max(call_spread.max_loss,
    put_spread.max_loss). The earlier draft of the plan used the latter and
    over-stated max loss by ~10x.
    """
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )
    ic = next(c for c in response.candidate_structures if c.structure == "iron_condor")
    call_spread = next(c for c in response.candidate_structures if c.structure == "call_credit_spread")
    put_spread = next(c for c in response.candidate_structures if c.structure == "put_credit_spread")

    expected_credit = (call_spread.net_credit_debit or Decimal("0")) + (
        put_spread.net_credit_debit or Decimal("0")
    )
    assert ic.net_credit_debit == expected_credit
    assert ic.max_profit == expected_credit
    # Both wings are 5 points wide in the fixture; max wing breach loss is
    # width - total_credit, not the max of the per-wing losses.
    assert ic.max_loss == Decimal("5") - expected_credit
```

- [x] **Step 2: Implement simple V1 assembler**

Extend `src/uw_scan/reports/trade_insights.py` with:

```python
import hashlib
import json
from datetime import date, datetime

from uw_scan.models import (
    CandidateStructure,
    ChainFlowReadRow,
    InsightBadge,
    InsightLeg,
    InsightSignalRow,
    InsightsSynthesis,
    TermMoveRow,
    SourceReconciliation,
    SourceReconciliationRow,
    TradeInsightsHeader,
    TradeInsightsResponse,
)


ASSEMBLER_VERSION = "trade-insights-v1"


def _stable_payload_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalized_contracts(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in raw:
        parsed = parse_option_symbol(str(row.get("option_symbol", "")))
        if parsed is None:
            continue
        item = dict(row)
        item["parsed"] = parsed
        item["mid"] = _mid(row)
        out.append(item)
    return out


def _build_flow_table(contracts: list[dict]) -> list[ChainFlowReadRow]:
    by_strike: dict[Decimal, dict[str, dict]] = {}
    for c in contracts:
        parsed: ParsedOptionSymbol = c["parsed"]
        by_strike.setdefault(parsed.strike, {})[parsed.right] = c

    rows: list[ChainFlowReadRow] = []
    for strike in sorted(by_strike):
        call = by_strike[strike].get("C", {})
        put = by_strike[strike].get("P", {})
        call_volume = call.get("volume")
        put_volume = put.get("volume")
        call_oi = call.get("open_interest")
        put_oi = put.get("open_interest")
        ratio = None
        if call_volume is not None and put_volume not in (None, 0):
            ratio = Decimal(str(call_volume)) / Decimal(str(put_volume))
        requires_t1 = bool(
            (call_volume is not None and call_oi is not None and call_volume > call_oi)
            or (put_volume is not None and put_oi is not None and put_volume > put_oi)
        )
        rows.append(
            ChainFlowReadRow(
                strike=strike,
                call_volume=call_volume,
                call_open_interest=call_oi,
                put_volume=put_volume,
                put_open_interest=put_oi,
                call_put_volume_ratio=ratio,
                volume_oi_note="Volume > OI; confirm with next-day OI"
                if requires_t1
                else "No volume/OI anomaly",
                read="Call demand concentrated"
                if ratio is not None and ratio > Decimal("1.5")
                else "Mixed flow",
                requires_t1_oi_confirmation=requires_t1,
            )
        )
    return rows


def _build_source_reconciliation(repo, run_id: int, ticker: str) -> SourceReconciliation:
    fetch = getattr(repo, "fetch_source_reconciliation_rows", None)
    rows = fetch(run_id, ticker) if fetch is not None else []
    if not rows:
        return SourceReconciliation(
            status="UNKNOWN",
            headline="No external IV source reconciliation stored for this run",
            decision="Use chain-derived values for contract math; do not make absolute-IV trust claims.",
        )
    return SourceReconciliation(
        status="MIXED" if any(r.get("iv_diff") for r in rows) else "READY",
        headline="Source reconciliation rows available",
        rows=[SourceReconciliationRow(**r) for r in rows],
        decision="Prefer chain-derived IV for absolute cheap/rich decisions when vendor IV disagrees.",
    )


def _atm_straddles_by_expiry(
    contracts: list[dict], spot: Decimal | None
) -> dict[date, Decimal]:
    if spot is None:
        return {}
    out: dict[date, Decimal] = {}
    expiries = sorted({c["parsed"].expiry for c in contracts})
    for expiry in expiries:
        same_expiry = [c for c in contracts if c["parsed"].expiry == expiry and c.get("mid") is not None]
        calls = [c for c in same_expiry if c["parsed"].right == "C"]
        puts = [c for c in same_expiry if c["parsed"].right == "P"]
        if not calls or not puts:
            continue
        call = min(calls, key=lambda c: abs(c["parsed"].strike - spot))
        put = min(puts, key=lambda c: abs(c["parsed"].strike - spot))
        if call["parsed"].strike == put["parsed"].strike:
            out[expiry] = call["mid"] + put["mid"]
    return out


def _build_term_rows(
    raw: list[dict], contracts: list[dict], spot: Decimal | None
) -> list[TermMoveRow]:
    atm_by_expiry = _atm_straddles_by_expiry(contracts, spot)
    rows: list[TermMoveRow] = []
    for r in raw:
        dte = r.get("dte")
        move = _dec(r.get("implied_move_perc"))
        daily = None
        if dte and move is not None and dte > 0:
            daily = move / Decimal(str(dte))
        rows.append(
            TermMoveRow(
                expiry=r["expiry"],
                dte=dte,
                atm_straddle=atm_by_expiry.get(r["expiry"]),
                implied_move_perc=move,
                daily_implied_move_perc=daily,
                read="Front elevated" if dte is not None and dte <= 7 else "Back expiry",
            )
        )
    return rows


def _leg(side: str, c: dict) -> InsightLeg:
    parsed: ParsedOptionSymbol = c["parsed"]
    return InsightLeg(
        side=side,
        option_symbol=c["option_symbol"],
        option_right=parsed.right,
        expiry=parsed.expiry,
        strike=parsed.strike,
        mid=c.get("mid"),
    )


def _build_candidates(contracts: list[dict], spot: Decimal | None) -> list[CandidateStructure]:
    if spot is None:
        return []
    calls = sorted(
        [c for c in contracts if c["parsed"].right == "C" and c.get("mid") is not None],
        key=lambda c: abs(c["parsed"].strike - spot),
    )
    puts = sorted(
        [c for c in contracts if c["parsed"].right == "P" and c.get("mid") is not None],
        key=lambda c: abs(c["parsed"].strike - spot),
    )
    candidates: list[CandidateStructure] = []

    if len(calls) >= 2:
        short_call = calls[0]
        long_call = next(
            (c for c in calls[1:] if c["parsed"].strike > short_call["parsed"].strike),
            None,
        )
        if long_call is not None:
            width = long_call["parsed"].strike - short_call["parsed"].strike
            credit, max_loss, max_profit = _credit_spread_math(
                short_mid=short_call["mid"], long_mid=long_call["mid"], width=width
            )
            candidates.append(
                CandidateStructure(
                    idea_id="A",
                    structure="call_credit_spread",
                    thesis="Defined-risk short-call premium candidate.",
                    expression_type="SHORT_VOL",
                    legs=[_leg("sell", short_call), _leg("buy", long_call)],
                    net_credit_debit=credit,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    profit_zone=f"Underlying below {short_call['parsed'].strike}",
                    edge_source="IV-RV spread / theta",
                    risk_flags=["bullish_flow_can_break_call_side"],
                    rank=1,
                    status="candidate",
                )
            )

    if len(puts) >= 2:
        short_put = puts[0]
        long_put = next(
            (p for p in puts[1:] if p["parsed"].strike < short_put["parsed"].strike),
            None,
        )
        if long_put is not None:
            width = short_put["parsed"].strike - long_put["parsed"].strike
            credit, max_loss, max_profit = _credit_spread_math(
                short_mid=short_put["mid"], long_mid=long_put["mid"], width=width
            )
            candidates.append(
                CandidateStructure(
                    idea_id="B",
                    structure="put_credit_spread",
                    thesis="Defined-risk short-put premium candidate.",
                    expression_type="DIRECTIONAL_THETA",
                    legs=[_leg("sell", short_put), _leg("buy", long_put)],
                    net_credit_debit=credit,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    profit_zone=f"Underlying above {short_put['parsed'].strike}",
                    edge_source="theta / bullish flow",
                    risk_flags=["gap_down_risk"],
                    rank=2,
                    status="candidate",
                )
            )

    if len(candidates) >= 2:
        call_spread = next((c for c in candidates if c.structure == "call_credit_spread"), None)
        put_spread = next((c for c in candidates if c.structure == "put_credit_spread"), None)
        if call_spread and put_spread and call_spread.net_credit_debit and put_spread.net_credit_debit:
            # Iron condor math: max loss equals the wider wing's width minus the
            # TOTAL credit collected from both verticals. Only one wing can be
            # breached at expiry, so the loss on that wing is (width - credit),
            # not the sum of the two wing losses. Using max(call_spread.max_loss,
            # put_spread.max_loss) double-counts the credit on the unused wing
            # and understates the actual max loss whenever credit > 0.
            call_short_strike = call_spread.legs[0].strike
            call_long_strike = call_spread.legs[1].strike
            put_short_strike = put_spread.legs[0].strike
            put_long_strike = put_spread.legs[1].strike
            call_width = abs(call_long_strike - call_short_strike)
            put_width = abs(put_short_strike - put_long_strike)
            credit = call_spread.net_credit_debit + put_spread.net_credit_debit
            max_loss = max(call_width, put_width) - credit
            candidates.append(
                CandidateStructure(
                    idea_id="C",
                    structure="iron_condor",
                    thesis="Defined-risk range candidate built from both short verticals.",
                    expression_type="SHORT_VOL_RANGE",
                    legs=[*put_spread.legs, *call_spread.legs],
                    net_credit_debit=credit,
                    max_profit=credit,
                    max_loss=max_loss,
                    profit_zone=f"{put_spread.profit_zone}; {call_spread.profit_zone}",
                    edge_source="term structure / IV-RV spread / range structure",
                    risk_flags=["breakout_risk", "event_check_required"],
                    rank=3,
                    status="candidate",
                )
            )

    front_expiry = min((c["parsed"].expiry for c in contracts), default=None)
    if front_expiry is not None:
        front_calls = [c for c in calls if c["parsed"].expiry == front_expiry]
        front_puts = [p for p in puts if p["parsed"].expiry == front_expiry]
        if front_calls and front_puts:
            call = front_calls[0]
            put = min(front_puts, key=lambda p: abs(p["parsed"].strike - call["parsed"].strike))
            debit = call["mid"] + put["mid"]
            strike = call["parsed"].strike
            candidates.append(
                CandidateStructure(
                    idea_id="D",
                    structure="long_straddle",
                    thesis="Long-vol candidate for cheap-vol or realized-move expansion setups.",
                    expression_type="LONG_VOL",
                    legs=[_leg("buy", call), _leg("buy", put)],
                    net_credit_debit=-debit,
                    max_loss=debit,
                    max_profit=None,
                    breakevens=[strike - debit, strike + debit]
                    if call["parsed"].strike == put["parsed"].strike
                    else [],
                    edge_source="realized-vol expansion / cheap IV",
                    risk_flags=["theta_decay", "requires_realized_move"],
                    rank=4,
                    status="candidate",
                )
            )

    calendar_pairs = [
        (near, far)
        for near in calls
        for far in calls
        if near["parsed"].strike == far["parsed"].strike
        and near["parsed"].expiry < far["parsed"].expiry
    ]
    if calendar_pairs:
        near, far = calendar_pairs[0]
        debit = far["mid"] - near["mid"]
        # Calendar spread: max loss is bounded by the initial net debit only if
        # the position is held to expiration of the far leg. Earlier exit (the
        # normal exit, around the front expiry) has path-dependent P&L driven by
        # term-structure shifts and changes in far-leg IV; theoretical max loss
        # at the front expiry can exceed the debit if the far leg's IV collapses.
        # V1 reports the "held-to-far-expiry" bound as max_loss and flags the
        # path-dependence in risk_flags so users do not treat it as a hard cap.
        # If the near leg is more expensive than the far leg (backwardation),
        # this becomes a credit calendar; we skip the candidate rather than
        # report a negative debit, because that scenario needs different math.
        if debit <= Decimal("0"):
            pass
        else:
            candidates.append(
                CandidateStructure(
                    idea_id="E",
                    structure="calendar_spread",
                    thesis="Term-structure candidate: sell front volatility, buy later expiry.",
                    expression_type="TERM_STRUCTURE",
                    legs=[_leg("sell", near), _leg("buy", far)],
                    net_credit_debit=-debit,
                    max_loss=debit,
                    max_profit=None,
                    profit_zone=f"Near {near['parsed'].strike} through front expiry",
                    edge_source="front/back implied-vol dislocation",
                    risk_flags=[
                        "event_check_required",
                        "assignment_ex_dividend_check",
                        "path_dependent_far_iv_collapse",
                    ],
                    rank=5,
                    status="candidate",
                )
            )

    return candidates


def assemble_trade_insights(
    *,
    ticker: str,
    run_id: int,
    repo,
    as_of: datetime | None,
    spot: Decimal | None,
) -> TradeInsightsResponse:
    contracts = _normalized_contracts(repo.fetch_option_contracts_rich(run_id, ticker))
    source_reconciliation = _build_source_reconciliation(repo, run_id, ticker)
    flow_rows = _build_flow_table(contracts)
    term_rows = _build_term_rows(repo.fetch_iv_term_rows(run_id, ticker), contracts, spot)
    candidates = _build_candidates(contracts, spot)
    # V1 intentionally hardcodes event_data_known=False so every candidate ends
    # as `needs_check` and `preferred_idea_id` stays None. The earnings/dividend
    # plumbing exists upstream (flow_events.next_earnings_date,
    # SingleStockReport.next_earnings_date) but is not wired through to this
    # assembler in V1. A follow-up patch should read those fields and flip the
    # gate when both are present and outside all candidate expiries.
    event_data_known = False
    liquidity_ready = bool(contracts) and all(c.max_loss is not None for c in candidates)

    badges: list[InsightBadge] = [InsightBadge(code="DEFINED_RISK_ONLY", label="Defined-risk only")]
    if not contracts:
        badges.append(InsightBadge(code="NO_CHAIN", label="No option chain", severity="warning"))
    if source_reconciliation.status in {"UNKNOWN", "MIXED"}:
        badges.append(
            InsightBadge(
                code="SOURCE_RECONCILIATION_REQUIRED",
                label="Source reconciliation incomplete",
                severity="warning",
            )
        )
    if not event_data_known:
        badges.append(
            InsightBadge(
                code="EVENT_CHECK_REQUIRED",
                label="Event check required",
                severity="warning",
            )
        )
    if any(r.requires_t1_oi_confirmation for r in flow_rows):
        badges.append(
            InsightBadge(
                code="T1_OI_CONFIRMATION",
                label="Volume > OI needs next-day OI confirmation",
                severity="warning",
            )
        )

    signal_stack = [
        InsightSignalRow(
            lens="VOL_LEVEL",
            read="IV_RV_PROXY_AVAILABLE",
            evidence=["Use Volatility tab IV-RV spread proxy; true model-free VRP not computed."],
        ),
        InsightSignalRow(
            lens="FLOW",
            read="CALL_DEMAND" if any((r.call_put_volume_ratio or 0) > 1 for r in flow_rows) else "MIXED",
            evidence=[f"{len(flow_rows)} strike rows available"],
        ),
        InsightSignalRow(
            lens="TERM",
            read="TERM_ROWS_AVAILABLE" if term_rows else "MISSING",
            evidence=[f"{len(term_rows)} expiries available"],
        ),
    ]

    can_prefer = (
        bool(candidates)
        and event_data_known
        and liquidity_ready
        and source_reconciliation.status != "UNKNOWN"
    )
    if not can_prefer:
        for candidate in candidates:
            candidate.status = "needs_check"
    preferred = candidates[0].idea_id if can_prefer else None
    return TradeInsightsResponse(
        ticker=ticker,
        as_of=as_of,
        header=TradeInsightsHeader(
            dominant_bias="NEUTRAL_SHORT_VOL" if candidates else "NEUTRAL",
            primary_setup="TRADE_INSIGHTS_RESEARCH",
            confidence_label="MEDIUM" if contracts and candidates else "LOW",
            data_quality_label="MIXED" if contracts else "INSUFFICIENT",
            idea_count=len(candidates),
            preferred_idea_id=preferred,
            badges=badges,
        ),
        source_reconciliation=source_reconciliation,
        signal_stack=signal_stack,
        flow_table=flow_rows,
        term_structure_table=term_rows,
        candidate_structures=candidates,
        synthesis=InsightsSynthesis(
            dominant_story="Deterministic research-grade ideas built from current chain, flow, and term data."
            if candidates
            else "Insufficient option-chain data for structure generation.",
            preferred_idea_id=preferred,
            best_risk_reward_idea_id=preferred,
            avoid=["Naked short options", "Executable recommendation language"],
            required_before_sizing=[
                "Confirm event calendar through all expiries",
                "Confirm bid/ask width and open interest",
                "Confirm next-day OI for volume > OI flags",
                "Run out-of-sample validation before automation",
            ],
        ),
    )
```

- [x] **Step 3: Run unit tests**

Run:

```bash
uv run pytest tests/test_trade_insights.py -q
```

Expected: all tests pass.

- [x] **Step 4: Commit**

```bash
git add src/uw_scan/reports/trade_insights.py tests/test_trade_insights.py
git commit -m "Assemble deterministic Trade Insights response"
```

### Task 2.3: Add API router and mount it

**Files:**
- Create: `src/uw_scan/api/routers/trade_insights.py`
- Modify: `src/uw_scan/api/server.py`
- Test: `tests/integration/api/test_trade_insights_endpoint.py`

- [x] **Step 1: Add integration test**

Create `tests/integration/api/test_trade_insights_endpoint.py`:

```python
"""Integration tests for GET /api/stock/{ticker}/trade-insights."""

from __future__ import annotations


def test_trade_insights_endpoint_returns_404_without_run(client, seeded_db_empty_cards):
    r = client.get("/api/stock/NOPE/trade-insights")
    assert r.status_code == 404
    assert "no runs" in r.text
```

- [x] **Step 2: Create router**

Create `src/uw_scan/api/routers/trade_insights.py`:

```python
"""Trade Insights endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.models import TradeInsightsResponse
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.reports.trade_insights import (
    ASSEMBLER_VERSION,
    _stable_payload_hash,
    assemble_trade_insights,
)
from uw_scan.storage.repository import Repository

router = APIRouter()


@router.get(
    "/stock/{ticker}/trade-insights",
    response_model=TradeInsightsResponse,
)
def get_trade_insights(
    ticker: str, repo: Repository = Depends(get_repo)
) -> TradeInsightsResponse:
    t = ticker.upper()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {t}")

    report = assemble_single_stock_report(t, run_id, repo)
    response = assemble_trade_insights(
        ticker=t,
        run_id=run_id,
        repo=repo,
        as_of=report.generated_at,
        spot=report.market_structure.spot,
    )
    payload = response.model_dump(mode="json")
    input_hash = _stable_payload_hash(payload)
    snapshot_id = repo.upsert_trade_insight_snapshot(
        run_id=run_id,
        ticker=t,
        as_of=response.as_of,
        assembler_version=ASSEMBLER_VERSION,
        input_hash=input_hash,
        payload=payload,
    )
    repo.replace_trade_insight_candidates(
        snapshot_id=snapshot_id,
        run_id=run_id,
        ticker=t,
        candidates=payload["candidate_structures"],
    )
    repo.conn.commit()
    return response
```

- [x] **Step 3: Mount router**

In `src/uw_scan/api/server.py`, update imports:

```python
from uw_scan.api.routers import health, jobs, ohlc, stock, trade_insights, volatility, watchlist
```

Then add before `return app`:

```python
    app.include_router(trade_insights.router, prefix="/api", tags=["trade-insights"])
```

- [x] **Step 4: Run API test**

Run:

```bash
uv run pytest tests/integration/api/test_trade_insights_endpoint.py -q
```

Expected: pass when `UW_SCAN_TEST_DB_NAME` is configured.

- [x] **Step 5: Commit**

```bash
git add src/uw_scan/api/routers/trade_insights.py src/uw_scan/api/server.py tests/integration/api/test_trade_insights_endpoint.py
git commit -m "Add Trade Insights API endpoint"
```

### Task 2.4: Persist snapshots during scan completion

**Files:**
- Modify: `src/uw_scan/pipeline.py`
- Test: `tests/integration/test_trade_insights_pipeline_persistence.py`

- [x] **Step 1: Add a small persistence helper**

In `src/uw_scan/pipeline.py`, import:

```python
from .reports.trade_insights import (
    ASSEMBLER_VERSION,
    _stable_payload_hash,
    assemble_trade_insights,
)
```

Add a helper near `run_single_stock`:

```python
def _persist_trade_insights_for_run(
    *,
    repo: Repository,
    report: SingleStockReport,
) -> None:
    response = assemble_trade_insights(
        ticker=report.ticker,
        run_id=report.run_id,
        repo=repo,
        as_of=report.generated_at,
        spot=report.market_structure.spot,
    )
    payload = response.model_dump(mode="json")
    snapshot_id = repo.upsert_trade_insight_snapshot(
        run_id=report.run_id,
        ticker=report.ticker,
        as_of=response.as_of,
        assembler_version=ASSEMBLER_VERSION,
        input_hash=_stable_payload_hash(payload),
        payload=payload,
    )
    repo.replace_trade_insight_candidates(
        snapshot_id=snapshot_id,
        run_id=report.run_id,
        ticker=report.ticker,
        candidates=payload["candidate_structures"],
    )
```

- [x] **Step 2: Call the helper before finishing the scan run**

In `run_single_stock`, after the bulk-screener/aggregate update block and before `repo.finish_scan_run(run_id, status="ok")`, call:

```python
        try:
            _persist_trade_insights_for_run(repo=repo, report=report)
        except Exception as exc:  # noqa: BLE001 — research-log only; never block a scan
            logger.warning(
                "trade_insights persistence failed for %s run_id=%s: %s",
                report.ticker,
                report.run_id,
                repr(exc),
            )
```

Rationale: a new derived feature must not break nightly full-scans for illiquid tickers or sparse chains. The GET endpoint still runs the assembler on demand and writes the same idempotent row, so a missed nightly persistence is recoverable by simply opening the tab. Treat the snapshot table as a research log, not a hard contract.

- [x] **Step 3: Keep the endpoint idempotent**

The `GET /api/stock/{ticker}/trade-insights` endpoint should still upsert the same snapshot as a backfill/repair path for older runs or manually seeded test data. The unique `(run_id, ticker, assembler_version, input_hash)` constraint prevents duplicates.

- [x] **Step 4: Add integration coverage**

Create `tests/integration/test_trade_insights_pipeline_persistence.py` or extend an existing pipeline integration test to assert that a successful single-stock run writes:

- one `trade_insight_snapshots` row for the run;
- one or more `trade_insight_candidates` rows when enough chain data exists;
- the same `snapshot_id` after rerunning the endpoint for that run/input hash.

- [x] **Step 5: Commit**

```bash
git add src/uw_scan/pipeline.py tests/integration/test_trade_insights_pipeline_persistence.py
git commit -m "Persist Trade Insights during scan completion"
```

---

## Phase 3 — Frontend API and route integration

### Task 3.1: Regenerate OpenAPI types and add API helper

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/lib/api.ts`

- [x] **Step 1: Start backend in a separate terminal if needed**

Run:

```bash
bash scripts/dev.sh
```

Expected: FastAPI available at `http://127.0.0.1:8400/openapi.json`.

- [x] **Step 2: Regenerate types**

Run:

```bash
cd web
npm run gen:types
```

Expected: `web/lib/types.ts` contains `/api/stock/{ticker}/trade-insights`.

- [x] **Step 3: Add API helper**

In `web/lib/api.ts`, add:

```ts
type TradeInsightsResponse = Json<
  "/api/stock/{ticker}/trade-insights",
  "get"
>;
```

Inside `api`:

```ts
  tradeInsights: (ticker: string): Promise<TradeInsightsResponse> =>
    _fetch<TradeInsightsResponse>(`/api/stock/${ticker}/trade-insights`),
```

And export it:

```ts
export type {
  JobStatus,
  OhlcResponse,
  SingleStockReport,
  TradeInsightsResponse,
  VolatilitySeriesResponse,
  WatchlistResponse,
};
```

- [x] **Step 4: Typecheck**

Run:

```bash
cd web
npm run typecheck
```

Expected: no TypeScript errors.

- [x] **Step 5: Commit**

```bash
git add web/lib/types.ts web/lib/api.ts
git commit -m "Add Trade Insights API client"
```

### Task 3.2: Add the tab route

**Files:**
- Modify: `web/components/stock/TabBar.tsx`
- Modify: `web/app/stock/[ticker]/[tab]/page.tsx`
- Create: `web/components/stock/tabs/TradeInsightsTab.tsx`

- [x] **Step 1: Create placeholder tab**

Create `web/components/stock/tabs/TradeInsightsTab.tsx`:

```tsx
import { api } from "@/lib/api";

export async function TradeInsightsTab({ ticker }: { ticker: string }) {
  const insights = await api.tradeInsights(ticker);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <h3
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          color: "var(--text-muted)",
          letterSpacing: 1,
          textTransform: "uppercase",
        }}
      >
        Trade Insights
      </h3>
      <div
        style={{
          border: "1px solid var(--border-dim)",
          background: "var(--bg-panel)",
          padding: 16,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        {insights.header.primary_setup}
      </div>
    </div>
  );
}
```

- [x] **Step 2: Add tab link**

In `web/components/stock/TabBar.tsx`, update `TABS`:

```ts
const TABS = [
  ["market-structure", "Market Structure"],
  ["volatility", "Volatility"],
  ["flow", "Flow"],
  ["trade-insights", "Trade Insights"],
  ["trade-plan", "Trade Plan"],
] as const;
```

Note: there is no `["tables", "Tables"]` entry — the standalone Tables tab was merged into Flow in commit `e996b5e` (2026-05). Do not re-introduce it.

- [x] **Step 3: Add route switch**

In `web/app/stock/[ticker]/[tab]/page.tsx`, import:

```ts
import { TradeInsightsTab } from "@/components/stock/tabs/TradeInsightsTab";
```

Update the report-backed tab map. Keep `trade-insights` out of this map because it fetches its own endpoint and accepts `{ ticker }`, not `{ report }`. The current `TABS` constant only contains the four report-backed tabs (no `tables` — that tab was removed when Flow + Tables merged):

```ts
const REPORT_TABS = {
  "market-structure": MarketStructureTab,
  volatility: VolatilityTab,
  flow: FlowTab,
  "trade-plan": TradePlanTab,
} as const;
```

Do **not** import `TablesTab` — that component no longer exists.

Update the return:

```tsx
  if (tab === "trade-insights") {
    return <TradeInsightsTab ticker={ticker} />;
  }
  const Component = REPORT_TABS[tab as keyof typeof REPORT_TABS];
  if (!Component) notFound();

  const report = await api.stock(ticker);
  return <Component report={report} />;
```

Loading/error UX: `TradeInsightsTab` is an async server component that hits a fresh endpoint, so a slow or 404 response would otherwise blank the page. Either rely on the surrounding `app/stock/[ticker]/layout.tsx` `loading.tsx`/`error.tsx` boundaries if they already cover the `[tab]` segment, or add minimal `loading.tsx` and `error.tsx` siblings to `app/stock/[ticker]/[tab]/` if not. Confirm before implementation.

- [x] **Step 4: Typecheck**

Run:

```bash
cd web
npm run typecheck
```

Expected: no TypeScript errors.

- [x] **Step 5: Commit**

```bash
git add web/components/stock/TabBar.tsx 'web/app/stock/[ticker]/[tab]/page.tsx' web/components/stock/tabs/TradeInsightsTab.tsx
git commit -m "Add Trade Insights stock tab route"
```

### Task 3.3: Add loading and error boundaries for the stock tab segment

**Files:**
- Create: `web/app/stock/[ticker]/[tab]/loading.tsx`
- Create: `web/app/stock/[ticker]/[tab]/error.tsx`

**Why this task exists.** The Volatility / Flow / Market Structure / Trade Plan tabs survive a slow `api.stock(ticker)` because the parent layout awaits it before paint. Trade Insights adds a second sequential `await api.tradeInsights(ticker)` inside the tab — when that endpoint is slow the user sees the previous tab's content frozen for the full duration. A `loading.tsx` sibling at the `[tab]` segment makes the transition explicit; an `error.tsx` keeps a single failing tab from blanking the rest of the page.

- [x] **Step 1: Create `loading.tsx`**

```tsx
export default function Loading() {
  return (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--text-muted)",
        padding: 16,
      }}
    >
      Loading…
    </div>
  );
}
```

Match the existing empty-state styling (mono 12px, `var(--text-muted)`). Do not add a full skeleton in V1 — the loading state is brief enough that a single line is sufficient and adding skeleton panels per tab is scope creep.

- [x] **Step 2: Create `error.tsx`**

```tsx
"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <div
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--negative)",
        padding: 16,
      }}
    >
      <div>Tab failed to load: {error.message}</div>
      <button
        type="button"
        onClick={reset}
        style={{
          marginTop: 8,
          padding: "4px 8px",
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          color: "var(--text-primary)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          cursor: "pointer",
        }}
      >
        Retry
      </button>
    </div>
  );
}
```

The boundary applies to every tab via the route segment, so all four existing tabs also gain graceful failure. This is intentional — they previously had none.

- [x] **Step 3: Commit**

```bash
git add 'web/app/stock/[ticker]/[tab]/loading.tsx' 'web/app/stock/[ticker]/[tab]/error.tsx'
git commit -m "Add loading and error boundaries for stock tab segment"
```

---

## Phase 4 — Frontend panels

### Task 4.0: Extract shared `InsightPanel` shell

**Files:**
- Create: `web/components/stock/panels/InsightPanel.tsx`

**Why this task exists.** Seven of the eight Trade Insights components share identical panel chrome (border, background, padding, section heading). Volatility v2 already established the precedent of lifting a `AnalyticalSeriesPanel.tsx` shell — without doing the same here, the seven downstream panel files each repeat the same 6-line inline style block. Build the shell first; every later panel just nests its content inside `<InsightPanel heading="…">…</InsightPanel>`.

- [x] **Step 1: Create the shell**

```tsx
import type { ReactNode } from "react";

const sectionHeading: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase",
  marginTop: 4,
};

export function InsightPanel({
  heading,
  subheading,
  children,
  fullBleed = false,
}: {
  heading: string;
  subheading?: string;
  children: ReactNode;
  fullBleed?: boolean;
}) {
  return (
    <section
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: "var(--bg-panel)",
        padding: fullBleed ? 0 : 16,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ padding: fullBleed ? "16px 16px 0" : 0 }}>
        <div style={sectionHeading}>{heading}</div>
        {subheading && (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--text-primary)",
            }}
          >
            {subheading}
          </div>
        )}
      </div>
      <div style={{ padding: fullBleed ? "0 16px 16px" : 0 }}>{children}</div>
    </section>
  );
}

export function InsightStatusBanner({
  text,
  severity = "warning",
}: {
  text: string;
  severity?: "warning" | "negative" | "info";
}) {
  const color =
    severity === "negative"
      ? "var(--negative)"
      : severity === "info"
        ? "var(--text-secondary)"
        : "var(--warning)";
  return (
    <div
      style={{
        padding: 8,
        background: "var(--bg-panel)",
        border: `1px dashed ${color}`,
        borderRadius: 4,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color,
      }}
    >
      {text}
    </div>
  );
}
```

Pattern source: `VolatilityTabClient.tsx` lines 65–88 (the dashed-banner) and 79–88 (the section heading).

- [x] **Step 2: Commit**

```bash
git add web/components/stock/panels/InsightPanel.tsx
git commit -m "Add shared InsightPanel shell for Trade Insights"
```

### Task 4.1: Add bias banner, source reconciliation, and signal stack panels

**Files:**
- Create: `web/components/stock/panels/TradeInsightsBiasBanner.tsx`
- Create: `web/components/stock/panels/SourceReconciliationPanel.tsx`
- Create: `web/components/stock/panels/SignalStackPanel.tsx`
- Modify: `web/components/stock/tabs/TradeInsightsTab.tsx`
- Test: `web/tests/unit/tradeInsightsPanels.test.tsx`

**Why the rename.** `web/app/stock/[ticker]/layout.tsx` already renders `<DetailHeader>` showing the ticker, spot, IV, and setup badge. A second ticker render in the tab body is duplicated UX. The panel's actual job is the bias/setup/confidence/data-quality row plus badges — `TradeInsightsBiasBanner` names that responsibility. Do not accept `ticker` as a prop; do not render the ticker.

- [x] **Step 1: Create panel tests**

Create `web/tests/unit/tradeInsightsPanels.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignalStackPanel } from "@/components/stock/panels/SignalStackPanel";
import { SourceReconciliationPanel } from "@/components/stock/panels/SourceReconciliationPanel";
import { TradeInsightsBiasBanner } from "@/components/stock/panels/TradeInsightsBiasBanner";

describe("TradeInsightsBiasBanner", () => {
  it("renders setup and badges without the ticker", () => {
    render(
      <TradeInsightsBiasBanner
        header={{
          dominant_bias: "NEUTRAL_SHORT_VOL",
          primary_setup: "TRADE_INSIGHTS_RESEARCH",
          confidence_label: "MEDIUM",
          data_quality_label: "MIXED",
          badges: [{ code: "DEFINED_RISK_ONLY", label: "Defined-risk only", severity: "info" }],
        }}
      />,
    );
    // The parent layout's <DetailHeader> already renders the ticker, so the
    // banner intentionally does NOT — assert absence to lock that contract in.
    expect(screen.queryByText("TSLA")).toBeNull();
    expect(screen.getByText("TRADE_INSIGHTS_RESEARCH")).toBeDefined();
    expect(screen.getByText("Defined-risk only")).toBeDefined();
  });
});

describe("SourceReconciliationPanel", () => {
  it("renders source decision", () => {
    render(
      <SourceReconciliationPanel
        reconciliation={{
          status: "UNKNOWN",
          headline: "No external IV source reconciliation stored for this run",
          primary_iv_source: null,
          relative_shape_source: null,
          rows: [],
          decision: "Use chain-derived values for contract math.",
        }}
      />,
    );
    expect(screen.getByText(/chain-derived values/i)).toBeDefined();
  });
});

describe("SignalStackPanel", () => {
  it("renders lens rows", () => {
    render(
      <SignalStackPanel
        rows={[
          {
            lens: "VOL_LEVEL",
            read: "IV_RV_PROXY_AVAILABLE",
            evidence: ["proxy available"],
            conflicts: [],
          },
        ]}
      />,
    );
    expect(screen.getByText("VOL_LEVEL")).toBeDefined();
    expect(screen.getByText("proxy available")).toBeDefined();
  });
});
```

- [x] **Step 2: Implement `TradeInsightsBiasBanner`**

Create `web/components/stock/panels/TradeInsightsBiasBanner.tsx`. Uses the shared `InsightPanel` shell from Task 4.0. No ticker render — that's the parent layout's job.

```tsx
import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Header = TradeInsightsResponse["header"];

const badgeColor = (severity: string | undefined) => {
  if (severity === "warning") return "var(--warning)";
  if (severity === "error") return "var(--negative)";
  return "var(--accent-bg)";
};

export function TradeInsightsBiasBanner({ header }: { header: Header }) {
  return (
    <InsightPanel heading="BIAS · SETUP">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        <div>
          <div style={{ color: "var(--text-primary)", fontSize: 14 }}>
            {header.primary_setup}
          </div>
          <div style={{ color: "var(--text-secondary)" }}>
            {header.dominant_bias}
          </div>
        </div>
        <div style={{ textAlign: "right", color: "var(--text-secondary)" }}>
          <div>Confidence: {header.confidence_label}</div>
          <div>Data quality: {header.data_quality_label}</div>
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {header.badges.map((badge) => (
          <span
            key={badge.code}
            style={{
              border: "1px solid var(--border-dim)",
              color: badgeColor(badge.severity),
              padding: "4px 8px",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
            }}
          >
            {badge.label}
          </span>
        ))}
      </div>
    </InsightPanel>
  );
}
```

- [x] **Step 3: Implement `SourceReconciliationPanel`**

Create `web/components/stock/panels/SourceReconciliationPanel.tsx`:

```tsx
import type { TradeInsightsResponse } from "@/lib/api";
import { DataTable } from "./DataTable";

type Reconciliation = TradeInsightsResponse["source_reconciliation"];

const sectionHeading: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase",
};

export function SourceReconciliationPanel({
  reconciliation,
}: {
  reconciliation: Reconciliation;
}) {
  return (
    <section
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: "var(--bg-panel)",
        padding: 16,
      }}
    >
      <h3 style={sectionHeading}>SOURCE RECONCILIATION</h3>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        <div style={{ color: "var(--text-primary)", marginBottom: 4 }}>
          {reconciliation.headline}
        </div>
        <div style={{ color: "var(--text-secondary)", marginBottom: 12 }}>
          {reconciliation.decision}
        </div>
      </div>
      {reconciliation.rows.length > 0 && (
        <DataTable
          rows={reconciliation.rows}
          columns={[
            { key: "source_pair", label: "Source Pair" },
            { key: "price_agreement", label: "Price" },
            { key: "iv_agreement", label: "IV" },
            { key: "decision", label: "Decision" },
          ]}
        />
      )}
    </section>
  );
}
```

- [x] **Step 4: Implement `SignalStackPanel`**

Create `web/components/stock/panels/SignalStackPanel.tsx`:

```tsx
import type { TradeInsightsResponse } from "@/lib/api";

type Row = TradeInsightsResponse["signal_stack"][number];

const sectionHeading: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase",
};

export function SignalStackPanel({ rows }: { rows: Row[] }) {
  return (
    <section
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: "var(--bg-panel)",
        padding: 16,
      }}
    >
      <h3 style={sectionHeading}>
        SIGNAL STACK
      </h3>
      <div style={{ display: "grid", gap: 10 }}>
        {rows.map((row) => (
          <div key={row.lens} style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 12 }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{row.lens}</div>
            <div>
              <div style={{ fontWeight: 600 }}>{row.read}</div>
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
                {row.evidence.join(" | ")}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [x] **Step 5: Compose panels in tab**

Update `web/components/stock/tabs/TradeInsightsTab.tsx`:

```tsx
import { api } from "@/lib/api";
import { SignalStackPanel } from "../panels/SignalStackPanel";
import { SourceReconciliationPanel } from "../panels/SourceReconciliationPanel";
import { TradeInsightsBiasBanner } from "../panels/TradeInsightsBiasBanner";

export async function TradeInsightsTab({ ticker }: { ticker: string }) {
  const insights = await api.tradeInsights(ticker);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <TradeInsightsBiasBanner header={insights.header} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <SourceReconciliationPanel reconciliation={insights.source_reconciliation} />
        <SignalStackPanel rows={insights.signal_stack} />
      </div>
    </div>
  );
}
```

Layout pattern source: `VolatilityTabClient.tsx` lines 95+ (`gridTemplateColumns: "1fr 1fr"` for paired panels). Task 4.2 expands this with another paired row (flow + term) and two full-width rows (candidates, synthesis).

- [x] **Step 6: Run frontend tests**

Run:

```bash
cd web
npm run test -- tradeInsightsPanels.test.tsx
```

Expected: tests pass.

- [x] **Step 7: Commit**

```bash
git add web/components/stock/panels/TradeInsightsBiasBanner.tsx web/components/stock/panels/SourceReconciliationPanel.tsx web/components/stock/panels/SignalStackPanel.tsx web/components/stock/tabs/TradeInsightsTab.tsx web/tests/unit/tradeInsightsPanels.test.tsx
git commit -m "Add Trade Insights header and signal panels"
```

### Task 4.2: Add flow, term, candidate, and synthesis panels

**Files:**
- Create: `web/components/stock/panels/ChainFlowReadPanel.tsx`
- Create: `web/components/stock/panels/TermMovePanel.tsx`
- Create: `web/components/stock/panels/CandidateStructuresPanel.tsx`
- Create: `web/components/stock/panels/InsightsSynthesisPanel.tsx`
- Modify: `web/components/stock/tabs/TradeInsightsTab.tsx`
- Test: `web/tests/unit/tradeInsightsPanels.test.tsx`

- [x] **Step 1: Add panel tests**

Append tests:

```tsx
import { CandidateStructuresPanel } from "@/components/stock/panels/CandidateStructuresPanel";
import { ChainFlowReadPanel } from "@/components/stock/panels/ChainFlowReadPanel";
import { InsightsSynthesisPanel } from "@/components/stock/panels/InsightsSynthesisPanel";
import { TermMovePanel } from "@/components/stock/panels/TermMovePanel";

describe("Trade Insights detail panels", () => {
  it("renders flow table T+1 caveat", () => {
    render(
      <ChainFlowReadPanel
        rows={[
          {
            strike: "430",
            call_volume: 1500,
            call_open_interest: 1000,
            put_volume: 600,
            put_open_interest: 700,
            call_put_volume_ratio: "2.5",
            volume_oi_note: "Volume > OI; confirm with next-day OI",
            read: "Call demand concentrated",
            requires_t1_oi_confirmation: true,
          },
        ]}
      />,
    );
    expect(screen.getByText(/next-day OI/i)).toBeDefined();
  });

  it("renders term move rows", () => {
    render(
      <TermMovePanel
        rows={[
          {
            expiry: "2026-05-15",
            dte: 4,
            atm_straddle: null,
            implied_move_perc: "0.048",
            daily_implied_move_perc: "0.012",
            read: "Front elevated",
          },
        ]}
      />,
    );
    expect(screen.getByText("2026-05-15")).toBeDefined();
    expect(screen.getByText("Front elevated")).toBeDefined();
  });

  it("renders candidate max loss", () => {
    render(
      <CandidateStructuresPanel
        candidates={[
          {
            idea_id: "A",
            structure: "call_credit_spread",
            thesis: "Defined-risk short-call premium candidate.",
            expression_type: "SHORT_VOL",
            legs: [],
            net_credit_debit: "1.25",
            max_profit: "1.25",
            max_loss: "3.75",
            breakevens: [],
            profit_zone: "Underlying below 430",
            edge_source: "IV-RV spread / theta",
            risk_flags: ["bullish_flow_can_break_call_side"],
            rank: 1,
            status: "candidate",
          },
        ]}
      />,
    );
    expect(screen.getByText(/Max loss/i)).toBeDefined();
    expect(screen.getByText("$3.75")).toBeDefined();
  });

  it("renders synthesis required checks", () => {
    render(
      <InsightsSynthesisPanel
        synthesis={{
          dominant_story: "Research-grade ideas built from current chain.",
          preferred_idea_id: "A",
          best_risk_reward_idea_id: "A",
          avoid: ["Naked short options"],
          required_before_sizing: ["Confirm event calendar"],
        }}
      />,
    );
    expect(screen.getByText(/Confirm event calendar/)).toBeDefined();
  });
});
```

- [x] **Step 2: Implement panels**

Use compact table/card components with inline styles matching the existing panel pattern. Prefer importing and reusing `DataTable` for `ChainFlowReadPanel` and `TermMovePanel`, because this keeps spacing, text, and borders aligned with the `Tables` and `Trade Plan` tabs. Each panel should accept the exact typed slice from `TradeInsightsResponse`. Ensure empty arrays render a clear empty state:

Empty states should use the shared dashed banner from `InsightPanel.tsx` instead of an ad-hoc div, so they look identical to Volatility v2's "Building 1-year history…" notice:

```tsx
import { InsightStatusBanner } from "./InsightPanel";

// Inside any panel where the input is empty:
if (rows.length === 0) {
  return (
    <InsightPanel heading="CHAIN / FLOW READ">
      <InsightStatusBanner text="No option chain rows for this run" severity="info" />
    </InsightPanel>
  );
}
```

Specific styling requirements:

- Panel shell: use `<InsightPanel heading="…">` from Task 4.0 — do NOT re-inline `border / borderRadius / background / padding`. The shell already supplies them.
- Tables: use `DataTable` and its column renderers for money/percent formatting.
- Candidate cards: `display: grid`, compact `gap: 8`, same border/background as the panel shell, but **do not nest `InsightPanel` inside `InsightPanel`** (would double-border). Cards use the plain `<section>` styling inline.
- Risk flags: small mono chips using `var(--warning)` or `var(--negative)`.
- Required checks: compact bullet list in mono 12px, same as `TradePlanTab` confirmations/warnings.
- Empty-state strings (`InsightStatusBanner` text): `"No option chain rows for this run"`, `"No iv_term_snapshots for this run"`, `"No candidate structures generated"`, `"No source reconciliation data"`. Match phrasing across panels.

- [x] **Step 3: Compose all panels in a 2-column grid where natural**

Update `TradeInsightsTab.tsx` so the layout matches the density of `VolatilityTabClient.tsx` (2-col grid for paired panels, full-width for the synthesis row):

```tsx
import { CandidateStructuresPanel } from "../panels/CandidateStructuresPanel";
import { ChainFlowReadPanel } from "../panels/ChainFlowReadPanel";
import { InsightsSynthesisPanel } from "../panels/InsightsSynthesisPanel";
import { TermMovePanel } from "../panels/TermMovePanel";

// Final composed return:
return (
  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <TradeInsightsBiasBanner header={insights.header} />
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <SourceReconciliationPanel reconciliation={insights.source_reconciliation} />
      <SignalStackPanel rows={insights.signal_stack} />
    </div>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <ChainFlowReadPanel rows={insights.flow_table} />
      <TermMovePanel rows={insights.term_structure_table} />
    </div>
    <CandidateStructuresPanel candidates={insights.candidate_structures} />
    <InsightsSynthesisPanel synthesis={insights.synthesis} />
  </div>
);
```

Rationale: source reconciliation and signal stack are both short evidence-summary panels — pairing them avoids dead horizontal space. Flow table and term table both render tabular data of similar height — pairing them creates symmetry. Candidate cards and synthesis are wide content that benefits from the full viewport.

- [x] **Step 4: Run frontend tests and typecheck**

Run:

```bash
cd web
npm run test -- tradeInsightsPanels.test.tsx
npm run typecheck
```

Expected: both pass.

- [x] **Step 5: Commit**

```bash
git add web/components/stock/panels/ChainFlowReadPanel.tsx web/components/stock/panels/TermMovePanel.tsx web/components/stock/panels/CandidateStructuresPanel.tsx web/components/stock/panels/InsightsSynthesisPanel.tsx web/components/stock/tabs/TradeInsightsTab.tsx web/tests/unit/tradeInsightsPanels.test.tsx
git commit -m "Render Trade Insights detail panels"
```

---

## Phase 5 — Validation and follow-up docs

### Task 5.1: Full backend and frontend verification

**Files:**
- No source edits unless tests expose a defect.

- [x] **Step 1: Run backend focused tests**

Run:

```bash
uv run pytest tests/test_trade_insights.py tests/integration/api/test_trade_insights_endpoint.py -q
```

Expected: all pass.

- [x] **Step 2: Run frontend focused tests**

Run:

```bash
cd web
npm run test -- tradeInsightsPanels.test.tsx
npm run typecheck
```

Expected: all pass.

- [x] **Step 3: Run whitespace check**

Run:

```bash
git diff --check HEAD
```

Expected: no output.

- [x] **Step 4: Commit any verification fixes**

If fixes were needed:

```bash
git add <changed-files>
git commit -m "Fix Trade Insights verification issues"
```

If no fixes were needed, record in the implementation handoff that verification passed with no changes.

### Task 5.2: Optional V1.5 Codex analysis plan

**Files:**
- Create: `docs/superpowers/plans/2026-05-13-trade-insights-codex-analysis.md`

- [x] **Step 1: Create a separate V1.5 plan only after V1 is passing**

Write a follow-up plan that covers:

- migration for `trade_insight_ai_analyses`;
- fixed prompt template;
- allowlisted `codex exec` wrapper;
- worker job and timeout;
- UI button and polling;
- artifact rendering;
- tests for failure fallback.

- [x] **Step 2: Keep V1.5 out of the V1 code path**

Do not add the button or Codex job in this implementation branch unless the user explicitly expands scope after V1 passes.

---

## Self-review

### Spec coverage

- `Trade Insights` naming: covered by tab route and UI labels in Tasks 3.2 and 4.x.
- Research-grade boundary: covered by backend status strings, UI guardrails, and no order controls.
- Source reconciliation: covered by response model, deterministic assembler default, and `SourceReconciliationPanel`.
- Deterministic signal stack: covered by Task 2.2 and Task 4.1.
- Chain/flow read with T+1 OI caveat: covered by Task 2.2 and Task 4.2.
- Term structure / implied move rows: covered by Task 2.2 and Task 4.2, including ATM straddle computed from chain mids when available.
- Candidate structures with max loss: covered by Task 2.2 and Task 4.2 for call credit spread, put credit spread, iron condor, long straddle, and calendar spread.
- Preferred status gate: covered by Task 2.2; missing event/source/liquidity checks force `needs_check` and keep `preferred_idea_id` null.
- Contract normalization: covered by Task 1.2 parser and backend-normalized response legs.
- Optional Codex support: explicitly deferred into Task 5.2 as V1.5.

### Execution notes

- Start execution in an isolated worktree if the current tree contains unrelated Volatility v2 edits.
- Do not commit `.serena/` unless the user explicitly wants project-local Serena metadata tracked.
- Keep V1 deterministic; AI commentary is not part of this plan's implemented scope.

### Known V1 limitations (carried intentionally)

- `event_data_known` is hardcoded `False` in `assemble_trade_insights`. Every candidate gets `status="needs_check"` and `preferred_idea_id` stays `None`. The earnings/dividend plumbing exists upstream but is not wired into this assembler in V1 — schedule a V1.1 follow-up to read `SingleStockReport.next_earnings_date` and `flow_events.next_earnings_date` and unblock the `preferred` gate.
- `InsightSignalRow.conflicts` is declared in the model but the V1 assembler emits empty arrays. Reserved for V1.1 (bullish-flow-vs-short-call surfacing per spec §4.3). Leaving the field shape stable now avoids a breaking response change later.
- `data_quality_label` only emits `MIXED` or `INSUFFICIENT` in V1. `READY` is reserved for the same V1.1 patch that wires event/source/liquidity gates end-to-end.
- Pipeline persistence is best-effort (logged warning on failure, see Task 2.4 Step 2). The GET endpoint is the authoritative path — it always assembles fresh and upserts idempotently.
- `liquidity_ready` is a math-completeness check (`all(c.max_loss is not None)`), not a true liquidity gate. The spec §9 calls for suppressing structures when the chain is stale or illiquid (wide NBBO, low OI/volume). V1 does not implement bid/ask-width or OI/volume thresholds before candidate generation — every fillable strike pair produces a candidate. A V1.1 patch should add a `_passes_liquidity_gate(contract)` check (suggested initial thresholds: `(ask - bid) / mid <= 0.10` and `open_interest >= 100`) and skip non-passing strikes before the candidate loop.
- Calendar-spread candidate is skipped when the front leg is more expensive than the back (backwardation → credit calendar). The math in V1 only handles the debit-calendar case correctly; credit-calendar P&L requires different bounds.
- **No expiry / strike-range selectors** on the Chain Flow Read panel. `FlowTab.tsx` exposes `EXPIRIES: [N selected ▾]` and `STRIKE RANGE: [±30% ▾]` controls above its strike tables; Trade Insights V1 renders every strike row from `flow_table`. For very liquid names this can produce a 30-row table. A V1.1 patch should adopt the Flow filter shape so users can scope the chain view.
