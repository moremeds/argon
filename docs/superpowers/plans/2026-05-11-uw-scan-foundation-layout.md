# UW Scan Foundation And First Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working Streamlit layout shell, typed view-model layer, fixture data, request-budget planner, TradingView parser spike, and database migration foundation for the Unusual Whales opportunity scanner.

**Architecture:** This first plan intentionally avoids live UW ingestion and live database writes until the integration boundaries are proven. It creates a fixture-backed Streamlit UI that consumes typed view models, a deterministic request-budget planner, a TradingView shared-watchlist parser contract, and SQL migrations that define the `uw_scan` schema grains.

**Tech Stack:** Python 3.11+, Streamlit, pandas, pydantic, httpx, pytest, psycopg optional for later database integration, Postgres SQL migrations.

---

## Scope Boundary

This plan implements Phase 1 from the design spec and the validation pieces needed before Phase 2:

- Creates the repo package scaffold.
- Adds `.env.example` without secrets.
- Defines typed view models and fixtures.
- Adds a first Streamlit layout using fixtures only.
- Adds a request-budget planner and tests.
- Adds a TradingView parser contract and tests with fixtures.
- Adds SQL migration files for `option_wizard.uw_scan` schema foundation.
- Adds tests that inspect migration content and core schema grains.

This plan does not use the provided Unusual Whales token directly and does not commit it. Live UW API calls come in a later plan after the client and audit path are implemented.

## File Structure

- Create: `.gitignore`  
  Keeps `.env`, caches, virtualenvs, and Streamlit local state out of git.

- Create: `.env.example`  
  Documents runtime config with sample keys only.

- Create: `pyproject.toml`  
  Defines package metadata, dependencies, pytest config, and formatting defaults.

- Create: `README.md`  
  Gives local setup and first layout run commands.

- Create: `app/streamlit_app.py`  
  Streamlit entrypoint. It imports typed fixture view models and renders tabs.

- Create: `src/uw_scan/__init__.py`  
  Package marker and version string.

- Create: `src/uw_scan/config.py`  
  Environment-backed config object with request caps and DB settings.

- Create: `src/uw_scan/models.py`  
  Pydantic view/domain models for source rows, opportunities, tracked items, surface rows, snapshots, and request budget summaries.

- Create: `src/uw_scan/fixtures.py`  
  Deterministic fixture view model used by Streamlit and tests.

- Create: `src/uw_scan/request_budget.py`  
  Pure request-budget estimator and cap enforcement.

- Create: `src/uw_scan/sources/tradingview.py`  
  Shared-watchlist parser contract. Static HTML parsing succeeds only when symbols are exposed in embedded JSON or text fixtures; otherwise returns a nonblocking failure result.

- Create: `src/uw_scan/sources/__init__.py`  
  Source package marker.

- Create: `src/uw_scan/storage/migrations/001_create_uw_scan_schema.sql`  
  Idempotent schema migration with schema versioning and foundation tables.

- Create: `src/uw_scan/storage/__init__.py`  
  Storage package marker.

- Create: `tests/test_config.py`  
  Config defaults and environment override tests.

- Create: `tests/test_fixtures.py`  
  Fixture shape tests.

- Create: `tests/test_request_budget.py`  
  Request-budget and cap-enforcement tests.

- Create: `tests/test_tradingview_parser.py`  
  TradingView parser contract tests.

- Create: `tests/test_migration_sql.py`  
  SQL migration content tests for schema, raw payload storage, and uniqueness grains.

- Create: `tests/test_streamlit_smoke.py`  
  Import-level smoke test for the Streamlit app module.

## Task 1: Project Scaffold And Config

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/uw_scan/__init__.py`
- Create: `src/uw_scan/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_config.py`:

```python
import os

from uw_scan.config import UwScanConfig


def test_config_defaults_do_not_contain_secret_token(monkeypatch):
    monkeypatch.delenv("UW_SCAN_API_KEY", raising=False)

    config = UwScanConfig.from_env()

    assert config.api_key is None
    assert config.db_name == "option_wizard"
    assert config.db_schema == "uw_scan"
    assert config.max_requests_per_cycle == 250
    assert config.max_deep_surface_tickers == 8


def test_config_reads_environment_overrides(monkeypatch):
    monkeypatch.setenv("UW_SCAN_API_KEY", "runtime-token")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_PORT", "5544")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard")
    monkeypatch.setenv("UW_SCAN_DB_USER", "moremeds")
    monkeypatch.setenv("UW_SCAN_DB_PASSWORD", "secret")
    monkeypatch.setenv("UW_SCAN_POLL_SECONDS", "45")
    monkeypatch.setenv("UW_SCAN_MAX_REQUESTS_PER_CYCLE", "120")

    config = UwScanConfig.from_env()

    assert config.api_key == "runtime-token"
    assert config.db_host == "127.0.0.1"
    assert config.db_port == 5544
    assert config.db_user == "moremeds"
    assert config.db_password == "secret"
    assert config.poll_seconds == 45
    assert config.max_requests_per_cycle == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan'`.

- [ ] **Step 3: Create project metadata and ignore files**

Create `.gitignore`:

```gitignore
.DS_Store
.env
.env.*
!.env.example
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/
.streamlit/secrets.toml
.superpowers/
```

Create `.env.example`:

```bash
UW_SCAN_API_KEY=
UW_SCAN_DB_HOST=127.0.0.1
UW_SCAN_DB_PORT=5432
UW_SCAN_DB_NAME=option_wizard
UW_SCAN_DB_SCHEMA=uw_scan
UW_SCAN_DB_USER=
UW_SCAN_DB_PASSWORD=
UW_SCAN_POLL_SECONDS=60
UW_SCAN_MAX_REQUESTS_PER_CYCLE=250
UW_SCAN_MAX_FLOW_ROWS=100
UW_SCAN_MAX_TV_SYMBOLS_PER_SOURCE=200
UW_SCAN_MAX_WATCHLIST_TICKERS=50
UW_SCAN_MAX_DEEP_SURFACE_TICKERS=8
UW_SCAN_MAX_EXPIRIES_PER_TICKER=4
UW_SCAN_MAX_OPTION_CONTRACT_PAGES=2
```

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "uw-scan"
version = "0.1.0"
description = "Streamlit opportunity scanner for Unusual Whales data"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "pandas>=2.2",
  "pydantic>=2.7",
  "streamlit>=1.35",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
]
postgres = [
  "psycopg[binary]>=3.2",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Create `README.md`:

```markdown
# Unusual Whales Opportunity Scanner

Streamlit dashboard for spotting and tracking options opportunities from Unusual Whales data and TradingView shared watchlists.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,postgres]"
cp .env.example .env
```

Put the real Unusual Whales token in `.env` as `UW_SCAN_API_KEY`. Do not commit `.env`.

## First Layout

```bash
streamlit run app/streamlit_app.py
```

The first layout uses fixture data only. Live UW polling is added in a later phase.
```

- [ ] **Step 4: Create package config implementation**

Create `src/uw_scan/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/uw_scan/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class UwScanConfig:
    api_key: str | None = None
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "option_wizard"
    db_schema: str = "uw_scan"
    db_user: str = ""
    db_password: str = ""
    poll_seconds: int = 60
    max_requests_per_cycle: int = 250
    max_flow_rows: int = 100
    max_tv_symbols_per_source: int = 200
    max_watchlist_tickers: int = 50
    max_deep_surface_tickers: int = 8
    max_expiries_per_ticker: int = 4
    max_option_contract_pages: int = 2

    @classmethod
    def from_env(cls) -> "UwScanConfig":
        return cls(
            api_key=os.environ.get("UW_SCAN_API_KEY") or None,
            db_host=os.environ.get("UW_SCAN_DB_HOST", cls.db_host),
            db_port=_int_env("UW_SCAN_DB_PORT", cls.db_port),
            db_name=os.environ.get("UW_SCAN_DB_NAME", cls.db_name),
            db_schema=os.environ.get("UW_SCAN_DB_SCHEMA", cls.db_schema),
            db_user=os.environ.get("UW_SCAN_DB_USER", cls.db_user),
            db_password=os.environ.get("UW_SCAN_DB_PASSWORD", cls.db_password),
            poll_seconds=_int_env("UW_SCAN_POLL_SECONDS", cls.poll_seconds),
            max_requests_per_cycle=_int_env("UW_SCAN_MAX_REQUESTS_PER_CYCLE", cls.max_requests_per_cycle),
            max_flow_rows=_int_env("UW_SCAN_MAX_FLOW_ROWS", cls.max_flow_rows),
            max_tv_symbols_per_source=_int_env("UW_SCAN_MAX_TV_SYMBOLS_PER_SOURCE", cls.max_tv_symbols_per_source),
            max_watchlist_tickers=_int_env("UW_SCAN_MAX_WATCHLIST_TICKERS", cls.max_watchlist_tickers),
            max_deep_surface_tickers=_int_env("UW_SCAN_MAX_DEEP_SURFACE_TICKERS", cls.max_deep_surface_tickers),
            max_expiries_per_ticker=_int_env("UW_SCAN_MAX_EXPIRIES_PER_TICKER", cls.max_expiries_per_ticker),
            max_option_contract_pages=_int_env("UW_SCAN_MAX_OPTION_CONTRACT_PAGES", cls.max_option_contract_pages),
        )
```

- [ ] **Step 5: Run config tests**

Run:

```bash
pytest tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit scaffold**

```bash
git add .gitignore .env.example pyproject.toml README.md src/uw_scan/__init__.py src/uw_scan/config.py tests/test_config.py
git commit -m "Add UW scan project scaffold"
```

## Task 2: Typed View Models And Fixtures

**Files:**
- Create: `src/uw_scan/models.py`
- Create: `src/uw_scan/fixtures.py`
- Test: `tests/test_fixtures.py`

- [ ] **Step 1: Write fixture tests**

Create `tests/test_fixtures.py`:

```python
from uw_scan.fixtures import demo_dashboard


def test_demo_dashboard_has_expected_tabs_data():
    dashboard = demo_dashboard()

    assert len(dashboard.opportunities) >= 2
    assert len(dashboard.flow_rows) >= 2
    assert len(dashboard.watchlist_sources) >= 1
    assert len(dashboard.tracked_items) >= 1
    assert dashboard.request_budget.total_estimated_requests > 0


def test_opportunity_fixture_contains_structure_without_sizing():
    dashboard = demo_dashboard()
    first = dashboard.opportunities[0]

    assert first.structure_idea is not None
    assert first.structure_idea.max_risk_note == "Sizing deferred"
    assert first.score >= 0
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_fixtures.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing `uw_scan.fixtures`.

- [ ] **Step 3: Implement view models**

Create `src/uw_scan/models.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class SourceKind(str, Enum):
    UW_FLOW = "uw_flow"
    TRADINGVIEW = "tradingview"
    MANUAL = "manual"


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SourceFeed(BaseModel):
    label: str
    kind: SourceKind
    url: HttpUrl | None = None
    enabled: bool = True
    status: str = "ready"


class FlowRow(BaseModel):
    ticker: str
    option_symbol: str
    expiry: date
    strike: Decimal
    option_type: str
    premium: Decimal
    volume: int
    open_interest: int | None
    side: str
    dte: int
    source_label: str


class StructureIdea(BaseModel):
    structure_type: str
    rationale: str
    invalidation: str
    max_risk_note: str = "Sizing deferred"


class Opportunity(BaseModel):
    ticker: str
    contract_label: str
    direction: SignalDirection
    score: int = Field(ge=0, le=5)
    setup_types: list[str]
    confirmations: list[str]
    warnings: list[str]
    source_labels: list[str]
    structure_idea: StructureIdea | None = None


class WatchlistSourceView(BaseModel):
    source: SourceFeed
    imported_symbols: list[str]
    failed_symbols: list[str] = Field(default_factory=list)
    parsed_at_utc: datetime


class TrackedItem(BaseModel):
    label: str
    ticker: str
    option_symbol: str | None
    expiry: date | None
    tracking_kind: str
    reconciliation_status: str
    iv_change: Decimal | None = None
    oi_change: int | None = None


class SurfaceMetric(BaseModel):
    ticker: str
    expiry: date
    strike: Decimal
    call_iv: Decimal | None
    put_iv: Decimal | None
    gamma_exposure: Decimal | None
    delta_exposure: Decimal | None
    vanna_exposure: Decimal | None
    charm_exposure: Decimal | None


class SnapshotSummary(BaseModel):
    run_id: str
    mode: str
    started_at_utc: datetime
    source_count: int
    opportunity_count: int


class RequestBudgetSummary(BaseModel):
    flow_rows: int
    watchlist_symbols: int
    estimated_discovery_requests: int
    estimated_enrichment_requests: int
    estimated_deep_surface_requests: int
    total_estimated_requests: int
    max_requests_per_cycle: int
    capped: bool


class DashboardViewModel(BaseModel):
    generated_at_utc: datetime
    opportunities: list[Opportunity]
    flow_rows: list[FlowRow]
    watchlist_sources: list[WatchlistSourceView]
    tracked_items: list[TrackedItem]
    surface_metrics: list[SurfaceMetric]
    snapshots: list[SnapshotSummary]
    request_budget: RequestBudgetSummary


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
```

- [ ] **Step 4: Implement deterministic fixtures**

Create `src/uw_scan/fixtures.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from .models import (
    DashboardViewModel,
    FlowRow,
    Opportunity,
    RequestBudgetSummary,
    SignalDirection,
    SnapshotSummary,
    SourceFeed,
    SourceKind,
    StructureIdea,
    SurfaceMetric,
    TrackedItem,
    WatchlistSourceView,
)


def demo_dashboard() -> DashboardViewModel:
    generated_at = datetime(2026, 5, 11, 13, 30, tzinfo=timezone.utc)
    tv_source = SourceFeed(
        label="portfolio(update daily)",
        kind=SourceKind.TRADINGVIEW,
        url="https://www.tradingview.com/watchlists/326877343/",
        enabled=True,
        status="sample static page needs parser spike",
    )
    uw_source = SourceFeed(label="UW Flow Poll", kind=SourceKind.UW_FLOW, enabled=True)

    return DashboardViewModel(
        generated_at_utc=generated_at,
        opportunities=[
            Opportunity(
                ticker="NVDA",
                contract_label="NVDA 2026-06-19 650C",
                direction=SignalDirection.BULLISH,
                score=5,
                setup_types=["Deep Conviction Directional", "Multi-Signal Confluence"],
                confirmations=["Ask-side premium", "Volume > OI", "IV rising"],
                warnings=["Next-session OI pending"],
                source_labels=[uw_source.label],
                structure_idea=StructureIdea(
                    structure_type="Call debit spread candidate",
                    rationale="Bullish ask-side flow with high conviction and IV expansion.",
                    invalidation="Downgrade if next-session OI does not confirm or skew turns strongly bearish.",
                ),
            ),
            Opportunity(
                ticker="AMD",
                contract_label="AMD important expiries",
                direction=SignalDirection.BULLISH,
                score=4,
                setup_types=["Watchlist Confluence", "OI Buildup"],
                confirmations=["TradingView source", "Call OI building", "Max pain below spot"],
                warnings=["Needs live UW refresh"],
                source_labels=[tv_source.label],
                structure_idea=StructureIdea(
                    structure_type="Call spread watch",
                    rationale="Watchlist name with call-side concentration near important tenor.",
                    invalidation="Avoid if liquidity is thin or OI build reverses.",
                ),
            ),
        ],
        flow_rows=[
            FlowRow(
                ticker="NVDA",
                option_symbol="NVDA260619C00650000",
                expiry=date(2026, 6, 19),
                strike=Decimal("650"),
                option_type="call",
                premium=Decimal("1250000"),
                volume=2400,
                open_interest=900,
                side="ask",
                dte=39,
                source_label=uw_source.label,
            ),
            FlowRow(
                ticker="TSLA",
                option_symbol="TSLA260619P00180000",
                expiry=date(2026, 6, 19),
                strike=Decimal("180"),
                option_type="put",
                premium=Decimal("820000"),
                volume=1800,
                open_interest=620,
                side="ask",
                dte=39,
                source_label=uw_source.label,
            ),
        ],
        watchlist_sources=[
            WatchlistSourceView(
                source=tv_source,
                imported_symbols=["AMD", "NVDA", "TSLA"],
                failed_symbols=[],
                parsed_at_utc=generated_at,
            )
        ],
        tracked_items=[
            TrackedItem(
                label="NVDA 650C Jun19",
                ticker="NVDA",
                option_symbol="NVDA260619C00650000",
                expiry=date(2026, 6, 19),
                tracking_kind="contract",
                reconciliation_status="next OI pending",
                iv_change=Decimal("0.035"),
                oi_change=None,
            )
        ],
        surface_metrics=[
            SurfaceMetric(
                ticker="NVDA",
                expiry=date(2026, 6, 19),
                strike=Decimal("650"),
                call_iv=Decimal("0.54"),
                put_iv=Decimal("0.58"),
                gamma_exposure=Decimal("1250000"),
                delta_exposure=Decimal("4800000"),
                vanna_exposure=Decimal("220000"),
                charm_exposure=Decimal("-180000"),
            )
        ],
        snapshots=[
            SnapshotSummary(
                run_id="fixture-20260511-1330",
                mode="fixture",
                started_at_utc=generated_at,
                source_count=2,
                opportunity_count=2,
            )
        ],
        request_budget=RequestBudgetSummary(
            flow_rows=100,
            watchlist_symbols=3,
            estimated_discovery_requests=2,
            estimated_enrichment_requests=18,
            estimated_deep_surface_requests=8,
            total_estimated_requests=28,
            max_requests_per_cycle=250,
            capped=False,
        ),
    )
```

- [ ] **Step 5: Run fixture tests**

Run:

```bash
pytest tests/test_fixtures.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit view models and fixtures**

```bash
git add src/uw_scan/models.py src/uw_scan/fixtures.py tests/test_fixtures.py
git commit -m "Add dashboard view models and fixtures"
```

## Task 3: Request Budget Planner

**Files:**
- Create: `src/uw_scan/request_budget.py`
- Test: `tests/test_request_budget.py`

- [ ] **Step 1: Write request-budget tests**

Create `tests/test_request_budget.py`:

```python
from uw_scan.config import UwScanConfig
from uw_scan.request_budget import estimate_request_budget


def test_request_budget_estimates_normal_run_under_cap():
    config = UwScanConfig(max_requests_per_cycle=250)

    budget = estimate_request_budget(
        flow_rows=50,
        watchlist_symbols=20,
        deep_surface_tickers=3,
        important_expiries_per_ticker=2,
        config=config,
    )

    assert budget.total_estimated_requests <= 250
    assert budget.capped is False
    assert budget.estimated_discovery_requests == 2


def test_request_budget_caps_large_run():
    config = UwScanConfig(max_requests_per_cycle=60)

    budget = estimate_request_budget(
        flow_rows=100,
        watchlist_symbols=200,
        deep_surface_tickers=8,
        important_expiries_per_ticker=4,
        config=config,
    )

    assert budget.total_estimated_requests == 60
    assert budget.capped is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_request_budget.py -v
```

Expected: FAIL with missing `uw_scan.request_budget`.

- [ ] **Step 3: Implement request-budget estimator**

Create `src/uw_scan/request_budget.py`:

```python
from __future__ import annotations

from .config import UwScanConfig
from .models import RequestBudgetSummary


def estimate_request_budget(
    *,
    flow_rows: int,
    watchlist_symbols: int,
    deep_surface_tickers: int,
    important_expiries_per_ticker: int,
    config: UwScanConfig,
) -> RequestBudgetSummary:
    capped_flow_rows = min(flow_rows, config.max_flow_rows)
    capped_watchlist_symbols = min(watchlist_symbols, config.max_watchlist_tickers)
    capped_deep_tickers = min(deep_surface_tickers, config.max_deep_surface_tickers)
    capped_expiries = min(important_expiries_per_ticker, config.max_expiries_per_ticker)

    discovery = 2
    enrichment = capped_watchlist_symbols * 4
    exact_contract_refresh = max(1, capped_flow_rows // 25)
    deep_surface = capped_deep_tickers * (1 + capped_expiries * 2)

    raw_total = discovery + enrichment + exact_contract_refresh + deep_surface
    total = min(raw_total, config.max_requests_per_cycle)

    return RequestBudgetSummary(
        flow_rows=capped_flow_rows,
        watchlist_symbols=capped_watchlist_symbols,
        estimated_discovery_requests=discovery,
        estimated_enrichment_requests=enrichment + exact_contract_refresh,
        estimated_deep_surface_requests=deep_surface,
        total_estimated_requests=total,
        max_requests_per_cycle=config.max_requests_per_cycle,
        capped=raw_total > config.max_requests_per_cycle,
    )
```

- [ ] **Step 4: Run request-budget tests**

Run:

```bash
pytest tests/test_request_budget.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit request-budget planner**

```bash
git add src/uw_scan/request_budget.py tests/test_request_budget.py
git commit -m "Add request budget planner"
```

## Task 4: TradingView Shared Watchlist Parser Spike

**Files:**
- Create: `src/uw_scan/sources/__init__.py`
- Create: `src/uw_scan/sources/tradingview.py`
- Test: `tests/test_tradingview_parser.py`

- [ ] **Step 1: Write TradingView parser tests**

Create `tests/test_tradingview_parser.py`:

```python
from uw_scan.sources.tradingview import parse_tradingview_watchlist_html


def test_parse_embedded_symbols_from_fixture_html():
    html = """
    <html>
      <head><title>portfolio(update daily) — TradingView</title></head>
      <body>
        <script id="watchlist-data" type="application/json">
          {"symbols":["NASDAQ:NVDA","NASDAQ:AMD","NYSE:TSLA"]}
        </script>
      </body>
    </html>
    """

    result = parse_tradingview_watchlist_html(
        html,
        source_url="https://www.tradingview.com/watchlists/326877343/",
    )

    assert result.source_label == "portfolio(update daily)"
    assert result.symbols == ["NVDA", "AMD", "TSLA"]
    assert result.status == "ok"


def test_parse_static_page_without_symbols_returns_nonblocking_failure():
    html = "<html><head><title>portfolio(update daily) — TradingView</title></head><body>No symbols here</body></html>"

    result = parse_tradingview_watchlist_html(
        html,
        source_url="https://www.tradingview.com/watchlists/326877343/",
    )

    assert result.source_label == "portfolio(update daily)"
    assert result.symbols == []
    assert result.status == "no_symbols_found"
    assert "browser-rendered retrieval" in result.message
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_tradingview_parser.py -v
```

Expected: FAIL with missing source module.

- [ ] **Step 3: Implement parser contract**

Create `src/uw_scan/sources/__init__.py`:

```python
"""External source adapters."""
```

Create `src/uw_scan/sources/tradingview.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape


@dataclass(frozen=True)
class TradingViewParseResult:
    source_url: str
    source_label: str
    symbols: list[str]
    failed_symbols: list[str]
    status: str
    message: str


def _clean_symbol(raw: str) -> str:
    symbol = raw.split(":")[-1].strip().upper()
    return re.sub(r"[^A-Z0-9._-]", "", symbol)


def _title_label(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return "TradingView Watchlist"
    title = unescape(match.group(1)).strip()
    return title.replace("— TradingView", "").strip()


def _symbols_from_json_scripts(html: str) -> list[str]:
    symbols: list[str] = []
    for script_match in re.finditer(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL):
        content = script_match.group(1).strip()
        if not content.startswith("{"):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        raw_symbols = payload.get("symbols")
        if isinstance(raw_symbols, list):
            for raw in raw_symbols:
                if isinstance(raw, str):
                    cleaned = _clean_symbol(raw)
                    if cleaned and cleaned not in symbols:
                        symbols.append(cleaned)
    return symbols


def parse_tradingview_watchlist_html(html: str, *, source_url: str) -> TradingViewParseResult:
    label = _title_label(html)
    symbols = _symbols_from_json_scripts(html)
    if symbols:
        return TradingViewParseResult(
            source_url=source_url,
            source_label=label,
            symbols=symbols,
            failed_symbols=[],
            status="ok",
            message=f"Parsed {len(symbols)} symbols from static HTML.",
        )
    return TradingViewParseResult(
        source_url=source_url,
        source_label=label,
        symbols=[],
        failed_symbols=[],
        status="no_symbols_found",
        message="Static HTML did not expose symbols; use browser-rendered retrieval or keep this source degraded.",
    )
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
pytest tests/test_tradingview_parser.py -v
```

Expected: PASS.

- [ ] **Step 5: Manual validation command for sample URL**

Run this command only to inspect the current public page behavior:

```bash
python - <<'PY'
import httpx
from uw_scan.sources.tradingview import parse_tradingview_watchlist_html

url = "https://www.tradingview.com/watchlists/326877343/"
html = httpx.get(url, timeout=20).text
result = parse_tradingview_watchlist_html(html, source_url=url)
print(result)
PY
```

Expected: likely `status='no_symbols_found'` for static HTML. If symbols appear, record the result in the implementation notes and add a fixture in the same commit.

- [ ] **Step 6: Commit parser spike**

```bash
git add src/uw_scan/sources/__init__.py src/uw_scan/sources/tradingview.py tests/test_tradingview_parser.py
git commit -m "Add TradingView parser contract"
```

## Task 5: Postgres Schema Migration Foundation

**Files:**
- Create: `src/uw_scan/storage/__init__.py`
- Create: `src/uw_scan/storage/migrations/001_create_uw_scan_schema.sql`
- Test: `tests/test_migration_sql.py`

- [ ] **Step 1: Write migration SQL tests**

Create `tests/test_migration_sql.py`:

```python
from pathlib import Path


MIGRATION = Path("src/uw_scan/storage/migrations/001_create_uw_scan_schema.sql")


def test_migration_creates_schema_and_version_table():
    sql = MIGRATION.read_text()

    assert "CREATE SCHEMA IF NOT EXISTS uw_scan" in sql
    assert "CREATE TABLE IF NOT EXISTS uw_scan.schema_versions" in sql
    assert "001_create_uw_scan_schema" in sql


def test_migration_uses_compressed_bytea_raw_payloads():
    sql = MIGRATION.read_text()

    assert "CREATE TABLE IF NOT EXISTS uw_scan.raw_payloads" in sql
    assert "payload_compressed BYTEA NOT NULL" in sql
    assert "content_sha256 TEXT NOT NULL" in sql


def test_migration_defines_core_uniqueness_grains():
    sql = MIGRATION.read_text()

    assert "UNIQUE (run_id, option_symbol, fetched_at_utc)" in sql
    assert "UNIQUE (run_id, ticker, market_date, expiry, strike)" in sql
    assert "UNIQUE (run_id, ticker, market_date, expiry)" in sql
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_migration_sql.py -v
```

Expected: FAIL because migration file does not exist.

- [ ] **Step 3: Create storage package and migration SQL**

Create `src/uw_scan/storage/__init__.py`:

```python
"""Storage helpers and SQL migrations."""
```

Create `src/uw_scan/storage/migrations/001_create_uw_scan_schema.sql`:

```sql
CREATE SCHEMA IF NOT EXISTS uw_scan;

CREATE TABLE IF NOT EXISTS uw_scan.schema_versions (
    version TEXT PRIMARY KEY,
    applied_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS uw_scan.scan_runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at_utc TIMESTAMPTZ NOT NULL,
    completed_at_utc TIMESTAMPTZ,
    status TEXT NOT NULL,
    request_budget INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS uw_scan.source_feeds (
    source_feed_id BIGSERIAL PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_label TEXT NOT NULL,
    source_url TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_kind, source_label, source_url)
);

CREATE TABLE IF NOT EXISTS uw_scan.source_imports (
    source_import_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    source_feed_id BIGINT NOT NULL REFERENCES uw_scan.source_feeds(source_feed_id),
    symbol_or_contract TEXT NOT NULL,
    import_status TEXT NOT NULL,
    parsed_at_utc TIMESTAMPTZ NOT NULL,
    error_message TEXT,
    UNIQUE (run_id, source_feed_id, symbol_or_contract)
);

CREATE TABLE IF NOT EXISTS uw_scan.raw_payloads (
    raw_payload_id BIGSERIAL PRIMARY KEY,
    payload_compressed BYTEA NOT NULL,
    content_encoding TEXT NOT NULL DEFAULT 'gzip',
    content_sha256 TEXT NOT NULL,
    payload_size_bytes INTEGER NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS uw_scan.api_request_audit (
    api_request_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    request_fingerprint TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    normalized_params TEXT NOT NULL,
    response_status INTEGER,
    latency_ms INTEGER,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    raw_payload_id BIGINT REFERENCES uw_scan.raw_payloads(raw_payload_id),
    error_message TEXT,
    UNIQUE (run_id, request_fingerprint)
);

CREATE TABLE IF NOT EXISTS uw_scan.option_contract_snapshots (
    option_contract_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    option_symbol TEXT NOT NULL,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    strike NUMERIC NOT NULL,
    option_type TEXT NOT NULL,
    implied_volatility NUMERIC,
    open_interest INTEGER,
    previous_open_interest INTEGER,
    volume INTEGER,
    premium NUMERIC,
    bid NUMERIC,
    ask NUMERIC,
    mid NUMERIC,
    ask_volume INTEGER,
    bid_volume INTEGER,
    multi_leg_volume INTEGER,
    sweep_volume INTEGER,
    UNIQUE (run_id, option_symbol, fetched_at_utc)
);

CREATE TABLE IF NOT EXISTS uw_scan.greeks_by_expiry_strike (
    greek_row_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    strike NUMERIC NOT NULL,
    call_iv NUMERIC,
    put_iv NUMERIC,
    delta NUMERIC,
    gamma NUMERIC,
    theta NUMERIC,
    vega NUMERIC,
    rho NUMERIC,
    vanna NUMERIC,
    charm NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry, strike)
);

CREATE TABLE IF NOT EXISTS uw_scan.oi_by_expiry (
    oi_by_expiry_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    call_open_interest INTEGER,
    put_open_interest INTEGER,
    UNIQUE (run_id, ticker, market_date, expiry)
);

CREATE TABLE IF NOT EXISTS uw_scan.opportunity_scores (
    opportunity_score_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    option_symbol TEXT,
    score INTEGER NOT NULL,
    direction TEXT NOT NULL,
    setup_types TEXT NOT NULL,
    confirmations TEXT NOT NULL,
    warnings TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uw_scan_contract_ticker_expiry
    ON uw_scan.option_contract_snapshots (ticker, expiry, strike);

CREATE INDEX IF NOT EXISTS idx_uw_scan_greeks_ticker_expiry
    ON uw_scan.greeks_by_expiry_strike (ticker, expiry, strike);

INSERT INTO uw_scan.schema_versions (version)
VALUES ('001_create_uw_scan_schema')
ON CONFLICT (version) DO NOTHING;
```

- [ ] **Step 4: Run migration SQL tests**

Run:

```bash
pytest tests/test_migration_sql.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit migration foundation**

```bash
git add src/uw_scan/storage/__init__.py src/uw_scan/storage/migrations/001_create_uw_scan_schema.sql tests/test_migration_sql.py
git commit -m "Add uw_scan schema migration foundation"
```

## Task 6: Fixture-Backed Streamlit Layout

**Files:**
- Create: `app/streamlit_app.py`
- Test: `tests/test_streamlit_smoke.py`

- [ ] **Step 1: Write Streamlit smoke test**

Create `tests/test_streamlit_smoke.py`:

```python
import importlib


def test_streamlit_app_imports_without_running_server():
    module = importlib.import_module("app.streamlit_app")

    assert hasattr(module, "render_app")
```

- [ ] **Step 2: Run smoke test to verify failure**

Run:

```bash
pytest tests/test_streamlit_smoke.py -v
```

Expected: FAIL because `app.streamlit_app` does not exist.

- [ ] **Step 3: Create Streamlit layout**

Create `app/streamlit_app.py`:

```python
from __future__ import annotations

import pandas as pd
import streamlit as st

from uw_scan.config import UwScanConfig
from uw_scan.fixtures import demo_dashboard


def _opportunities_df(dashboard):
    return pd.DataFrame(
        [
            {
                "Ticker": row.ticker,
                "Contract": row.contract_label,
                "Direction": row.direction.value,
                "Score": row.score,
                "Setups": ", ".join(row.setup_types),
                "Sources": ", ".join(row.source_labels),
                "Structure": row.structure_idea.structure_type if row.structure_idea else "",
                "Warnings": ", ".join(row.warnings),
            }
            for row in dashboard.opportunities
        ]
    )


def _flow_df(dashboard):
    return pd.DataFrame([row.model_dump() for row in dashboard.flow_rows])


def _tracked_df(dashboard):
    return pd.DataFrame([row.model_dump() for row in dashboard.tracked_items])


def _surface_df(dashboard):
    return pd.DataFrame([row.model_dump() for row in dashboard.surface_metrics])


def render_sidebar(config: UwScanConfig):
    st.sidebar.header("Controls")
    mode = st.sidebar.radio("Run mode", ["Fixture", "Live polling", "Snapshot replay"], index=0)
    st.sidebar.number_input("Polling interval seconds", min_value=15, max_value=600, value=config.poll_seconds, step=15)
    st.sidebar.text_input("TradingView shared URL", value="https://www.tradingview.com/watchlists/326877343/")
    st.sidebar.number_input("Max requests per cycle", min_value=25, max_value=1000, value=config.max_requests_per_cycle, step=25)
    st.sidebar.caption("UW API key: configured" if config.api_key else "UW API key: not configured")
    st.sidebar.button("Run scan", disabled=mode == "Fixture")
    st.sidebar.button("Save snapshot", disabled=True)
    st.sidebar.button("Load snapshot", disabled=True)
    return mode


def render_app():
    st.set_page_config(page_title="UW Opportunity Scanner", layout="wide")
    config = UwScanConfig.from_env()
    dashboard = demo_dashboard()
    mode = render_sidebar(config)

    st.title("UW Opportunity Scanner")
    st.caption(f"Mode: {mode} | Generated at {dashboard.generated_at_utc.isoformat()}")

    budget = dashboard.request_budget
    cols = st.columns(4)
    cols[0].metric("Estimated requests", budget.total_estimated_requests)
    cols[1].metric("Flow rows", budget.flow_rows)
    cols[2].metric("Watchlist symbols", budget.watchlist_symbols)
    cols[3].metric("Deep surface capped", "Yes" if budget.capped else "No")

    tabs = st.tabs([
        "Top Opportunities",
        "UW Flow Feed",
        "TradingView Watchlists",
        "Tracked Contracts",
        "Surface Explorer",
        "Snapshots",
    ])

    with tabs[0]:
        st.subheader("Top Opportunities")
        st.dataframe(_opportunities_df(dashboard), use_container_width=True, hide_index=True)

    with tabs[1]:
        st.subheader("UW Flow Feed")
        st.dataframe(_flow_df(dashboard), use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("TradingView Watchlists")
        for source in dashboard.watchlist_sources:
            st.markdown(f"**{source.source.label}**")
            st.caption(f"{source.source.url} | status: {source.source.status}")
            st.write(", ".join(source.imported_symbols))

    with tabs[3]:
        st.subheader("Tracked Contracts")
        st.dataframe(_tracked_df(dashboard), use_container_width=True, hide_index=True)

    with tabs[4]:
        st.subheader("Surface Explorer")
        st.dataframe(_surface_df(dashboard), use_container_width=True, hide_index=True)

    with tabs[5]:
        st.subheader("Snapshots")
        st.dataframe(pd.DataFrame([row.model_dump() for row in dashboard.snapshots]), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    render_app()
```

- [ ] **Step 4: Run Streamlit smoke test**

Run:

```bash
pytest tests/test_streamlit_smoke.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run:

```bash
pytest -v
```

Expected: PASS for all tests created in this plan.

- [ ] **Step 6: Start local Streamlit app**

Run:

```bash
streamlit run app/streamlit_app.py
```

Expected: Streamlit prints a local URL and the page renders six tabs using fixture data.

- [ ] **Step 7: Commit first layout**

```bash
git add app/streamlit_app.py tests/test_streamlit_smoke.py
git commit -m "Add fixture-backed Streamlit layout"
```

## Task 7: Documentation And Verification Pass

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-11-uw-scan-design.md`

- [ ] **Step 1: Update README with current phase boundary**

Modify `README.md` so it includes:

```markdown
## Current Phase

The current implementation is fixture-backed. It verifies the dashboard shape, config loading, request-budget preview, TradingView parser contract, and schema migration foundation.

Live UW API polling is intentionally deferred until the request audit and normalization layer are implemented.
```

- [ ] **Step 2: Run full verification**

Run:

```bash
pytest -v
```

Expected: PASS.

Run:

```bash
git status --short
```

Expected: only `README.md` is modified before the final commit.

- [ ] **Step 3: Commit docs**

```bash
git add README.md
git commit -m "Document UW scan foundation phase"
```

## Plan Self-Review Checklist

- Spec coverage: This plan covers the first layout, secret handling, config, TradingView parser spike, request-budget planner, schema migration foundation, typed relational grains, raw payload storage decision, and fixture-backed UI. It does not implement live UW API calls, live Postgres persistence, scoring rules, tracking reconciliation, or deep surface retrieval; those are later implementation plans.
- Red-flag scan: The plan intentionally avoids committed secret values. No committed secret token appears in the plan.
- Type consistency: `DashboardViewModel`, `RequestBudgetSummary`, `UwScanConfig`, and parser result names are defined before use.
- Execution gate: After this plan passes, write the next plan for live UW client plus request audit and normalization.
