# Trade Insights AI Claude Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Claude as a second AI provider alongside Codex for the Trade Insights AI feature, with side-by-side tabs (Codex | Claude) on the stock detail page. Each Run click enqueues one row per enabled provider; both render in independent tabs as they finish.

**Architecture:** Provider dimension added at every layer (DB column, Pydantic models, API contract, worker dispatch, web tabs). Shared prompt/schema/validator/renderer across providers — comparison is "same input, different model" by construction. A `Protocol`-based runner registry (`RUNNERS = {"codex": CodexRunner(), "claude": ClaudeRunner()}`) keeps the dispatch tick branch-free and trivially extensible.

**Tech Stack:** Python 3.13 + `uv`, FastAPI + Pydantic v2, psycopg 3, APScheduler, PostgreSQL (schema `uw_scan`), Next.js 16 + React 19 + TypeScript, Vitest + Playwright (web), pytest + pytest-postgresql (Python). `claude --print` CLI for the new runner; existing `codex exec` for the existing runner.

**Spec:** `docs/superpowers/archive/specs/2026-05-22-trade-insights-ai-claude-provider-design.md`

**Phases:**
- **Phase A (Tasks 1–17):** Schema + Pydantic models + repository + runners + worker dispatch + config + API contract + web tabs. Both providers default-enabled. Worker topology stays on the legacy `ai` single-pool — both providers run, just through one shared queue.
- **Phase B (Tasks 18–22):** Operational topology split into `ai-codex` × 2 + `ai-claude` × 2 with per-provider heartbeats and health surface.

End of Phase A is a functionally complete, shippable feature.

---

## Pre-flight checks

Run these once before starting Task 1.

- [ ] **Step 1: Confirm `claude` CLI is installed and on PATH**

Run: `which claude && claude --version`
Expected: a path under `~/.local/bin/claude` (or similar) and a version string.

- [ ] **Step 2: Confirm `claude --print --json-schema` works**

Run:
```bash
# CRITICAL: --mcp-config requires {"mcpServers": {}} — bare {} is rejected with
# "Invalid input: expected record, received undefined".
# CRITICAL: --output-format json returns a JSON *array* of events, not a single
# envelope object. The array contains init/assistant/result events in order.
unset ANTHROPIC_API_KEY  # otherwise apiKeySource wins over OAuth keychain
echo "Return JSON with key 'ok' set to true." | claude --print \
  --tools "" --disable-slash-commands --strict-mcp-config \
  --mcp-config '{"mcpServers": {}}' \
  --no-session-persistence --output-format json \
  --json-schema '{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"]}'
```
Expected: a JSON array. The first element is `{"type":"system","subtype":"init","model":"claude-opus-4-7","apiKeySource":"...","session_id":"..."}`. The last element is `{"type":"result","subtype":"success","is_error":false,"result":"{\"ok\":true}","model":"claude-opus-4-7",...}`. The `result` field is a stringified JSON conforming to the schema. The runner extracts `model` from the init event and `result` from the result event, and treats `is_error: true` as a failure even when `subtype == "success"`.

- [ ] **Step 3: Confirm latest migration number**

Run: `ls -1 src/uw_scan/storage/migrations/*.sql | sort | tail -3`
Expected: `052_ws_consumer_state.sql` (or newer). The plan uses migration number **053** for the new schema change. If something newer than 052 exists, bump to next available number and update every reference below.

- [ ] **Step 4: Confirm `uv sync --extra postgres` is current**

Run: `uv sync --extra postgres`
Expected: "Resolved N packages" with no install failures.

- [ ] **Step 5: Create the feature branch**

Run:
```bash
git checkout main
git pull origin main
git checkout -b feat/trade-insights-ai-claude-provider
```

---

# Phase A — Code-complete feature on legacy worker topology

## Task 1: Migration 053 (provider column + indexes)

**Files:**
- Create: `src/uw_scan/storage/migrations/053_trade_insights_ai_provider_column.sql`
- Test: `tests/integration/storage/test_migrations.py` (extend existing block)

- [ ] **Step 1.1: Write the failing migration test**

Extend the existing `trade_insight_ai_analyses` block in `tests/integration/storage/test_migrations.py`. Locate the existing block (`SELECT to_regclass('uw_scan.trade_insight_ai_analyses')`) and add after it:

```python
def test_trade_insight_ai_analyses_has_provider_column(postgresql, run_migrations) -> None:
    """Migration 053 adds provider TEXT NOT NULL DEFAULT 'codex' with a CHECK
    constraint restricting values to codex|claude."""
    with postgresql.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'uw_scan' "
            "  AND table_name = 'trade_insight_ai_analyses' "
            "  AND column_name = 'provider'"
        )
        row = cur.fetchone()
    assert row is not None, "provider column missing"
    assert row[1] == "text"
    assert row[2] == "NO"
    assert row[3] is not None and "'codex'" in row[3]


def test_trade_insight_ai_analyses_provider_check_constraint(postgresql, run_migrations) -> None:
    with postgresql.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class t ON c.conrelid = t.oid "
            "JOIN pg_namespace n ON t.relnamespace = n.oid "
            "WHERE n.nspname = 'uw_scan' "
            "  AND t.relname = 'trade_insight_ai_analyses' "
            "  AND c.conname = 'trade_insight_ai_analyses_provider_check'"
        )
        row = cur.fetchone()
    assert row is not None
    assert "codex" in row[0] and "claude" in row[0]


def test_trade_insight_ai_analyses_succeeded_reuse_index_includes_provider(
    postgresql, run_migrations
) -> None:
    with postgresql.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "  AND tablename = 'trade_insight_ai_analyses' "
            "  AND indexname = 'idx_trade_insight_ai_analyses_succeeded_reuse'"
        )
        row = cur.fetchone()
    assert row is not None
    indexdef = row[0]
    assert "provider" in indexdef
    assert "analysis_input_hash" in indexdef
    assert "prompt_version" in indexdef
    assert "model" in indexdef
    assert "succeeded" in indexdef.lower()


def test_trade_insight_ai_analyses_active_reuse_index_includes_provider(
    postgresql, run_migrations
) -> None:
    with postgresql.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "  AND tablename = 'trade_insight_ai_analyses' "
            "  AND indexname = 'idx_trade_insight_ai_analyses_active_reuse'"
        )
        row = cur.fetchone()
    assert row is not None
    indexdef = row[0]
    assert "provider" in indexdef
    assert "queued" in indexdef.lower() and "running" in indexdef.lower()


def test_trade_insight_ai_analyses_provider_queue_index_exists(
    postgresql, run_migrations
) -> None:
    with postgresql.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "  AND tablename = 'trade_insight_ai_analyses' "
            "  AND indexname = 'idx_trade_insight_ai_analyses_provider_queue'"
        )
        assert cur.fetchone() is not None
```

- [ ] **Step 1.2: Run the tests — verify they fail**

Run: `uv run pytest tests/integration/storage/test_migrations.py -k provider -v`
Expected: 5 tests fail (the migration file doesn't exist yet).

- [ ] **Step 1.3: Write migration 053**

Create `src/uw_scan/storage/migrations/053_trade_insights_ai_provider_column.sql`:

```sql
-- 053_trade_insights_ai_provider_column.sql
-- Add provider column + extend cache-reuse indexes for the Claude provider.
-- Existing rows backfill with 'codex' (the only path that existed before this
-- migration). Per-provider cache reuse is enforced by the new index keys.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'codex';

ALTER TABLE uw_scan.trade_insight_ai_analyses
    DROP CONSTRAINT IF EXISTS trade_insight_ai_analyses_provider_check;

ALTER TABLE uw_scan.trade_insight_ai_analyses
    ADD CONSTRAINT trade_insight_ai_analyses_provider_check
        CHECK (provider IN ('codex', 'claude'));

DROP INDEX IF EXISTS uw_scan.idx_trade_insight_ai_analyses_succeeded_reuse;
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_succeeded_reuse
    ON uw_scan.trade_insight_ai_analyses (
        ticker, analysis_input_hash, prompt_version, model, provider
    )
    WHERE status = 'succeeded';

DROP INDEX IF EXISTS uw_scan.idx_trade_insight_ai_analyses_active_reuse;
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_active_reuse
    ON uw_scan.trade_insight_ai_analyses (
        ticker, analysis_input_hash, prompt_version, model, provider
    )
    WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_trade_insight_ai_analyses_provider_queue
    ON uw_scan.trade_insight_ai_analyses (provider, status, requested_at);

COMMENT ON COLUMN uw_scan.trade_insight_ai_analyses.provider IS
    'AI provider that produced this analysis: codex or claude. '
    'Each Run enqueues one row per enabled provider; per-provider cache reuse '
    'is enforced by indexes keyed on (ticker, analysis_input_hash, '
    'prompt_version, model, provider).';
```

- [ ] **Step 1.4: Run the tests — verify they pass**

Run: `uv run pytest tests/integration/storage/test_migrations.py -k provider -v`
Expected: all 5 provider tests pass.

- [ ] **Step 1.5: Apply migration locally**

Run: `bash scripts/migrate.sh`
Expected: "applying 053_trade_insights_ai_provider_column.sql" then "OK"; subsequent run prints "already applied" or is a no-op.

- [ ] **Step 1.6: Spot-check the live DB**

Run:
```bash
psql -d option_wizard -c "SELECT provider, count(*) FROM uw_scan.trade_insight_ai_analyses GROUP BY provider"
psql -d option_wizard -c "\d uw_scan.trade_insight_ai_analyses"
```
Expected: existing rows show `provider = 'codex'`; the column and CHECK constraint appear in `\d` output; both `idx_..._succeeded_reuse` and `idx_..._active_reuse` indexes include `provider`.

- [ ] **Step 1.7: Commit**

```bash
git add src/uw_scan/storage/migrations/053_trade_insights_ai_provider_column.sql \
        tests/integration/storage/test_migrations.py
git commit -m "feat(ai): migration 053 — provider column + per-provider cache indexes"
```

---

## Task 2: Pydantic models — provider literal + new response types

**Files:**
- Modify: `src/uw_scan/models/trade_insights_ai.py:165-225`
- Modify: `src/uw_scan/models/__init__.py:114-135` (exports), `:254-272` (__all__), `:285-310` (`_preserve_public_module` call)
- Test: `tests/unit/test_models_trade_insights_ai.py` (new file)

- [ ] **Step 2.1: Write failing model tests**

Create `tests/unit/test_models_trade_insights_ai.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from uw_scan.models import (
    TradeInsightAiAnalysisEnqueueResponse,
    TradeInsightAiAnalysisResponse,
    TradeInsightAiAnalysisStub,
    TradeInsightAiLatestPair,
    TradeInsightAiProvider,
)


def test_provider_literal_accepts_codex_and_claude() -> None:
    stub = TradeInsightAiAnalysisStub(
        provider="codex",
        analysis_id=uuid4(),
        status="queued",
        reused=False,
        model="codex-default",
    )
    assert stub.provider == "codex"
    stub2 = stub.model_copy(update={"provider": "claude"})
    assert stub2.provider == "claude"


def test_provider_literal_rejects_other_values() -> None:
    with pytest.raises(ValueError):
        TradeInsightAiAnalysisStub(
            provider="openai",  # type: ignore[arg-type]
            analysis_id=uuid4(),
            status="queued",
            reused=False,
            model="x",
        )


def test_enqueue_response_holds_list_of_stubs() -> None:
    resp = TradeInsightAiAnalysisEnqueueResponse(
        analyses=[
            TradeInsightAiAnalysisStub(
                provider="codex",
                analysis_id=uuid4(),
                status="queued",
                reused=False,
                model="codex-default",
            ),
            TradeInsightAiAnalysisStub(
                provider="claude",
                analysis_id=uuid4(),
                status="succeeded",
                reused=True,
                model="claude-opus-4-7",
            ),
        ]
    )
    assert len(resp.analyses) == 2
    assert {a.provider for a in resp.analyses} == {"codex", "claude"}


def test_latest_pair_allows_null_per_provider() -> None:
    pair = TradeInsightAiLatestPair(codex=None, claude=None)
    assert pair.codex is None
    assert pair.claude is None


def test_analysis_response_has_provider_and_model_fields() -> None:
    now = datetime.now(timezone.utc)
    resp = TradeInsightAiAnalysisResponse(
        analysis_id=uuid4(),
        ticker="TSLA",
        run_id=1,
        trade_insights_input_hash="x",
        analysis_input_hash="y",
        model="codex-default",
        provider="codex",
        prompt_version="trade-insights-ai-v4",
        status="queued",
        requested_at=now,
        reused=False,
    )
    assert resp.provider == "codex"
    assert resp.model == "codex-default"
```

- [ ] **Step 2.2: Run the tests — verify they fail**

Run: `uv run pytest tests/unit/test_models_trade_insights_ai.py -v`
Expected: all tests fail with `ImportError: cannot import name 'TradeInsightAiAnalysisStub'` (and friends).

- [ ] **Step 2.3: Add new types to `src/uw_scan/models/trade_insights_ai.py`**

At the top of the file (where the existing `Literal` imports are), ensure `Literal` is imported:

```python
from typing import Literal
```

Replace the existing `class TradeInsightAiAnalysisResponse(...)` block (around line 171) with this expanded version:

```python
TradeInsightAiProvider = Literal["codex", "claude"]


class TradeInsightAiAnalysisRequest(TradeInsightAiBase):
    force_rerun: bool = False


class TradeInsightAiAnalysisResponse(TradeInsightAiBase):
    analysis_id: UUID
    ticker: str
    run_id: int
    trade_insights_input_hash: str
    analysis_input_hash: str
    model: str
    provider: TradeInsightAiProvider = "codex"
    prompt_version: str
    status: Literal["queued", "running", "succeeded", "failed"]
    produced_at: datetime | None = None
    outcome: TradeInsightAiOutcome | None = None
    markdown: str | None = None
    error_message: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reused: bool = False


class TradeInsightAiAnalysisStub(TradeInsightAiBase):
    """Lightweight stub returned by POST when enqueueing per-provider rows."""

    provider: TradeInsightAiProvider
    analysis_id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    reused: bool
    model: str


class TradeInsightAiAnalysisEnqueueResponse(TradeInsightAiBase):
    """POST response — one stub per enabled provider."""

    analyses: list[TradeInsightAiAnalysisStub]


class TradeInsightAiLatestPair(TradeInsightAiBase):
    """GET /latest response — null per provider when no succeeded row exists."""

    codex: TradeInsightAiAnalysisResponse | None = None
    claude: TradeInsightAiAnalysisResponse | None = None
```

The `provider` default of `"codex"` on `TradeInsightAiAnalysisResponse` preserves OpenAPI compatibility for any consumer that hasn't migrated.

- [ ] **Step 2.4: Wire new exports in `src/uw_scan/models/__init__.py`**

In the `from .trade_insights_ai import (` block (currently around line 114–135), add (alphabetical insertion):

```python
    TradeInsightAiAnalysisEnqueueResponse,
    TradeInsightAiAnalysisStub,
    TradeInsightAiLatestPair,
    TradeInsightAiProvider,
```

In the `__all__` tuple (currently around line 254–272), add (alphabetical):

```python
    "TradeInsightAiAnalysisEnqueueResponse",
    "TradeInsightAiAnalysisStub",
    "TradeInsightAiLatestPair",
    "TradeInsightAiProvider",
```

In the `_preserve_public_module(...)` call (around line 285), add the three new BaseModel classes (NOT `TradeInsightAiProvider` — it's a Literal alias, not a model):

```python
    TradeInsightAiAnalysisEnqueueResponse,
    TradeInsightAiAnalysisStub,
    TradeInsightAiLatestPair,
```

- [ ] **Step 2.5: Run the tests — verify they pass**

Run: `uv run pytest tests/unit/test_models_trade_insights_ai.py -v`
Expected: all 5 tests pass.

- [ ] **Step 2.6: Verify no other model tests broke**

Run: `uv run pytest tests/unit/ -v -k "model" 2>&1 | tail -40`
Expected: no failures in any model test (the new `provider` default keeps existing `TradeInsightAiAnalysisResponse` instantiations working).

- [ ] **Step 2.7: Commit**

```bash
git add src/uw_scan/models/trade_insights_ai.py \
        src/uw_scan/models/__init__.py \
        tests/unit/test_models_trade_insights_ai.py
git commit -m "feat(ai): add TradeInsightAiProvider literal + stub/pair/enqueue response models"
```

---

## Task 3: Repository — provider parameter on all reads/writes

**Files:**
- Modify: `src/uw_scan/storage/trade_insights_ai.py:147-410` (touch every method that filters on `model`)
- Test: `tests/integration/storage/test_trade_insights_ai_repository.py` (new file)

- [ ] **Step 3.1: Write failing repository tests**

Create `tests/integration/storage/test_trade_insights_ai_repository.py`:

```python
"""Tests for provider-aware trade_insights_ai repository methods."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from uw_scan.storage.repository import Repository


def _seed_snapshot(repo: Repository) -> int:
    """Insert a minimal trade_insight_snapshot for FK satisfaction."""
    cur = repo.conn.cursor()
    cur.execute(
        f"INSERT INTO {repo._schema}.trade_insight_snapshots "
        "(run_id, ticker, as_of, assembler_version, input_hash, "
        " source_reconciliation_status, confidence_label, data_quality_label, "
        " preferred_idea_id, payload_jsonb) "
        "VALUES (1, 'TSLA', NULL, 'test', 'h', 'ok', 'ok', 'ok', NULL, '{}'::jsonb) "
        "RETURNING snapshot_id"
    )
    return cur.fetchone()[0]


def test_enqueue_with_provider_creates_separate_rows_per_provider(repo: Repository) -> None:
    snapshot_id = _seed_snapshot(repo)
    codex_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=1,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={"k": "v"},
        prompt_version="trade-insights-ai-v4",
        model="codex-default",
        provider="codex",
    )
    claude_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id,
        ticker="TSLA",
        run_id=1,
        trade_insights_input_hash="h",
        analysis_input_hash="ha",
        analysis_input={"k": "v"},
        prompt_version="trade-insights-ai-v4",
        model="claude-default",
        provider="claude",
    )
    assert codex_id != claude_id


def test_unique_reuse_allows_same_input_different_providers(repo: Repository) -> None:
    """Load-bearing test for migration 053: same input hash + prompt_version
    + model BUT different provider must NOT collide on the active-reuse index."""
    snapshot_id = _seed_snapshot(repo)
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id, ticker="TSLA", run_id=1,
        trade_insights_input_hash="h", analysis_input_hash="ha",
        analysis_input={"k": "v"}, prompt_version="v",
        model="m", provider="codex",
    )
    # Same hash/version/model — only provider differs. Must succeed.
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id, ticker="TSLA", run_id=1,
        trade_insights_input_hash="h", analysis_input_hash="ha",
        analysis_input={"k": "v"}, prompt_version="v",
        model="m", provider="claude",
    )


def test_claim_next_with_provider_filter_returns_only_matching_rows(repo: Repository) -> None:
    snapshot_id = _seed_snapshot(repo)
    codex_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id, ticker="TSLA", run_id=1,
        trade_insights_input_hash="h", analysis_input_hash="ha",
        analysis_input={}, prompt_version="v", model="m", provider="codex",
    )
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id, ticker="TSLA", run_id=1,
        trade_insights_input_hash="h", analysis_input_hash="hb",
        analysis_input={}, prompt_version="v", model="m", provider="claude",
    )
    claimed = repo.claim_next_trade_insight_ai_analysis(
        stale_running_before=datetime(2000, 1, 1, tzinfo=timezone.utc),
        provider="codex",
    )
    assert claimed is not None
    assert str(claimed["analysis_id"]) == str(codex_id)
    assert claimed["provider"] == "codex"


def test_claim_next_without_provider_filter_returns_any_provider(repo: Repository) -> None:
    snapshot_id = _seed_snapshot(repo)
    repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id, ticker="TSLA", run_id=1,
        trade_insights_input_hash="h", analysis_input_hash="ha",
        analysis_input={}, prompt_version="v", model="m", provider="claude",
    )
    claimed = repo.claim_next_trade_insight_ai_analysis(
        stale_running_before=datetime(2000, 1, 1, tzinfo=timezone.utc),
        provider=None,
    )
    assert claimed is not None
    assert claimed["provider"] == "claude"


def test_latest_pair_returns_keyed_dict_per_provider(repo: Repository) -> None:
    snapshot_id = _seed_snapshot(repo)
    codex_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id, ticker="TSLA", run_id=1,
        trade_insights_input_hash="h", analysis_input_hash="ha",
        analysis_input={}, prompt_version="v", model="m", provider="codex",
    )
    repo.complete_trade_insight_ai_analysis(
        codex_id, outcome={"x": 1}, markdown="md", resolved_model="codex-default",
    )
    pair = repo.find_latest_trade_insight_ai_analyses_per_provider(
        ticker="TSLA", prompt_version="v",
    )
    assert pair["codex"] is not None
    assert pair["claude"] is None
    assert str(pair["codex"]["analysis_id"]) == str(codex_id)
```

You'll also need a `repo` fixture that wraps a `pytest-postgresql`-provisioned DB. Check `tests/integration/conftest.py` or `tests/integration/storage/conftest.py` for the existing fixture (the migration tests already use one — re-use it). If no `repo` fixture exists in the storage subdirectory, add one to `tests/integration/storage/conftest.py`:

```python
import pytest
import psycopg
from uw_scan.storage.repository import Repository

@pytest.fixture
def repo(postgresql, run_migrations) -> Repository:
    conn = psycopg.connect(
        host=postgresql.info.host, port=postgresql.info.port,
        dbname=postgresql.info.dbname, user=postgresql.info.user,
        password=postgresql.info.password,
    )
    return Repository(conn, schema="uw_scan")
```

- [ ] **Step 3.2: Run the tests — verify they fail**

Run: `uv run pytest tests/integration/storage/test_trade_insights_ai_repository.py -v`
Expected: tests fail with `TypeError: enqueue_trade_insight_ai_analysis() got an unexpected keyword argument 'provider'` (and similar for claim/latest).

- [ ] **Step 3.3: Update `enqueue_trade_insight_ai_analysis` to accept `provider`**

In `src/uw_scan/storage/trade_insights_ai.py`, change the `enqueue_trade_insight_ai_analysis` signature and SQL (around line 250):

```python
def enqueue_trade_insight_ai_analysis(
    self,
    *,
    snapshot_id: int,
    ticker: str,
    run_id: int,
    trade_insights_input_hash: str,
    analysis_input_hash: str,
    analysis_input: dict[str, Any],
    prompt_version: str,
    model: str,
    provider: str,  # NEW
) -> str:
    sql = (
        f"INSERT INTO {self._schema}.trade_insight_ai_analyses "
        "(snapshot_id, ticker, run_id, trade_insights_input_hash, "
        "analysis_input_hash, analysis_input_jsonb, prompt_version, model, provider, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued') "
        "ON CONFLICT (ticker, analysis_input_hash, prompt_version, model, provider) "
        "WHERE status IN ('queued', 'running') "
        "DO NOTHING "
        "RETURNING analysis_id"
    )
    with self._conn.cursor() as cur:
        cur.execute(
            sql,
            (
                snapshot_id, ticker.upper(), run_id,
                trade_insights_input_hash, analysis_input_hash,
                Jsonb(analysis_input),
                prompt_version, model, provider,
            ),
        )
        row = cur.fetchone()
        if row is not None:
            return str(row[0])
        # ON CONFLICT path — fetch the existing row's analysis_id.
        cur.execute(
            f"SELECT analysis_id FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s AND analysis_input_hash = %s "
            "  AND prompt_version = %s AND model = %s AND provider = %s "
            "  AND status IN ('queued', 'running') "
            "ORDER BY requested_at DESC LIMIT 1",
            (ticker.upper(), analysis_input_hash, prompt_version, model, provider),
        )
        return str(cur.fetchone()[0])
```

- [ ] **Step 3.4: Update `find_reusable_trade_insight_ai_analysis` to accept `provider`**

Locate the method (around line 140) and add a required `provider: str` keyword parameter; add `AND provider = %s` to the WHERE clause; append `provider` to the params tuple. The SQL pattern:

```python
def find_reusable_trade_insight_ai_analysis(
    self,
    *,
    ticker: str,
    analysis_input_hash: str,
    prompt_version: str,
    model: str,
    provider: str,  # NEW
) -> dict[str, Any] | None:
    sql = (
        f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
        "WHERE ticker = %s AND analysis_input_hash = %s "
        "  AND prompt_version = %s AND model = %s AND provider = %s "
        "  AND status = 'succeeded' "
        "ORDER BY produced_at DESC NULLS LAST, requested_at DESC LIMIT 1"
    )
    with self._conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            sql,
            (ticker.upper(), analysis_input_hash, prompt_version, model, provider),
        )
        return cur.fetchone()
```

- [ ] **Step 3.5: Update `find_latest_trade_insight_ai_analysis` to accept `provider`**

Same pattern — add `provider: str` parameter, `AND provider = %s` to WHERE, `provider` to params (around line 222):

```python
def find_latest_trade_insight_ai_analysis(
    self,
    *,
    ticker: str,
    prompt_version: str,
    model: str,
    provider: str,  # NEW
) -> dict[str, Any] | None:
    sql = (
        f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
        "WHERE ticker = %s AND prompt_version = %s AND model = %s AND provider = %s "
        "  AND status = 'succeeded' "
        "ORDER BY produced_at DESC NULLS LAST, requested_at DESC LIMIT 1"
    )
    with self._conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (ticker.upper(), prompt_version, model, provider))
        return cur.fetchone()
```

- [ ] **Step 3.6: Add `find_latest_trade_insight_ai_analyses_per_provider`**

Insert this NEW method immediately after `find_latest_trade_insight_ai_analysis`:

```python
def find_latest_trade_insight_ai_analyses_per_provider(
    self,
    *,
    ticker: str,
    prompt_version: str,
) -> dict[str, dict[str, Any] | None]:
    """Return the latest succeeded row per known provider as a dict.

    Output shape: {"codex": row|None, "claude": row|None}. Model is NOT in
    the key — the latest succeeded row WINS regardless of which model produced
    it (mirrors the existing single-provider /latest behavior, which also
    queried by model but always with the currently-configured model).
    """
    sql = (
        f"SELECT DISTINCT ON (provider) * FROM {self._schema}.trade_insight_ai_analyses "
        "WHERE ticker = %s AND prompt_version = %s AND status = 'succeeded' "
        "ORDER BY provider, produced_at DESC NULLS LAST, requested_at DESC"
    )
    out: dict[str, dict[str, Any] | None] = {"codex": None, "claude": None}
    with self._conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (ticker.upper(), prompt_version))
        for row in cur.fetchall():
            out[row["provider"]] = row
    return out
```

- [ ] **Step 3.7: Update `claim_next_trade_insight_ai_analysis` to accept `provider`**

The existing method (at `src/uw_scan/storage/trade_insights_ai.py:303`) uses an inline UPDATE with subquery pattern (NOT a CTE). Preserve that pattern; just extend the inner SELECT's WHERE clause with an optional provider filter. The current signature is `(*, stale_running_before: datetime | None = None)` — add `provider: str | None = None` as a new keyword-only param:

```python
def claim_next_trade_insight_ai_analysis(
    self,
    *,
    stale_running_before: datetime | None = None,
    provider: str | None = None,  # NEW
) -> dict[str, Any] | None:
    provider_clause = " AND provider = %s" if provider is not None else ""
    sql = (
        f"UPDATE {self._schema}.trade_insight_ai_analyses "
        "SET status = 'running', started_at = now(), finished_at = NULL, error_message = NULL "
        "WHERE analysis_id = ("
        f"  SELECT analysis_id FROM {self._schema}.trade_insight_ai_analyses "
        "  WHERE (status = 'queued' "
        "     OR ("
        "       status = 'running' "
        "       AND %s::timestamptz IS NOT NULL "
        "       AND (started_at IS NULL OR started_at < %s::timestamptz)"
        "     ))"
        f"     {provider_clause} "
        "  ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, requested_at "
        "  FOR UPDATE SKIP LOCKED "
        "  LIMIT 1"
        ") "
        "RETURNING *"
    )
    params: list[Any] = [stale_running_before, stale_running_before]
    if provider is not None:
        params.append(provider)
    with self._conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description or []]
        return dict(zip(cols, row, strict=False))
```

Note: this preserves the existing dict-mapping pattern (no `psycopg.rows.dict_row`) — the rest of the file uses that style.

- [ ] **Step 3.8: Update `complete_trade_insight_ai_analysis` to accept `resolved_model`**

Locate the method (around line 343 in `trade_insights_ai.py`). Add a `resolved_model: str | None = None` parameter; when non-None, set `model = %s` in the UPDATE alongside the other fields. This is the post-hoc canonical-model capture:

```python
def complete_trade_insight_ai_analysis(
    self,
    analysis_id: str,
    *,
    outcome: dict[str, Any],
    markdown: str,
    resolved_model: str | None = None,  # NEW
) -> None:
    set_clauses = [
        "status = 'succeeded'",
        "outcome_jsonb = %s",
        "markdown = %s",
        "finished_at = now()",
    ]
    params: list[Any] = [Jsonb(outcome), markdown]
    if resolved_model is not None:
        set_clauses.insert(-1, "model = %s")
        params.append(resolved_model)
    params.append(analysis_id)
    sql = (
        f"UPDATE {self._schema}.trade_insight_ai_analyses "
        f"SET {', '.join(set_clauses)} "
        f"WHERE analysis_id = %s"
    )
    with self._conn.cursor() as cur:
        cur.execute(sql, tuple(params))
```

- [ ] **Step 3.9: Run the tests — verify they pass**

Run: `uv run pytest tests/integration/storage/test_trade_insights_ai_repository.py -v`
Expected: all 5 tests pass.

- [ ] **Step 3.10: Run the broader storage test suite to catch regressions**

Run: `uv run pytest tests/integration/storage/ -v 2>&1 | tail -40`
Expected: no failures. Pre-existing tests that called `enqueue_trade_insight_ai_analysis` without `provider=` will now fail with `TypeError: missing required keyword argument 'provider'` — fix them by adding `provider="codex"` to those call sites (they were Codex-only before this change). Do the same for `find_reusable_*` and `find_latest_*` callers.

- [ ] **Step 3.11: Commit**

```bash
git add src/uw_scan/storage/trade_insights_ai.py \
        src/uw_scan/storage/repository.py \
        tests/integration/storage/test_trade_insights_ai_repository.py \
        tests/integration/storage/conftest.py \
        tests/integration/storage/test_migrations.py
git commit -m "feat(ai): repository — provider-aware enqueue/find/claim + per-provider latest pair + resolved_model capture"
```

---

## Task 4: Shared runner module (Protocol + helpers)

**Files:**
- Create: `src/uw_scan/worker/jobs/trade_insights_ai_runners.py`
- Test: `tests/unit/worker/test_trade_insights_ai_runners_shared.py`

- [ ] **Step 4.1: Write failing tests for the shared helpers**

Create `tests/unit/worker/test_trade_insights_ai_runners_shared.py`:

```python
"""Tests for shared helpers in trade_insights_ai_runners."""
from __future__ import annotations

import os

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    _format_runner_failure,
    _runner_child_env,
)


def test_format_runner_failure_lifts_error_lines_to_front() -> None:
    banner = (
        "Codex banner line 1\n"
        + ("noise line\n" * 50)
        + "ERROR: You've hit your usage limit. Try again later."
    )
    msg = _format_runner_failure(banner, None)
    assert "[errors]" in msg
    assert "You've hit your usage limit" in msg
    assert msg.index("[errors]") < msg.index("[tail]")


def test_format_runner_failure_falls_back_to_tail_with_no_errors() -> None:
    long = "x" * 5000 + "\nfinal-cause"
    msg = _format_runner_failure(long, None)
    assert "final-cause" in msg
    assert msg.count("x") < 4000


def test_format_runner_failure_handles_empty_input() -> None:
    assert _format_runner_failure(None, None) == "(no output)"
    assert _format_runner_failure("", "") == "(no output)"


def test_format_runner_failure_combines_stderr_and_stdout() -> None:
    msg = _format_runner_failure("stderr-line", "stdout-line")
    assert "stderr-line" in msg
    assert "stdout-line" in msg


def test_runner_child_env_drops_app_secrets(monkeypatch) -> None:
    monkeypatch.setenv("UW_SCAN_API_KEY", "secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "secret")
    monkeypatch.setenv("UW_SCAN_DB_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-home")
    env = _runner_child_env()
    assert "UW_SCAN_API_KEY" not in env
    assert "MASSIVE_API_KEY" not in env
    assert "UW_SCAN_DB_PASSWORD" not in env
    assert env.get("CODEX_HOME") == "/tmp/codex-home"


def test_runner_child_env_preserves_path_and_locale(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    env = _runner_child_env()
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["LANG"] == "en_US.UTF-8"
```

- [ ] **Step 4.2: Run the tests — verify they fail**

Run: `uv run pytest tests/unit/worker/test_trade_insights_ai_runners_shared.py -v`
Expected: ImportError — the module doesn't exist yet.

- [ ] **Step 4.3: Create the shared runners module**

Create `src/uw_scan/worker/jobs/trade_insights_ai_runners.py`:

```python
"""Shared abstractions for Trade Insights AI provider runners.

Each provider (codex, claude) has its own runner module that implements the
AiProviderRunner Protocol. The worker tick dispatches via the RUNNERS registry
in trade_insights_ai.py — no if/else branching on provider.
"""
from __future__ import annotations

import os
from typing import Any, NamedTuple, Protocol


class TradeInsightsAiRunnerError(RuntimeError):
    """Controlled failure from any provider's CLI runner."""


class RunnerResult(NamedTuple):
    """What a runner returns on success."""

    outcome: dict[str, Any]
    """The structured JSON the model produced (already JSON-decoded)."""

    resolved_model: str
    """Canonical model ID the provider actually used (post-hoc capture).

    For Claude, comes from `envelope['model']`. For Codex, from the output
    envelope if exposed, else the configured value or a sentinel default.
    """


class AiProviderRunner(Protocol):
    """Interface every provider runner must satisfy."""

    name: str  # "codex" or "claude"

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> RunnerResult:
        ...


def _format_runner_failure(
    stderr: str | None,
    stdout: str | None,
    *,
    tail_chars: int = 1500,
) -> str:
    """Format provider stderr/stdout for an analysis row's error_message.

    Both `codex exec --output-schema` and `claude --print --json-schema` echo
    the prompt + banner to stderr as a side effect. When the provider fails,
    the human-readable cause (usage limit, auth, schema validation) lives at
    the END of the stream, not the start — keeping the first N chars is
    exactly the worst slice. This helper keeps the TAIL and lifts any
    `ERROR:` lines to the front.
    """
    stderr_clean = (stderr or "").strip()
    stdout_clean = (stdout or "").strip()
    combined = "\n".join(p for p in (stderr_clean, stdout_clean) if p)
    if not combined:
        return "(no output)"
    error_lines: dict[str, None] = {}
    for ln in combined.splitlines():
        stripped = ln.strip()
        if stripped.startswith(("ERROR:", "error:", "Error:")):
            error_lines.setdefault(stripped, None)
    tail = combined[-tail_chars:] if len(combined) > tail_chars else combined
    if error_lines:
        return "[errors] " + " | ".join(error_lines.keys()) + " | [tail] " + tail
    return tail


def _runner_child_env() -> dict[str, str]:
    """Allow-listed environment for any CLI runner subprocess.

    Forwards only neutral environment (PATH, locale, TMPDIR, CODEX_HOME) and
    drops every app secret (UW_SCAN_API_KEY, MASSIVE_API_KEY, *_DB_PASSWORD,
    ANTHROPIC_API_KEY, etc.). Both Codex and Claude work with this allow-list:
    Codex uses CODEX_HOME, Claude uses macOS keychain OAuth (no env var).
    """
    allowed_exact = {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "SHELL",
        "TERM",
        "TMPDIR",
    }
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in allowed_exact or key.startswith("LC_"):
            env[key] = value
    return env
```

- [ ] **Step 4.4: Run the tests — verify they pass**

Run: `uv run pytest tests/unit/worker/test_trade_insights_ai_runners_shared.py -v`
Expected: all 6 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add src/uw_scan/worker/jobs/trade_insights_ai_runners.py \
        tests/unit/worker/test_trade_insights_ai_runners_shared.py
git commit -m "feat(ai): shared runner protocol + _format_runner_failure + _runner_child_env"
```

---

## Task 5: Codex runner — extract to its own module

**Files:**
- Create: `src/uw_scan/worker/jobs/trade_insights_codex_runner.py`
- Modify: `src/uw_scan/worker/jobs/trade_insights_ai.py` (remove `run_codex_trade_insights_analysis`, `_format_codex_failure`, `_codex_child_env` — moved to runners or codex_runner)
- Modify / rename: `tests/unit/worker/test_trade_insights_ai_runner.py` → `tests/unit/worker/test_trade_insights_codex_runner.py`

- [ ] **Step 5.1: Rename the existing Codex runner test file**

Run: `git mv tests/unit/worker/test_trade_insights_ai_runner.py tests/unit/worker/test_trade_insights_codex_runner.py`
Expected: file is renamed, no test content changes yet.

- [ ] **Step 5.2: Update imports in the renamed test file**

In `tests/unit/worker/test_trade_insights_codex_runner.py`, change every occurrence of:

```python
from uw_scan.worker.jobs.trade_insights_ai import (
    TradeInsightsAiRunnerError,
    run_codex_trade_insights_analysis,
)
```

to:

```python
from uw_scan.worker.jobs.trade_insights_ai_runners import TradeInsightsAiRunnerError
from uw_scan.worker.jobs.trade_insights_codex_runner import CodexRunner

# Adapter helper for backwards compatibility within these tests:
def run_codex_trade_insights_analysis(*args, **kwargs):
    return CodexRunner().run(*args, **kwargs).outcome
```

- [ ] **Step 5.3: Update the subprocess mock patch path**

In the same file, change every `monkeypatch.setattr("uw_scan.worker.jobs.trade_insights_ai.subprocess.run", ...)` to:

```python
monkeypatch.setattr("uw_scan.worker.jobs.trade_insights_codex_runner.subprocess.run", ...)
```

- [ ] **Step 5.4: Run the renamed test file — verify it fails (import error)**

Run: `uv run pytest tests/unit/worker/test_trade_insights_codex_runner.py -v`
Expected: ImportError on `CodexRunner` (the runner module doesn't exist yet).

- [ ] **Step 5.5: Create the Codex runner module**

Create `src/uw_scan/worker/jobs/trade_insights_codex_runner.py`:

```python
"""Codex CLI runner — implements AiProviderRunner via local `codex exec`."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    AiProviderRunner,
    RunnerResult,
    TradeInsightsAiRunnerError,
    _format_runner_failure,
    _runner_child_env,
)


class CodexRunner:
    """Local Codex CLI runner. Reads keychain auth via CODEX_HOME."""

    name = "codex"

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> RunnerResult:
        with tempfile.TemporaryDirectory(prefix="trade-insights-codex-") as tmp:
            tmpdir = Path(tmp)
            schema_path = tmpdir / "schema.json"
            result_path = tmpdir / "result.json"
            schema_path.write_text(json.dumps(schema, sort_keys=True), encoding="utf-8")

            cmd = [
                "codex",
                "exec",
                "--ephemeral",
                "--sandbox", "read-only",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--cd", str(tmpdir),
            ]
            if model:
                cmd.extend(["--model", model])
            cmd.extend([
                "--output-schema", str(schema_path),
                "--output-last-message", str(result_path),
                "-",
            ])

            try:
                completed = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    env=_runner_child_env(),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise TradeInsightsAiRunnerError(
                    f"codex exec timed out after {timeout_seconds}s"
                ) from exc

            if completed.returncode != 0:
                detail = _format_runner_failure(completed.stderr, completed.stdout)
                raise TradeInsightsAiRunnerError(
                    f"codex exec failed with exit {completed.returncode}: {detail}"
                )
            if not result_path.exists():
                raise TradeInsightsAiRunnerError("codex exec did not write a final message")

            output_bytes = result_path.read_bytes()
            if len(output_bytes) > max_output_bytes:
                raise TradeInsightsAiRunnerError(
                    f"codex output exceeded {max_output_bytes} bytes"
                )
            try:
                parsed = json.loads(output_bytes.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise TradeInsightsAiRunnerError("codex output was not valid JSON") from exc
            if not isinstance(parsed, dict):
                raise TradeInsightsAiRunnerError("codex output JSON must be an object")
            return RunnerResult(outcome=parsed, resolved_model=model or "codex-default")
```

- [ ] **Step 5.6: Remove the moved code from `trade_insights_ai.py`**

In `src/uw_scan/worker/jobs/trade_insights_ai.py`, DELETE:
- The `class TradeInsightsAiRunnerError(RuntimeError)` definition (now in `trade_insights_ai_runners.py`)
- The `_format_codex_failure` function (now `_format_runner_failure` in runners module)
- The `_codex_child_env` function (now `_runner_child_env`)
- The `run_codex_trade_insights_analysis` function (now in `CodexRunner.run`)

Replace the imports block at the top with:

```python
"""Worker job for operator-triggered Trade Insights AI analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.trade_insights_ai import (
    PROMPT_VERSION,
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
    render_trade_insights_ai_markdown,
    trade_insights_ai_output_schema,
    validate_trade_insights_ai_outcome,
)
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.trade_insights_ai_runners import (
    AiProviderRunner,
    TradeInsightsAiRunnerError,
)
from uw_scan.worker.jobs.trade_insights_codex_runner import CodexRunner
```

(`ClaudeRunner` import and `RUNNERS` registry come in Task 7.)

In the existing `trade_insights_ai_tick(...)` body, replace the call:

```python
raw_outcome = run_codex_trade_insights_analysis(...)
```

with the temporary single-provider equivalent (Task 7 will replace this with `RUNNERS` dispatch):

```python
runner: AiProviderRunner = CodexRunner()
result = runner.run(
    build_trade_insights_ai_prompt(prompt_payload),
    trade_insights_ai_output_schema(),
    model=settings.trade_insights_ai_model.strip(),
    timeout_seconds=settings.trade_insights_ai_timeout_seconds,
    max_output_bytes=settings.trade_insights_ai_max_output_bytes,
)
raw_outcome = result.outcome
```

(Keep the rest of the tick exactly as-is for this task. Provider dispatch comes in Task 7.)

- [ ] **Step 5.7: Run the Codex runner tests — verify they pass**

Run: `uv run pytest tests/unit/worker/test_trade_insights_codex_runner.py -v`
Expected: all original Codex runner tests pass (under the new module).

- [ ] **Step 5.8: Verify the worker tick still passes its existing tests**

Run: `uv run pytest tests/integration/worker/ -v 2>&1 | tail -20` (or whichever directory holds the tick integration test).
Expected: existing tick tests pass — Codex is still the only provider wired up.

- [ ] **Step 5.9: Commit**

```bash
git add src/uw_scan/worker/jobs/trade_insights_codex_runner.py \
        src/uw_scan/worker/jobs/trade_insights_ai.py \
        tests/unit/worker/test_trade_insights_codex_runner.py
git commit -m "refactor(ai): extract CodexRunner to its own module with shared protocol"
```

---

## Task 6: Claude runner — new module

**Files:**
- Create: `src/uw_scan/worker/jobs/trade_insights_claude_runner.py`
- Create: `tests/unit/worker/test_trade_insights_claude_runner.py`

- [ ] **Step 6.1: Write the failing ClaudeRunner test file**

Create `tests/unit/worker/test_trade_insights_claude_runner.py`:

```python
"""Unit tests for ClaudeRunner — mirror of CodexRunner tests.

NOTE on output format: `claude --print --output-format json` returns a JSON
*array* of events: a `system/init` event (with `model`), zero or more
`assistant` events, and a final `result` event (with the stringified `result`
string and an `is_error` flag).
"""
from __future__ import annotations

import json
import subprocess

import pytest

from uw_scan.worker.jobs.trade_insights_ai_runners import TradeInsightsAiRunnerError
from uw_scan.worker.jobs.trade_insights_claude_runner import ClaudeRunner


def _success_stdout(result_payload: dict, model: str = "claude-opus-4-7") -> str:
    """Build a stdout array matching `claude --print --output-format json`."""
    return json.dumps([
        {
            "type": "system", "subtype": "init",
            "model": model, "session_id": "s", "apiKeySource": "oauth",
        },
        {
            "type": "result", "subtype": "success", "is_error": False,
            "result": json.dumps(result_payload),
            "model": model, "session_id": "s",
        },
    ])


SUCCESS_STDOUT = _success_stdout({"answer": "ok"})


def test_claude_runner_uses_print_mode_with_locked_down_flags(monkeypatch):
    captured = {}

    def fake_run(cmd, *, input, text, capture_output, timeout, env, check, cwd):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=SUCCESS_STDOUT, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    result = ClaudeRunner().run(
        "prompt text",
        {"type": "object"},
        model="opus",
        timeout_seconds=12,
        max_output_bytes=1024,
    )

    assert result.outcome == {"answer": "ok"}
    assert result.resolved_model == "claude-opus-4-7"

    cmd = captured["cmd"]
    assert cmd[:2] == ["claude", "--print"]
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--disable-slash-commands" in cmd
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == '{"mcpServers": {}}'
    assert "--no-session-persistence" in cmd
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "json"
    assert "--json-schema" in cmd
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert "--add-dir" in cmd


def test_claude_runner_omits_model_flag_when_blank(monkeypatch):
    captured = {}

    def fake_run(cmd, **_):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=SUCCESS_STDOUT, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    ClaudeRunner().run(
        "p", {"type": "object"}, model="", timeout_seconds=10, max_output_bytes=1024,
    )

    cmd = captured["cmd"]
    assert "--model" not in cmd


def test_claude_runner_resolved_model_falls_back_when_envelope_lacks_model(monkeypatch):
    # init event has no model field; result event has no model field either.
    arr = json.dumps([
        {"type": "system", "subtype": "init", "session_id": "s"},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": json.dumps({"ok": True}), "session_id": "s"},
    ])

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    r = ClaudeRunner().run(
        "p", {"type": "object"}, model="sonnet", timeout_seconds=10, max_output_bytes=1024,
    )
    assert r.resolved_model == "sonnet"


def test_claude_runner_resolved_model_falls_back_to_default_when_envelope_and_config_blank(monkeypatch):
    arr = json.dumps([
        {"type": "system", "subtype": "init", "session_id": "s"},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": json.dumps({"ok": True}), "session_id": "s"},
    ])

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    r = ClaudeRunner().run(
        "p", {"type": "object"}, model="", timeout_seconds=10, max_output_bytes=1024,
    )
    assert r.resolved_model == "claude-default"


def test_claude_runner_treats_is_error_true_as_failure_even_with_success_subtype(monkeypatch):
    """Verified-from-pre-flight regression: Claude returns subtype:'success'
    AND is_error:true for billing/API errors (e.g. 'Credit balance is too low').
    The runner MUST treat is_error:true as a failure regardless of subtype."""
    arr = json.dumps([
        {"type": "system", "subtype": "init", "model": "claude-opus-4-7"},
        {"type": "result", "subtype": "success", "is_error": True,
         "api_error_status": 400,
         "result": "Credit balance is too low", "model": "claude-opus-4-7"},
    ])

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="API error|Credit balance"):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=4096,
        )


def test_claude_runner_excludes_app_secrets_from_child_environment(monkeypatch):
    """ANTHROPIC_API_KEY exclusion is load-bearing — verified in pre-flight:
    with ANTHROPIC_API_KEY set, claude reports apiKeySource=ANTHROPIC_API_KEY
    and uses API-key billing instead of OAuth keychain (which is the user's
    Claude subscription). Stripping it forces fallback to keychain auth."""
    captured = {}
    monkeypatch.setenv("UW_SCAN_API_KEY", "secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "secret")
    monkeypatch.setenv("UW_SCAN_DB_PASSWORD", "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-too")
    monkeypatch.setenv("PATH", "/usr/bin")

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout=SUCCESS_STDOUT, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    ClaudeRunner().run(
        "p", {"type": "object"}, model="", timeout_seconds=10, max_output_bytes=1024,
    )

    env = captured["env"]
    assert "UW_SCAN_API_KEY" not in env
    assert "MASSIVE_API_KEY" not in env
    assert "UW_SCAN_DB_PASSWORD" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_claude_runner_timeout_raises_controlled_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="timed out"):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=1024,
        )


def test_claude_runner_nonzero_exit_raises_with_lifted_error(monkeypatch):
    stderr = ("OpenAI Codex banner...\n" + "echoed prompt\n" * 30 +
              "ERROR: Authentication failed.")

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr)

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError) as exc_info:
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=1024,
        )
    msg = str(exc_info.value)
    assert "claude --print failed with exit 1" in msg
    assert "[errors]" in msg
    assert "Authentication failed" in msg


def test_claude_runner_rejects_non_success_subtype(monkeypatch):
    arr = json.dumps([
        {"type": "system", "subtype": "init", "model": "x"},
        {"type": "result", "subtype": "error", "is_error": True, "message": "bad"},
    ])

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=4096,
        )


def test_claude_runner_rejects_stdout_not_array(monkeypatch):
    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout='{"single": "object"}', stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="expected JSON array"):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=1024,
        )


def test_claude_runner_rejects_missing_result_event(monkeypatch):
    """Stdout array has system+assistant but no result event — malformed."""
    arr = json.dumps([
        {"type": "system", "subtype": "init", "model": "x"},
        {"type": "assistant", "message": {}},
    ])

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="no result event"):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=1024,
        )


def test_claude_runner_rejects_malformed_stdout_json(monkeypatch):
    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="not valid JSON"):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=1024,
        )


def test_claude_runner_rejects_invalid_result_field(monkeypatch):
    arr = json.dumps([
        {"type": "system", "subtype": "init", "model": "x"},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "{not json", "model": "x"},
    ])

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=arr, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="result field was not valid JSON"):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=1024,
        )


def test_claude_runner_oversized_output_raises(monkeypatch):
    huge = _success_stdout({"data": "x" * 4096})

    def fake_run(cmd, **_):
        return subprocess.CompletedProcess(cmd, 0, stdout=huge, stderr="")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.trade_insights_claude_runner.subprocess.run",
        fake_run,
    )

    with pytest.raises(TradeInsightsAiRunnerError, match="exceeded"):
        ClaudeRunner().run(
            "p", {"type": "object"}, model="", timeout_seconds=1, max_output_bytes=1024,
        )
```

- [ ] **Step 6.2: Run the tests — verify they fail (import error)**

Run: `uv run pytest tests/unit/worker/test_trade_insights_claude_runner.py -v`
Expected: ImportError (ClaudeRunner module doesn't exist).

- [ ] **Step 6.3: Create the Claude runner module**

Create `src/uw_scan/worker/jobs/trade_insights_claude_runner.py`:

```python
"""Claude CLI runner — implements AiProviderRunner via `claude --print`.

Uses Claude Code's OAuth keychain auth (the operator's existing subscription).
Tools, slash-commands, MCP, session-persistence are all disabled so the
subprocess is pure prompt-in / JSON-out.

Verified pre-flight quirks (do NOT change unless re-verified):

- `--mcp-config '{"mcpServers": {}}'` is required; bare `'{}'` is rejected
  with "Invalid input: expected record, received undefined".
- `--output-format json` emits a JSON *array* of events, not a single envelope.
  Walk the array: extract `model` from the system/init event, extract `result`
  and `is_error` from the final result event.
- `is_error: true` can coexist with `subtype: "success"` (e.g. billing errors).
  Treat is_error as the ground truth.
- ANTHROPIC_API_KEY in the parent env overrides OAuth keychain (subscription
  auth) — _runner_child_env strips it.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from uw_scan.worker.jobs.trade_insights_ai_runners import (
    AiProviderRunner,
    RunnerResult,
    TradeInsightsAiRunnerError,
    _format_runner_failure,
    _runner_child_env,
)


class ClaudeRunner:
    """Local `claude --print` runner. Reads keychain OAuth (no env var)."""

    name = "claude"

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> RunnerResult:
        with tempfile.TemporaryDirectory(prefix="trade-insights-claude-") as tmp:
            tmpdir = Path(tmp)
            schema_json = json.dumps(schema, sort_keys=True)

            cmd = [
                "claude",
                "--print",
                "--tools", "",
                "--disable-slash-commands",
                "--strict-mcp-config",
                "--mcp-config", '{"mcpServers": {}}',
                "--no-session-persistence",
                "--output-format", "json",
                "--json-schema", schema_json,
                "--add-dir", str(tmpdir),
            ]
            if model:
                cmd.extend(["--model", model])

            try:
                completed = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    env=_runner_child_env(),
                    check=False,
                    cwd=str(tmpdir),
                )
            except subprocess.TimeoutExpired as exc:
                raise TradeInsightsAiRunnerError(
                    f"claude --print timed out after {timeout_seconds}s"
                ) from exc

            if completed.returncode != 0:
                detail = _format_runner_failure(completed.stderr, completed.stdout)
                raise TradeInsightsAiRunnerError(
                    f"claude --print failed with exit {completed.returncode}: {detail}"
                )

            stdout_bytes = completed.stdout.encode("utf-8")
            if len(stdout_bytes) > max_output_bytes:
                raise TradeInsightsAiRunnerError(
                    f"claude --print output exceeded {max_output_bytes} bytes"
                )

            try:
                events = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise TradeInsightsAiRunnerError(
                    "claude --print stdout was not valid JSON"
                ) from exc

            if not isinstance(events, list):
                raise TradeInsightsAiRunnerError(
                    "claude --print stdout expected JSON array of events"
                )

            init_event = next(
                (e for e in events
                 if isinstance(e, dict)
                 and e.get("type") == "system"
                 and e.get("subtype") == "init"),
                None,
            )
            result_event = None
            for e in reversed(events):
                if isinstance(e, dict) and e.get("type") == "result":
                    result_event = e
                    break

            if result_event is None:
                raise TradeInsightsAiRunnerError(
                    "claude --print returned no result event: "
                    f"{_format_runner_failure(None, completed.stdout)}"
                )

            if result_event.get("is_error") is True:
                raise TradeInsightsAiRunnerError(
                    "claude --print API error "
                    f"(status={result_event.get('api_error_status')}): "
                    f"{result_event.get('result') or result_event.get('message') or 'unknown'}"
                )
            if result_event.get("subtype") != "success":
                raise TradeInsightsAiRunnerError(
                    f"claude --print returned non-success subtype "
                    f"{result_event.get('subtype')!r}: "
                    f"{_format_runner_failure(None, completed.stdout)}"
                )

            result_str = result_event.get("result", "")
            try:
                parsed = json.loads(result_str)
            except json.JSONDecodeError as exc:
                raise TradeInsightsAiRunnerError(
                    "claude --print result field was not valid JSON"
                ) from exc

            if not isinstance(parsed, dict):
                raise TradeInsightsAiRunnerError(
                    "claude --print result was not a JSON object"
                )

            resolved = (
                (init_event or {}).get("model")
                or result_event.get("model")
                or (model if model else "claude-default")
            )
            return RunnerResult(outcome=parsed, resolved_model=resolved)
```

- [ ] **Step 6.4: Run the tests — verify they pass**

Run: `uv run pytest tests/unit/worker/test_trade_insights_claude_runner.py -v`
Expected: all 11 ClaudeRunner tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add src/uw_scan/worker/jobs/trade_insights_claude_runner.py \
        tests/unit/worker/test_trade_insights_claude_runner.py
git commit -m "feat(ai): ClaudeRunner — claude --print with locked-down tools/MCP, envelope parsing, resolved-model capture"
```

---

## Task 7: Worker tick — dispatch by row.provider

**Files:**
- Modify: `src/uw_scan/worker/jobs/trade_insights_ai.py:160-260` (tick body)
- Create: `tests/integration/worker/test_trade_insights_ai_tick_dispatch.py`

- [ ] **Step 7.1: Write failing dispatch tests**

Create `tests/integration/worker/test_trade_insights_ai_tick_dispatch.py`:

```python
"""Tests for provider-dispatching trade_insights_ai_tick."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from uw_scan.worker.jobs.trade_insights_ai import trade_insights_ai_tick
from uw_scan.worker.jobs.trade_insights_ai_runners import RunnerResult


@pytest.fixture
def fake_runners():
    """Patch RUNNERS registry so tests don't actually shell out to codex/claude."""
    codex_calls: list[str] = []
    claude_calls: list[str] = []

    class FakeCodex:
        name = "codex"
        def run(self, prompt, schema, *, model, timeout_seconds, max_output_bytes):
            codex_calls.append(prompt[:20])
            return RunnerResult(outcome={"x": 1}, resolved_model="codex-default")

    class FakeClaude:
        name = "claude"
        def run(self, prompt, schema, *, model, timeout_seconds, max_output_bytes):
            claude_calls.append(prompt[:20])
            return RunnerResult(outcome={"x": 1}, resolved_model="claude-opus-4-7")

    with patch.dict(
        "uw_scan.worker.jobs.trade_insights_ai.RUNNERS",
        {"codex": FakeCodex(), "claude": FakeClaude()},
        clear=True,
    ):
        yield codex_calls, claude_calls


def test_tick_dispatches_codex_row_to_codex_runner(
    settings, queued_codex_row, fake_runners
):
    codex_calls, claude_calls = fake_runners
    handled = trade_insights_ai_tick(settings, provider_filter="codex")
    assert handled is True
    assert len(codex_calls) == 1
    assert len(claude_calls) == 0


def test_tick_dispatches_claude_row_to_claude_runner(
    settings, queued_claude_row, fake_runners
):
    codex_calls, claude_calls = fake_runners
    handled = trade_insights_ai_tick(settings, provider_filter="claude")
    assert handled is True
    assert len(codex_calls) == 0
    assert len(claude_calls) == 1


def test_tick_with_codex_filter_skips_claude_rows(
    settings, queued_claude_row, fake_runners
):
    handled = trade_insights_ai_tick(settings, provider_filter="codex")
    assert handled is False  # nothing claimed


def test_tick_persists_resolved_model_from_runner(
    settings, queued_claude_row, fake_runners, repo
):
    trade_insights_ai_tick(settings, provider_filter="claude")
    row = repo.get_trade_insight_ai_analysis(queued_claude_row, ticker="TSLA")
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["model"] == "claude-opus-4-7"  # resolved, not configured


def test_tick_fails_row_with_unknown_provider(settings, queued_row_with_unknown_provider, fake_runners, repo):
    handled = trade_insights_ai_tick(settings, provider_filter=None)
    assert handled is True
    row = repo.get_trade_insight_ai_analysis(queued_row_with_unknown_provider, ticker="TSLA")
    assert row["status"] == "failed"
    assert "unknown provider" in (row["error_message"] or "").lower()
```

You'll need fixtures `settings`, `repo`, `queued_codex_row`, `queued_claude_row`, `queued_row_with_unknown_provider` in `tests/integration/worker/conftest.py`. Pattern (adapt the existing settings/repo fixtures from `tests/integration/conftest.py`):

```python
@pytest.fixture
def queued_codex_row(repo, postgresql) -> str:
    """Insert a queued codex row with the v4 prompt_version and return its id."""
    # Use repo.enqueue_trade_insight_ai_analysis with provider='codex'.
    # Also pre-set the row's analysis_input_jsonb / prompt_text / output_schema_jsonb
    # so the version-guard logic in the tick passes through. Adapt from the
    # existing fixture used by the prior single-provider tick test if one exists.
    ...
```

If no existing tick integration test exists yet, see the spec §12.2 for the expected fixture shape — the row needs `prompt_version='trade-insights-ai-v4'`, `analysis_input_jsonb={}` (or a minimal payload), and `provider` set as appropriate.

- [ ] **Step 7.2: Run the tests — verify they fail**

Run: `uv run pytest tests/integration/worker/test_trade_insights_ai_tick_dispatch.py -v`
Expected: tests fail with `AttributeError: module has no attribute 'RUNNERS'` or `TypeError: trade_insights_ai_tick() got an unexpected keyword argument 'provider_filter'`.

- [ ] **Step 7.3: Add RUNNERS registry + dispatch to `trade_insights_ai.py`**

In `src/uw_scan/worker/jobs/trade_insights_ai.py`, add at module scope (after imports):

```python
from uw_scan.worker.jobs.trade_insights_claude_runner import ClaudeRunner

RUNNERS: dict[str, AiProviderRunner] = {
    "codex": CodexRunner(),
    "claude": ClaudeRunner(),
}
```

Update `trade_insights_ai_tick` signature to accept the optional filter:

```python
def trade_insights_ai_tick(
    settings: Settings,
    *,
    provider_filter: str | None = None,
) -> bool:
```

Inside the function, where it calls `repo.claim_next_trade_insight_ai_analysis`, pass the filter through:

```python
row = repo.claim_next_trade_insight_ai_analysis(
    stale_running_before=stale_running_before,
    provider=provider_filter,
)
```

Replace the single-provider Codex call (the one added in Step 5.6) with the dispatch lookup:

```python
provider = row.get("provider", "codex")
runner = RUNNERS.get(provider)
if runner is None:
    _fail_analysis(settings, analysis_id, f"unknown provider {provider!r}")
    return True

# Choose model + timeout env var by provider.
if provider == "codex":
    model_env = settings.trade_insights_ai_model.strip()
    timeout = settings.trade_insights_ai_timeout_seconds
elif provider == "claude":
    model_env = settings.trade_insights_ai_claude_model.strip()
    timeout = settings.trade_insights_ai_claude_timeout_seconds
else:
    _fail_analysis(settings, analysis_id, f"unknown provider {provider!r}")
    return True

result = runner.run(
    build_trade_insights_ai_prompt(prompt_payload),
    trade_insights_ai_output_schema(),
    model=model_env,
    timeout_seconds=timeout,
    max_output_bytes=settings.trade_insights_ai_max_output_bytes,
)
outcome = validate_trade_insights_ai_outcome(
    result.outcome,
    prompt_payload,
    produced_at=produced_at,
)
markdown = render_trade_insights_ai_markdown(outcome)

repo = _repo(settings)
try:
    repo.complete_trade_insight_ai_analysis(
        analysis_id,
        outcome=outcome.model_dump(mode="json"),
        markdown=markdown,
        resolved_model=result.resolved_model,
    )
    repo.conn.commit()
finally:
    repo.conn.close()
```

(`settings.trade_insights_ai_claude_model` and `settings.trade_insights_ai_claude_timeout_seconds` are added in Task 8 — order is fine because Task 8 is the next step and the worker tick is not yet wired into the running scheduler with Claude rows.)

- [ ] **Step 7.4: Run the dispatch tests — partial pass expected**

Run: `uv run pytest tests/integration/worker/test_trade_insights_ai_tick_dispatch.py -v`
Expected: tests for the Codex path pass; Claude tests may fail with `AttributeError: 'Settings' has no attribute 'trade_insights_ai_claude_model'`. That's fine — Task 8 fixes this.

- [ ] **Step 7.5: Commit**

```bash
git add src/uw_scan/worker/jobs/trade_insights_ai.py \
        tests/integration/worker/test_trade_insights_ai_tick_dispatch.py \
        tests/integration/worker/conftest.py
git commit -m "feat(ai): worker tick dispatches via RUNNERS registry + provider_filter param"
```

---

## Task 8: Config — Claude env vars + flip default-enabled flags

`Settings` is a **Pydantic `BaseModel`**, not a `@dataclass`. Fields are declared as class attributes (`name: type = default`) and there's a `from_env()` classmethod that calls the Pydantic constructor with values pulled from `os.environ`. To flip the default to true, BOTH the class-attribute default AND the `from_env` default arg must change.

**Files:**
- Modify: `src/uw_scan/config.py:59` (`class Settings(BaseModel)` declaration), `:123` (`trade_insights_ai_enabled` field default), `:276` (`from_env` constructor)
- Test: `tests/unit/test_config_trade_insights_ai.py` (new file)

- [ ] **Step 8.1: Write failing config tests**

Create `tests/unit/test_config_trade_insights_ai.py`:

```python
from __future__ import annotations

from uw_scan.config import Settings


def test_trade_insights_ai_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("TRADE_INSIGHTS_AI_ENABLED", raising=False)
    settings = Settings.from_env()
    assert settings.trade_insights_ai_enabled is True


def test_trade_insights_ai_claude_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("TRADE_INSIGHTS_AI_CLAUDE_ENABLED", raising=False)
    settings = Settings.from_env()
    assert settings.trade_insights_ai_claude_enabled is True


def test_trade_insights_ai_claude_model_defaults_to_blank(monkeypatch):
    monkeypatch.delenv("TRADE_INSIGHTS_AI_CLAUDE_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.trade_insights_ai_claude_model == ""


def test_trade_insights_ai_claude_timeout_defaults_to_300(monkeypatch):
    monkeypatch.delenv("TRADE_INSIGHTS_AI_CLAUDE_TIMEOUT_SECONDS", raising=False)
    settings = Settings.from_env()
    assert settings.trade_insights_ai_claude_timeout_seconds == 300.0


def test_kill_switches_can_be_set_via_env(monkeypatch):
    monkeypatch.setenv("TRADE_INSIGHTS_AI_ENABLED", "false")
    monkeypatch.setenv("TRADE_INSIGHTS_AI_CLAUDE_ENABLED", "false")
    settings = Settings.from_env()
    assert settings.trade_insights_ai_enabled is False
    assert settings.trade_insights_ai_claude_enabled is False
```

- [ ] **Step 8.2: Run the tests — verify they fail**

Run: `uv run pytest tests/unit/test_config_trade_insights_ai.py -v`
Expected: failures — attributes don't exist; default for `trade_insights_ai_enabled` is currently False not True.

- [ ] **Step 8.3: Add Claude fields to the Pydantic Settings model**

In `src/uw_scan/config.py`, find `class Settings(BaseModel):` at line 59. Locate the existing `trade_insights_ai_enabled: bool = False` field at line 123 and **flip the default to `True`**. Add three new Claude fields immediately below it as class attributes (Pydantic v2 syntax — no `Field()` needed for simple defaults):

```python
    trade_insights_ai_enabled: bool = True   # flipped from False
    trade_insights_ai_model: str = ""
    trade_insights_ai_timeout_seconds: float = 300.0
    trade_insights_ai_max_output_bytes: int = 262144
    trade_insights_ai_poll_seconds: int = 3
    # NEW — Claude provider
    trade_insights_ai_claude_enabled: bool = True
    trade_insights_ai_claude_model: str = ""
    trade_insights_ai_claude_timeout_seconds: float = 300.0
```

Preserve the EXACT type annotations of the existing fields when copying — if a field already exists with a default, keep its current type annotation and only change the default value to `True`.

In the `Settings.from_env()` constructor (around line 276), find the existing `trade_insights_ai_enabled=_env_bool("TRADE_INSIGHTS_AI_ENABLED", False),` line. Change the default to `True` and add the Claude defaults:

```python
            trade_insights_ai_enabled=_env_bool("TRADE_INSIGHTS_AI_ENABLED", True),
            trade_insights_ai_model=os.environ.get("TRADE_INSIGHTS_AI_MODEL", ""),
            trade_insights_ai_timeout_seconds=float(
                os.environ.get("TRADE_INSIGHTS_AI_TIMEOUT_SECONDS", "300.0")
            ),
            trade_insights_ai_max_output_bytes=int(
                os.environ.get("TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES", "262144")
            ),
            trade_insights_ai_poll_seconds=int(
                os.environ.get("TRADE_INSIGHTS_AI_POLL_SECONDS", "3")
            ),
            trade_insights_ai_claude_enabled=_env_bool(
                "TRADE_INSIGHTS_AI_CLAUDE_ENABLED", True
            ),
            trade_insights_ai_claude_model=os.environ.get(
                "TRADE_INSIGHTS_AI_CLAUDE_MODEL", ""
            ),
            trade_insights_ai_claude_timeout_seconds=float(
                os.environ.get("TRADE_INSIGHTS_AI_CLAUDE_TIMEOUT_SECONDS", "300.0")
            ),
```

- [ ] **Step 8.4: Run the tests — verify they pass**

Run: `uv run pytest tests/unit/test_config_trade_insights_ai.py -v`
Expected: all 5 tests pass.

- [ ] **Step 8.5: Re-run the worker dispatch tests now that settings are available**

Run: `uv run pytest tests/integration/worker/test_trade_insights_ai_tick_dispatch.py -v`
Expected: all 5 dispatch tests pass.

- [ ] **Step 8.6: Update CLAUDE.md + AGENTS.md env-var docs**

In both `CLAUDE.md` and `AGENTS.md` at the repo root, find the existing Trade Insights AI env var section and extend it:

```markdown
- `TRADE_INSIGHTS_AI_ENABLED` — Codex kill switch; default true
- `TRADE_INSIGHTS_AI_MODEL` — optional Codex model alias; blank means local Codex default and rows store the resolved model id
- `TRADE_INSIGHTS_AI_TIMEOUT_SECONDS` — Codex subprocess timeout, default 300
- `TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES` — structured output cap, default 262144 (shared)
- `TRADE_INSIGHTS_AI_POLL_SECONDS` — worker polling interval, default 3 (shared)
- `TRADE_INSIGHTS_AI_CLAUDE_ENABLED` — Claude kill switch; default true
- `TRADE_INSIGHTS_AI_CLAUDE_MODEL` — optional Claude model alias; blank means Claude default and rows store the resolved model id from the envelope
- `TRADE_INSIGHTS_AI_CLAUDE_TIMEOUT_SECONDS` — Claude subprocess timeout, default 300
```

Also update the "Trade Insights AI (V1.5)" paragraph to read "Local Codex CLI and Claude CLI are the two model execution paths..." instead of "Local Codex CLI is the only model execution path..."

- [ ] **Step 8.7: Commit**

```bash
git add src/uw_scan/config.py CLAUDE.md AGENTS.md \
        tests/unit/test_config_trade_insights_ai.py
git commit -m "feat(ai): Claude config env vars + flip both AI providers to default-enabled"
```

---

## Task 9: API — POST returns paired stubs, /latest returns keyed dict

**Files:**
- Modify: `src/uw_scan/api/routers/trade_insights.py:118-265`
- Modify: `tests/integration/api/test_trade_insights_ai_endpoint.py` (extend/update existing tests — file is ~10KB and uses `_settings_for_repo(repo, enabled=...)` + `_client_for_settings(settings)` helpers + `get_repo`/`get_settings` dependency-override pattern; **preserve those helpers**, only update assertions)

- [ ] **Step 9.1: Update existing endpoint tests to assert the paired shape**

The existing file uses these patterns:
- `_settings_for_repo(repo, enabled=True)` returns a `Settings` via `Settings.from_env().model_copy(update={...})` — includes `trade_insights_ai_enabled` toggle
- `_client_for_settings(settings)` returns a `TestClient` with `get_repo`/`get_settings` deps overridden
- `_sample_outcome_for(...)` builds a v4 outcome dict

When updating tests, keep these helpers and call them the same way. Just change the assertions about response shape. Also extend `_settings_for_repo` to support `claude_enabled` if you need to toggle Claude per-test:

```python
def _settings_for_repo(repo, *, enabled: bool = True, claude_enabled: bool = True) -> Settings:
    return Settings.from_env().model_copy(
        update={
            "db_name": repo.conn.info.dbname,
            "db_schema": repo._schema,
            "trade_insights_ai_enabled": enabled,
            "trade_insights_ai_model": "",
            "trade_insights_ai_claude_enabled": claude_enabled,
            "trade_insights_ai_claude_model": "",
        }
    )
```

Add new test functions for the paired shape (keep existing tests, update their assertions to the new shape where applicable):

```python
def test_post_returns_one_stub_per_enabled_provider(client, repo):
    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})
    assert response.status_code == 202
    body = response.json()
    assert "analyses" in body
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"codex", "claude"}
    for stub in body["analyses"]:
        assert "analysis_id" in stub
        assert "status" in stub
        assert "reused" in stub
        assert "model" in stub


def test_post_skips_disabled_provider(client, repo, monkeypatch):
    monkeypatch.setenv("TRADE_INSIGHTS_AI_CLAUDE_ENABLED", "false")
    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})
    assert response.status_code == 202
    body = response.json()
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"codex"}  # claude omitted


def test_latest_returns_keyed_dict(client, repo):
    response = client.get("/api/stock/TSLA/trade-insights/ai-analysis/latest")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"codex", "claude"}


def test_latest_handles_both_missing_returns_200_with_nulls(client, repo):
    # No prior runs for ZZZZ
    response = client.get("/api/stock/ZZZZ/trade-insights/ai-analysis/latest")
    assert response.status_code == 200
    assert response.json() == {"codex": None, "claude": None}


def test_get_by_id_response_includes_provider_and_model(client, repo):
    post_body = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    a_id = post_body["analyses"][0]["analysis_id"]
    response = client.get(f"/api/stock/TSLA/trade-insights/ai-analysis/{a_id}")
    assert response.status_code == 200
    body = response.json()
    assert "provider" in body
    assert "model" in body
    assert body["provider"] in {"codex", "claude"}


def test_post_partial_reuse_codex_cached_claude_fresh(client, repo):
    """When codex has a succeeded row matching the input hash but claude doesn't,
    POST should return codex with reused=true and a fresh claude stub."""
    # First call — both fresh
    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    codex_stub_1 = next(a for a in first["analyses"] if a["provider"] == "codex")
    # Simulate codex completing without claude
    repo.complete_trade_insight_ai_analysis(
        codex_stub_1["analysis_id"], outcome={}, markdown="", resolved_model="codex-default",
    )
    repo.conn.commit()
    # Delete the queued claude row to simulate an environment where claude
    # hasn't succeeded yet.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {repo._schema}.trade_insight_ai_analyses "
            "WHERE ticker = 'TSLA' AND provider = 'claude'"
        )
    repo.conn.commit()
    second = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    codex_stub_2 = next(a for a in second["analyses"] if a["provider"] == "codex")
    claude_stub_2 = next(a for a in second["analyses"] if a["provider"] == "claude")
    assert codex_stub_2["reused"] is True
    assert codex_stub_2["status"] == "succeeded"
    assert claude_stub_2["reused"] is False
```

- [ ] **Step 9.2: Run the tests — verify they fail**

Run: `uv run pytest tests/integration/api/test_trade_insights_ai_endpoint.py -v`
Expected: failures — old single-row response shape vs new keyed/paired shape.

- [ ] **Step 9.3: Rewrite the POST handler**

In `src/uw_scan/api/routers/trade_insights.py`, replace the `post_trade_insights_ai_analysis` body. Use a small helper that handles one provider at a time:

```python
def _enqueue_one_provider(
    *,
    t: str,
    run_id: int,
    snapshot_id: int,
    trade_input_hash: str,
    analysis_hash: str,
    analysis_input: dict[str, Any],
    provider: str,
    model_label: str,
    force_rerun: bool,
    repo: Repository,
) -> dict[str, Any]:
    """Return the dict stub for one provider; reuses if available."""
    if not force_rerun:
        reused = repo.find_reusable_trade_insight_ai_analysis(
            ticker=t,
            analysis_input_hash=analysis_hash,
            prompt_version=PROMPT_VERSION,
            model=model_label,
            provider=provider,
        )
        if reused is not None:
            return {
                "provider": provider,
                "analysis_id": reused["analysis_id"],
                "status": reused["status"],
                "reused": True,
                "model": reused["model"],
            }
    analysis_id = repo.enqueue_trade_insight_ai_analysis(
        snapshot_id=snapshot_id, ticker=t, run_id=run_id,
        trade_insights_input_hash=trade_input_hash,
        analysis_input_hash=analysis_hash, analysis_input=analysis_input,
        prompt_version=PROMPT_VERSION, model=model_label, provider=provider,
    )
    row = repo.get_trade_insight_ai_analysis(analysis_id, ticker=t)
    assert row is not None
    return {
        "provider": provider, "analysis_id": analysis_id,
        "status": row["status"], "reused": False, "model": row["model"],
    }


@router.post(
    "/stock/{ticker}/trade-insights/ai-analysis",
    response_model=TradeInsightAiAnalysisEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_trade_insights_ai_analysis(
    ticker: str,
    request: TradeInsightAiAnalysisRequest | None = None,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TradeInsightAiAnalysisEnqueueResponse:
    t = ticker.upper()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        raise HTTPException(status_code=404, detail=f"no runs for {t}")
    if not (settings.trade_insights_ai_enabled or settings.trade_insights_ai_claude_enabled):
        raise HTTPException(status_code=503, detail="Trade Insights AI is disabled")

    force_rerun = bool(request.force_rerun) if request is not None else False
    trade_response, snapshot_id, trade_input_hash = _build_and_persist_trade_insights(t, repo)
    stock_report = assemble_single_stock_report(t, run_id, repo)
    stock_history = _build_stock_history_response(t, repo)
    backfill_status = (repo.get_volatility_backfill_status(t) or {}).get("status") or "ready"
    volatility = assemble_volatility_series(
        ticker=t, repo=repo, backfill_status=backfill_status, persist_derived=False,
    )
    analysis_input = build_trade_insights_ai_analysis_input(
        ticker=t, run_id=run_id, trade_insights_input_hash=trade_input_hash,
        trade_insights_payload=trade_response.model_dump(mode="json"),
        stock_report_payload=stock_report.model_dump(mode="json"),
        stock_history_payload=stock_history.model_dump(mode="json"),
        volatility_series_payload=volatility.model_dump(mode="json"),
    )
    analysis_hash = hash_trade_insights_ai_analysis_input(analysis_input)

    stubs: list[TradeInsightAiAnalysisStub] = []
    if settings.trade_insights_ai_enabled:
        model_label = settings.trade_insights_ai_model.strip() or "codex-default"
        stubs.append(TradeInsightAiAnalysisStub(**_enqueue_one_provider(
            t=t, run_id=run_id, snapshot_id=snapshot_id,
            trade_input_hash=trade_input_hash, analysis_hash=analysis_hash,
            analysis_input=analysis_input, provider="codex",
            model_label=model_label, force_rerun=force_rerun, repo=repo,
        )))
    if settings.trade_insights_ai_claude_enabled:
        model_label = settings.trade_insights_ai_claude_model.strip() or "claude-default"
        stubs.append(TradeInsightAiAnalysisStub(**_enqueue_one_provider(
            t=t, run_id=run_id, snapshot_id=snapshot_id,
            trade_input_hash=trade_input_hash, analysis_hash=analysis_hash,
            analysis_input=analysis_input, provider="claude",
            model_label=model_label, force_rerun=force_rerun, repo=repo,
        )))

    repo.conn.commit()
    return TradeInsightAiAnalysisEnqueueResponse(analyses=stubs)
```

- [ ] **Step 9.4: Rewrite the /latest handler**

Replace `get_latest_trade_insights_ai_analysis` with:

```python
@router.get(
    "/stock/{ticker}/trade-insights/ai-analysis/latest",
    response_model=TradeInsightAiLatestPair,
)
def get_latest_trade_insights_ai_analysis(
    ticker: str,
    repo: Repository = Depends(get_repo),
) -> TradeInsightAiLatestPair:
    pair = repo.find_latest_trade_insight_ai_analyses_per_provider(
        ticker=ticker.upper(),
        prompt_version=PROMPT_VERSION,
    )
    return TradeInsightAiLatestPair(
        codex=_row_to_ai_response(pair["codex"]) if pair["codex"] else None,
        claude=_row_to_ai_response(pair["claude"]) if pair["claude"] else None,
    )
```

- [ ] **Step 9.5: Update `_row_to_ai_response` to include provider + model**

Locate `_row_to_ai_response` (around line 118) and ensure the `TradeInsightAiAnalysisResponse(...)` call passes `provider=row["provider"]`. The `model` field is already populated from `row["model"]`.

- [ ] **Step 9.6: Run the API tests — verify they pass**

Run: `uv run pytest tests/integration/api/test_trade_insights_ai_endpoint.py -v`
Expected: all paired-API tests pass.

- [ ] **Step 9.7: Regenerate types**

Run: `cd web && npm run gen:types`
Expected: `web/lib/types.ts` updated; no errors. Verify with `git diff web/lib/types.ts | head -60` that the new `TradeInsightAiAnalysisEnqueueResponse` / `TradeInsightAiLatestPair` shapes appear and the POST/latest response paths reflect them.

- [ ] **Step 9.8: Commit**

```bash
git add src/uw_scan/api/routers/trade_insights.py \
        tests/integration/api/test_trade_insights_ai_endpoint.py \
        web/lib/types.ts
git commit -m "feat(ai): API returns paired stubs on POST + keyed pair on /latest"
```

---

## Task 10: Web client + Tab UI

**Files:**
- Modify: `web/lib/api.ts` (update existing `api.tradeInsightsAiAnalysis`, `api.tradeInsightsAiAnalysisLatest`, `api.tradeInsightsAiAnalysisStatus` return types)
- Create: `web/components/stock/panels/TradeInsightsAiTabs.tsx`
- Create: `web/components/stock/panels/TradeInsightsAiProviderView.tsx`
- Modify: `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx` (becomes a thin re-export of the tab component, or delete and update imports)
- Test: `web/components/stock/panels/TradeInsightsAiTabs.test.tsx`

- [ ] **Step 10.1: Update existing `api.tradeInsightsAiAnalysis*` methods in `web/lib/api.ts`**

The file exports an `api` object with methods that use an internal `_fetch<T>` helper (see file head around lines 1-50). Existing relevant methods (around lines 155-175):

- `api.tradeInsightsAiAnalysis(ticker, body)` — POST that currently returns `TradeInsightsAiAnalysisResponse`
- `api.tradeInsightsAiAnalysisStatus(ticker, analysisId)` — GET by id
- `api.tradeInsightsAiAnalysisLatest(ticker)` — GET /latest

The generated type `TradeInsightsAiAnalysisResponse` from `web/lib/types.ts` will (after Task 9.7's regen) reflect the NEW paired/keyed shapes — specifically:
- `Json<"/api/stock/{ticker}/trade-insights/ai-analysis", "post">` now resolves to the OpenAPI shape of `TradeInsightAiAnalysisEnqueueResponse` (which has `{analyses: [...]}`)
- `Json<"/api/stock/{ticker}/trade-insights/ai-analysis/latest", "get">` now resolves to `TradeInsightAiLatestPair` (which has `{codex, claude}`)

So in many cases the existing method signatures already point at the right generated types automatically. Add **new** type aliases near the top of `web/lib/api.ts` (alongside the existing `TradeInsightsAiAnalysisResponse` alias):

```typescript
type TradeInsightsAiAnalysisEnqueueResponse = Json<
  "/api/stock/{ticker}/trade-insights/ai-analysis",
  "post"
>;
type TradeInsightsAiLatestPair = Json<
  "/api/stock/{ticker}/trade-insights/ai-analysis/latest",
  "get"
>;
```

Update the existing three methods on the `api` object to use these new return types — keep the existing method names (`tradeInsightsAiAnalysis`, `tradeInsightsAiAnalysisStatus`, `tradeInsightsAiAnalysisLatest`):

```typescript
  tradeInsightsAiAnalysis: (
    ticker: string,
    body: { force_rerun?: boolean } = {},
  ): Promise<TradeInsightsAiAnalysisEnqueueResponse> =>
    _fetch<TradeInsightsAiAnalysisEnqueueResponse>(
      `/api/stock/${ticker}/trade-insights/ai-analysis`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  tradeInsightsAiAnalysisStatus: (
    ticker: string,
    analysisId: string,
  ): Promise<TradeInsightsAiAnalysisResponse> =>
    _fetch<TradeInsightsAiAnalysisResponse>(
      `/api/stock/${ticker}/trade-insights/ai-analysis/${analysisId}`,
    ),
  tradeInsightsAiAnalysisLatest: (
    ticker: string,
  ): Promise<TradeInsightsAiLatestPair> =>
    _fetch<TradeInsightsAiLatestPair>(
      `/api/stock/${ticker}/trade-insights/ai-analysis/latest`,
    ),
```

Also update the `export type { ... }` block at the bottom of the file to expose the new aliases so consumers can import them:

```typescript
export type {
  // ... existing exports ...
  TradeInsightsAiAnalysisEnqueueResponse,
  TradeInsightsAiLatestPair,
};
```

- [ ] **Step 10.2: Create `TradeInsightsAiProviderView.tsx`**

Create `web/components/stock/panels/TradeInsightsAiProviderView.tsx`. Lift the existing markdown + structured rendering logic from the current `TradeInsightsAiAnalysisPanel.tsx` body. The view receives:

```typescript
type Props = {
  provider: "codex" | "claude";
  latest: TradeInsightAiAnalysisResponse | null;
  pendingAnalysisId: string | null;
  ticker: string;
};
```

Behavior:
- If `pendingAnalysisId` is set AND `latest` exists → render `latest` body dimmed (opacity 0.5) with a spinner overlay.
- If `pendingAnalysisId` is set AND `latest` is null → render a spinner with text "Running… (<provider>)".
- If `latest?.status === 'failed'` → render the error_message body with a hint "Click Run again to retry this provider".
- If `latest?.status === 'succeeded'` → render existing markdown + outcome detail PLUS the footer line: `Generated by ${provider} (${latest.model}) · prompt ${latest.prompt_version} · ${shortDate(latest.produced_at)} · ${Math.round((finished - started)/1000)}s`.
- Otherwise (empty) → "Click Run to generate AI analysis for ${ticker}."

Use existing helpers from the current panel file: `tidy`, `shortDate`, `clipped`, `plainText`, `scoreText`, `SmallHeading`, `CompactNote`. Move them into the new file (or into a shared util file under `web/components/stock/panels/utils.ts`). Keep all CSS-in-JS styling identical to the current panel.

- [ ] **Step 10.3: Create `TradeInsightsAiTabs.tsx`**

Create `web/components/stock/panels/TradeInsightsAiTabs.tsx`:

```typescript
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  TradeInsightsAiAnalysisResponse,
  TradeInsightsAiLatestPair,
} from "@/lib/api";
import { TradeInsightsAiProviderView } from "./TradeInsightsAiProviderView";

type Provider = "codex" | "claude";
type LatestPair = TradeInsightsAiLatestPair;
type AnalysisResponse = TradeInsightsAiAnalysisResponse;

const PROVIDERS: Provider[] = ["codex", "claude"];
const POLL_MS = 3000;

function tabStateBadge(latest: AnalysisResponse | null, pendingId: string | null): string {
  if (pendingId) return "◐"; // running
  if (!latest) return "○"; // empty
  if (latest.status === "succeeded") return "●";
  if (latest.status === "failed") return "✕";
  return "○";
}

export function TradeInsightsAiTabs({ ticker }: { ticker: string }) {
  const [latest, setLatest] = useState<LatestPair>({ codex: null, claude: null });
  const [pending, setPending] = useState<Record<Provider, string | null>>({
    codex: null,
    claude: null,
  });
  const [active, setActive] = useState<Provider>("codex");
  const pollTimers = useRef<Record<Provider, number | null>>({ codex: null, claude: null });

  // Initial fetch
  useEffect(() => {
    api.tradeInsightsAiAnalysisLatest(ticker).then(setLatest).catch(console.error);
    return () => {
      for (const p of PROVIDERS) {
        const id = pollTimers.current[p];
        if (id != null) window.clearTimeout(id);
        pollTimers.current[p] = null;
      }
    };
  }, [ticker]);

  const pollOne = useCallback(
    (provider: Provider, analysisId: string) => {
      const tick = async () => {
        try {
          const row = await api.tradeInsightsAiAnalysisStatus(ticker, analysisId);
          if (row.status === "succeeded" || row.status === "failed") {
            // Terminal — refresh /latest and clear pending.
            const latestPair = await api.tradeInsightsAiAnalysisLatest(ticker);
            setLatest(latestPair);
            setPending((p) => ({ ...p, [provider]: null }));
            pollTimers.current[provider] = null;
          } else {
            pollTimers.current[provider] = window.setTimeout(tick, POLL_MS);
          }
        } catch (err) {
          console.error("AI poll failed", err);
          pollTimers.current[provider] = window.setTimeout(tick, POLL_MS);
        }
      };
      pollTimers.current[provider] = window.setTimeout(tick, POLL_MS);
    },
    [ticker],
  );

  const handleRun = useCallback(async () => {
    const resp = await api.tradeInsightsAiAnalysis(ticker);
    const newPending: Record<Provider, string | null> = { codex: null, claude: null };
    for (const stub of resp.analyses) {
      if (stub.status === "succeeded" && stub.reused) continue;
      newPending[stub.provider] = stub.analysis_id;
    }
    setPending(newPending);
    for (const p of PROVIDERS) {
      const id = newPending[p];
      if (id) pollOne(p, id);
    }
    // Refresh latest so any newly cached rows appear.
    api.tradeInsightsAiAnalysisLatest(ticker).then(setLatest).catch(console.error);
  }, [ticker, pollOne]);

  const anyPending = pending.codex !== null || pending.claude !== null;

  return (
    <section
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 12,
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", gap: 8 }}>
          {PROVIDERS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setActive(p)}
              style={{
                border: "1px solid var(--border-dim)",
                borderRadius: 4,
                background:
                  active === p ? "var(--bg-panel)" : "var(--bg-base)",
                color: "var(--text-primary)",
                cursor: "pointer",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                padding: "5px 10px",
              }}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}{" "}
              {tabStateBadge(latest[p], pending[p])}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={anyPending}
          style={{
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            background: anyPending ? "var(--bg-panel)" : "var(--bg-base)",
            color: anyPending ? "var(--text-muted)" : "var(--text-primary)",
            cursor: anyPending ? "not-allowed" : "pointer",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            padding: "7px 12px",
          }}
        >
          {anyPending ? "Running…" : "Run"}
        </button>
      </header>
      <TradeInsightsAiProviderView
        provider={active}
        latest={latest[active]}
        pendingAnalysisId={pending[active]}
        ticker={ticker}
      />
    </section>
  );
}
```

- [ ] **Step 10.4: Replace the existing panel**

Replace the entire body of `web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx` with a thin re-export so existing imports continue to work:

```typescript
"use client";
export { TradeInsightsAiTabs as TradeInsightsAiAnalysisPanel } from "./TradeInsightsAiTabs";
```

Or, if every caller is in your control, delete the file and update imports in the parent stock page (`web/app/stock/[ticker]/page.tsx` or the equivalent tab file under `web/app/stock/[ticker]/[tab]/page.tsx`) to import from `TradeInsightsAiTabs` directly. The re-export option is safer for a single-PR change.

- [ ] **Step 10.5: Write Vitest coverage**

Create `web/components/stock/panels/TradeInsightsAiTabs.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { TradeInsightsAiTabs } from "./TradeInsightsAiTabs";

vi.mock("@/lib/api", () => ({
  api: {
    tradeInsightsAiAnalysis: vi.fn(),
    tradeInsightsAiAnalysisLatest: vi.fn(),
    tradeInsightsAiAnalysisStatus: vi.fn(),
  },
}));

import { api } from "@/lib/api";

describe("TradeInsightsAiTabs", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders both tabs with empty dots when no data exists", async () => {
    (api.tradeInsightsAiAnalysisLatest as ReturnType<typeof vi.fn>).mockResolvedValue({
      codex: null,
      claude: null,
    });
    render(<TradeInsightsAiTabs ticker="TSLA" />);
    await waitFor(() => {
      expect(screen.getByText(/Codex ○/)).toBeTruthy();
      expect(screen.getByText(/Claude ○/)).toBeTruthy();
    });
  });

  it("renders succeeded dots when /latest returns both providers", async () => {
    (api.tradeInsightsAiAnalysisLatest as ReturnType<typeof vi.fn>).mockResolvedValue({
      codex: {
        analysis_id: "1", ticker: "TSLA", run_id: 1,
        trade_insights_input_hash: "", analysis_input_hash: "",
        model: "codex-default", provider: "codex",
        prompt_version: "trade-insights-ai-v4", status: "succeeded",
        requested_at: "2026-05-22T00:00:00Z", reused: false,
      },
      claude: {
        analysis_id: "2", ticker: "TSLA", run_id: 1,
        trade_insights_input_hash: "", analysis_input_hash: "",
        model: "claude-opus-4-7", provider: "claude",
        prompt_version: "trade-insights-ai-v4", status: "succeeded",
        requested_at: "2026-05-22T00:00:00Z", reused: false,
      },
    });
    render(<TradeInsightsAiTabs ticker="TSLA" />);
    await waitFor(() => {
      expect(screen.getByText(/Codex ●/)).toBeTruthy();
      expect(screen.getByText(/Claude ●/)).toBeTruthy();
    });
  });

  it("disables Run button while any provider is pending", async () => {
    (api.tradeInsightsAiAnalysisLatest as ReturnType<typeof vi.fn>).mockResolvedValue({
      codex: null, claude: null,
    });
    (api.tradeInsightsAiAnalysis as ReturnType<typeof vi.fn>).mockResolvedValue({
      analyses: [
        { provider: "codex", analysis_id: "1", status: "queued", reused: false, model: "codex-default" },
        { provider: "claude", analysis_id: "2", status: "queued", reused: false, model: "claude-default" },
      ],
    });
    (api.tradeInsightsAiAnalysisStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "running",
    });
    render(<TradeInsightsAiTabs ticker="TSLA" />);
    const runBtn = await screen.findByText("Run");
    runBtn.click();
    await waitFor(() => {
      expect(screen.getByText("Running…").hasAttribute("disabled")).toBe(true);
    });
  });

  it("cache-hit on both providers shows reused state without polling", async () => {
    (api.tradeInsightsAiAnalysisLatest as ReturnType<typeof vi.fn>).mockResolvedValue({
      codex: null, claude: null,
    });
    (api.tradeInsightsAiAnalysis as ReturnType<typeof vi.fn>).mockResolvedValue({
      analyses: [
        { provider: "codex", analysis_id: "1", status: "succeeded", reused: true, model: "codex-default" },
        { provider: "claude", analysis_id: "2", status: "succeeded", reused: true, model: "claude-opus-4-7" },
      ],
    });
    render(<TradeInsightsAiTabs ticker="TSLA" />);
    const runBtn = await screen.findByText("Run");
    runBtn.click();
    await waitFor(() => {
      expect(api.tradeInsightsAiAnalysisStatus).not.toHaveBeenCalled();
    });
  });
});
```

- [ ] **Step 10.6: Run web tests**

Run: `cd web && npm run test -- --run TradeInsightsAiTabs`
Expected: all 4 tests pass.

- [ ] **Step 10.7: Build the web bundle to catch type errors**

Run: `cd web && npm run build`
Expected: no TS errors. If type errors appear (likely from old single-provider `analysis_id` references in callers), fix them by updating the call site to use the new keyed/paired shape.

- [ ] **Step 10.8: Commit**

```bash
git add web/lib/api.ts \
        web/components/stock/panels/TradeInsightsAiAnalysisPanel.tsx \
        web/components/stock/panels/TradeInsightsAiTabs.tsx \
        web/components/stock/panels/TradeInsightsAiProviderView.tsx \
        web/components/stock/panels/TradeInsightsAiTabs.test.tsx
git commit -m "feat(ai): Codex/Claude tab UI with per-provider polling and Run button"
```

---

## Task 11: End-to-end smoke test (manual)

This is the regression-tested "smoke test goes through the real path" per [[deliver-results-through-the-real-worker-path]]. No /tmp side-channel scripts.

- [ ] **Step 11.1: Restart the dev stack**

Run: `bash scripts/dev.sh`
Expected: web on 3001, API on 8400, 2 UW workers, 2 massive workers, 2 AI workers (legacy `ai` role for Phase A), WS consumer. Confirm with `ps aux | grep scheduler` that the AI workers are running.

- [ ] **Step 11.2: Click Run on TSLA, observe both rows queue**

Open `http://localhost:3001/stock/TSLA` in a browser. Click Run. Inspect the network panel: the POST returns `{analyses: [{provider: "codex", ...}, {provider: "claude", ...}]}`. Both tabs show `◐` status dots.

In parallel, in a terminal:
```bash
psql -d option_wizard -c "
SELECT provider, status, model, started_at, finished_at, error_message IS NOT NULL as has_error
FROM uw_scan.trade_insight_ai_analyses
WHERE ticker = 'TSLA'
ORDER BY requested_at DESC LIMIT 4"
```
Expected: 2 fresh rows with `provider IN ('codex','claude')`, both `queued` → `running` → `succeeded` over ~60-120s.

- [ ] **Step 11.3: Verify both tabs render in browser**

After both rows succeed, the UI tabs should show `●` dots. Switch between Codex and Claude tabs — each renders the structured outcome with the v4 swing-HOLD prompt result. Verify the footer line shows:
- Codex tab: `Generated by codex (codex-default) · prompt trade-insights-ai-v4 · 2026-05-22 · ~Ns`
- Claude tab: `Generated by claude (claude-opus-4-7) · prompt trade-insights-ai-v4 · 2026-05-22 · ~Ns`

The Claude tab's model identifier should be the canonical resolved model (e.g. `claude-opus-4-7`), NOT the alias.

- [ ] **Step 11.4: Verify v4 prompt compliance**

In both tabs, the recommended expiry should be 28-45 DTE preferred (21-60 DTE allowed). Open the outcome detail and verify the entry DTE falls in this band. If either provider picks a DTE < 21 or > 60, the v4 prompt has a bug — STOP and investigate before continuing.

- [ ] **Step 11.5: Re-click Run, verify cache hit on both**

Click Run again on the same TSLA tab. The POST response should now show `reused: true` for both stubs. Check DB:
```bash
psql -d option_wizard -c "
SELECT count(*) FROM uw_scan.trade_insight_ai_analyses
WHERE ticker = 'TSLA' AND prompt_version = 'trade-insights-ai-v4'"
```
Expected: still 2 rows (no new rows enqueued). Network panel should show the cached `analysis_id`s.

- [ ] **Step 11.6: Verify per-provider cache invalidation by switching Claude model**

Set `TRADE_INSIGHTS_AI_CLAUDE_MODEL=sonnet` in the running dev environment (kill the stack, export the var, re-run `dev.sh`). Click Run again on TSLA.

Expected:
- Codex stub: `reused: true` (Codex model unchanged)
- Claude stub: `reused: false` (Claude model changed)
- A new Claude row enters `queued` status; the Codex row stays unchanged.

After Claude finishes, the Claude tab should show `Generated by claude (claude-sonnet-4-6) ...` (or whichever Sonnet model your subscription resolves to).

- [ ] **Step 11.7: Verify provider kill-switch**

Set `TRADE_INSIGHTS_AI_CLAUDE_ENABLED=false`, restart `dev.sh`, click Run. The POST response should have only one stub (codex). The Claude tab in the UI renders the `—` disabled placeholder.

- [ ] **Step 11.8: Stop the stack**

Run: `pkill -TERM concurrently` (or whatever runs `dev.sh`'s parent), then verify no orphan workers.

- [ ] **Step 11.9: Commit the smoke-test verification (no code changes — just a marker)**

If you maintain a CHANGELOG or release notes file, add a one-line entry:
```bash
git add CHANGELOG.md  # if exists
git commit -m "chore(ai): record end-to-end smoke test of Codex+Claude paired analysis"
```
If no CHANGELOG, skip this step.

---

# Phase B — Operational topology split (provider-pinned workers)

Phase B is functionally a no-op for the user — it changes how workers are organized, not what they do. The wins are operational: isolation under degradation and per-provider health visibility.

## Task 12: Repository — per-provider heartbeat keys

**Files:**
- Modify: `src/uw_scan/storage/repository.py` (`upsert_heartbeat` callers via tick — no repository change needed if heartbeat takes the key as a string)
- Modify: `src/uw_scan/worker/jobs/trade_insights_ai.py` (write a provider-specific heartbeat key)

- [ ] **Step 12.1: Update the tick to use provider-aware heartbeat key**

In `trade_insights_ai_tick`, replace:
```python
repo.upsert_heartbeat("trade_insights_ai_tick")
```
with:
```python
if provider_filter is None:
    repo.upsert_heartbeat("trade_insights_ai_tick")
else:
    repo.upsert_heartbeat(f"trade_insights_ai_tick_{provider_filter}")
```

- [ ] **Step 12.2: Commit**

```bash
git add src/uw_scan/worker/jobs/trade_insights_ai.py
git commit -m "feat(ai): per-provider heartbeat keys for split worker topology"
```

---

## Task 13: Scheduler — `ai-codex` / `ai-claude` / `ai` role routing

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py:340-580` (role dispatch)

- [ ] **Step 13.1: Add per-provider role dispatch**

In `src/uw_scan/worker/scheduler.py`, locate the existing role dispatch around line 347 (`_trade_insights_ai_tick` definition + `add_job` registration at line 568). Replace with role-aware versions:

```python
def _trade_insights_ai_tick_codex() -> None:
    trade_insights_ai_tick(settings, provider_filter="codex")

def _trade_insights_ai_tick_claude() -> None:
    trade_insights_ai_tick(settings, provider_filter="claude")

def _trade_insights_ai_tick_any() -> None:
    trade_insights_ai_tick(settings, provider_filter=None)
```

Locate the existing `if role in {"ai", "all"}:` branch (or similar). Refactor to:

```python
if role == "ai-codex":
    sched.add_job(
        _trade_insights_ai_tick_codex,
        trigger="interval",
        seconds=settings.trade_insights_ai_poll_seconds,
        id="trade_insights_ai_tick_codex",
    )
elif role == "ai-claude":
    sched.add_job(
        _trade_insights_ai_tick_claude,
        trigger="interval",
        seconds=settings.trade_insights_ai_poll_seconds,
        id="trade_insights_ai_tick_claude",
    )
elif role in {"ai", "all"}:
    sched.add_job(
        _trade_insights_ai_tick_any,
        trigger="interval",
        seconds=settings.trade_insights_ai_poll_seconds,
        id="trade_insights_ai_tick",
    )
```

Preserve every other `if role == "..."` branch exactly as it is — UW, massive, etc. only affect the AI block.

- [ ] **Step 13.2: Commit**

```bash
git add src/uw_scan/worker/scheduler.py
git commit -m "feat(ai): scheduler routes ai-codex / ai-claude roles to provider-pinned ticks"
```

---

## Task 14: dev.sh — split into 2 ai-codex + 2 ai-claude

**Files:**
- Modify: `scripts/dev.sh`

- [ ] **Step 14.1: Split AI worker invocations**

The current `scripts/dev.sh` uses `npx concurrently` with named processes and a `COUNTS` env var. The existing two `ai-0` and `ai-1` lines look like:

```bash
"$COUNTS $WS UW_SCAN_WORKER_ROLE=ai UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
"$COUNTS $WS UW_SCAN_WORKER_ROLE=ai UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
```

Replace those two lines with four (matching the exact existing `$COUNTS $WS ... UW_SCAN_WORKER_COUNT=...` shape):

```bash
"$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-codex  UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
"$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-codex  UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
"$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-claude UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
"$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-claude UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
```

Also update the `COUNTS` line so the API process and the new per-provider workers see the per-provider counts (used by Task 15's health panel):

```bash
COUNTS="UW_SCAN_UW_WORKER_COUNT=2 UW_SCAN_MASSIVE_WORKER_COUNT=2 UW_SCAN_AI_WORKER_COUNT=2 TRADE_INSIGHTS_AI_CODEX_WORKER_COUNT=2 TRADE_INSIGHTS_AI_CLAUDE_WORKER_COUNT=2"
```

And update the `-n` (names) and `-c` (colors) flags on the `concurrently` invocation to reflect 9 processes instead of 7. Existing labels include `ai-0,ai-1` — replace them with `ai-codex-0,ai-codex-1,ai-claude-0,ai-claude-1`. The new full line is:

```bash
exec npx --prefix web concurrently \
  -n next,api,uw-0,uw-1,massive-0,massive-1,ai-codex-0,ai-codex-1,ai-claude-0,ai-claude-1,massive-ws \
  -c cyan,green,yellow,magenta,blue,white,red,red,gray,gray,brightCyan \
  "cd web && npm run dev" \
  ...
```

Keep `UW_SCAN_AI_WORKER_COUNT=2` in `COUNTS` for now — it's a legacy hint used by the API's existing health-panel logic. Task 15 adds the per-provider keys.

- [ ] **Step 14.2: Run dev.sh and verify 4 AI workers are alive**

Run: `bash scripts/dev.sh`
Then in another terminal: `ps aux | grep 'uw_scan.worker.scheduler' | wc -l`
Expected: 6 (2 UW + 2 massive + 2 AI in PR-A) becomes 8 (2 UW + 2 massive + 4 AI in PR-B). Adjust for your actual baseline.

- [ ] **Step 14.3: Commit**

```bash
git add scripts/dev.sh
git commit -m "chore(dev): split AI worker pool into 2 ai-codex + 2 ai-claude"
```

---

## Task 15: Health endpoint — per-provider blocks

**Files:**
- Modify: `src/uw_scan/api/routers/health.py` (or wherever the existing `/api/health` lives)
- Add: `TRADE_INSIGHTS_AI_CODEX_WORKER_COUNT` and `TRADE_INSIGHTS_AI_CLAUDE_WORKER_COUNT` to `Settings` + `from_env`

- [ ] **Step 15.1: Add settings fields for the per-provider worker counts**

In `src/uw_scan/config.py`:

```python
    trade_insights_ai_codex_worker_count: int
    trade_insights_ai_claude_worker_count: int
```

In `from_env`:
```python
            trade_insights_ai_codex_worker_count=int(
                os.environ.get("TRADE_INSIGHTS_AI_CODEX_WORKER_COUNT", "2")
            ),
            trade_insights_ai_claude_worker_count=int(
                os.environ.get("TRADE_INSIGHTS_AI_CLAUDE_WORKER_COUNT", "2")
            ),
```

- [ ] **Step 15.2: Add per-provider blocks to `/api/health`**

Locate the existing `/api/health` handler in `src/uw_scan/api/routers/health.py`. Find where the existing `trade_insights_ai` block (if any) is computed. Replace or extend with a per-provider shape:

Use the existing `repo.get_heartbeat(job_name)` method (in `src/uw_scan/storage/health.py:248`). It returns `datetime | None` — None means the worker has never beaten. For "healthy" we treat the heartbeat as fresh if it's within `2 × poll_seconds + 60s` of now.

```python
from datetime import datetime, timedelta, timezone

def _ai_health_block(repo, settings) -> dict:
    """Per-provider AI worker health.

    NOTE: with provider-pinned workers, each `ai-codex` worker writes the
    heartbeat key `trade_insights_ai_tick_codex` and each `ai-claude` writes
    `trade_insights_ai_tick_claude`. A single shared key per provider is fine
    because workers within a pool race on the same DB row via UPSERT; healthiness
    is "at least one beat within the freshness window".
    """
    out = {}
    now = datetime.now(timezone.utc)
    fresh_window = timedelta(
        seconds=2 * settings.trade_insights_ai_poll_seconds + 60
    )
    for provider, count in (
        ("codex", settings.trade_insights_ai_codex_worker_count),
        ("claude", settings.trade_insights_ai_claude_worker_count),
    ):
        beat = repo.get_heartbeat(f"trade_insights_ai_tick_{provider}")
        # The heartbeat is shared across workers in the pool, so we can only
        # report "pool alive" (1) or "pool dead" (0), not exact worker counts.
        # For exact counts, future work could add per-worker-index heartbeat
        # keys; for v1 the binary signal matches the operator's actual concern.
        pool_alive = beat is not None and (now - beat) < fresh_window
        depth = repo.count_queued_trade_insight_ai_analyses_by_provider(provider)
        out[provider] = {
            "workers_expected": count,
            "workers_healthy": count if pool_alive else 0,
            "last_beat_at": beat.isoformat() if beat else None,
            "queued_depth": depth,
        }
    return out
```

Add this block under the `trade_insights_ai` key in the existing health response dict.

**Important:** Task 12's per-provider heartbeat-key change is REQUIRED for this to work. Verify Task 12 was applied (the tick writes `trade_insights_ai_tick_codex` / `trade_insights_ai_tick_claude` instead of just `trade_insights_ai_tick`).

- [ ] **Step 15.3: Add a small repo helper if needed**

In `src/uw_scan/storage/trade_insights_ai.py`:

```python
def count_queued_trade_insight_ai_analyses_by_provider(self, provider: str) -> int:
    with self._conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE provider = %s AND status IN ('queued', 'running')",
            (provider,),
        )
        return int(cur.fetchone()[0])
```

- [ ] **Step 15.4: Test the health surface**

Run: `curl http://localhost:8400/api/health | jq .trade_insights_ai`
Expected:
```json
{
  "codex":  { "workers_expected": 2, "workers_healthy": 2, "queued_depth": 0 },
  "claude": { "workers_expected": 2, "workers_healthy": 2, "queued_depth": 0 }
}
```

- [ ] **Step 15.5: Commit**

```bash
git add src/uw_scan/config.py \
        src/uw_scan/storage/trade_insights_ai.py \
        src/uw_scan/api/routers/health.py
git commit -m "feat(ai): /api/health surfaces per-provider worker count + queued depth"
```

---

## Task 16: Phase B end-to-end smoke test (manual)

- [ ] **Step 16.1: Run dev.sh, verify all 4 AI workers heartbeat**

Run: `bash scripts/dev.sh`, wait 10 seconds, then:
```bash
curl http://localhost:8400/api/health | jq .trade_insights_ai
```
Expected: both `codex.workers_healthy == 2` AND `claude.workers_healthy == 2`.

- [ ] **Step 16.2: Click Run on TSLA, verify provider-pinned dispatch**

Click Run on `http://localhost:3001/stock/TSLA`. Both rows queue. In the DB:
```bash
psql -d option_wizard -c "
SELECT provider, status, started_at
FROM uw_scan.trade_insight_ai_analyses
WHERE ticker = 'TSLA' ORDER BY requested_at DESC LIMIT 2"
```
Expected: both transition to `running` within ~3s of each other (two different workers in two different pools claim them simultaneously). Both succeed within ~60-120s.

- [ ] **Step 16.3: Verify isolation — kill the Claude pool, Codex keeps working**

`pkill -f 'WORKER_ROLE=ai-claude'`. Click Run on a different ticker (e.g. NVDA). Watch DB:
- The Codex row for NVDA transitions to `running` and completes normally.
- The Claude row for NVDA stays `queued` (no worker available).
- After ~60s, `/api/health` shows `claude.workers_healthy: 0`, `claude.queued_depth: 1`.

This demonstrates the isolation property described in spec §8.

- [ ] **Step 16.4: Restart the Claude pool and verify recovery**

Re-run `bash scripts/dev.sh` (or restart just the Claude workers). The queued Claude row gets claimed within ~3s and completes. Health surface returns to all-green.

---

# Final cleanup

## Task 17: Update memory + CLAUDE.md

- [ ] **Step 17.1: Update repo-root CLAUDE.md "Where to look first" table**

Add an entry under the existing trade-insights AI table reference:

```markdown
| Trade Insights AI — runners (codex + claude) | `src/uw_scan/worker/jobs/trade_insights_{ai_runners,codex_runner,claude_runner}.py` |
| Trade Insights AI — UI tabs | `web/components/stock/panels/TradeInsightsAi{Tabs,ProviderView}.tsx` |
```

- [ ] **Step 17.2: Commit + push branch**

```bash
git add CLAUDE.md
git commit -m "docs: add codex/claude runner + tabs panel to where-to-look-first table"
git push -u origin feat/trade-insights-ai-claude-provider
```

- [ ] **Step 17.3: Open the PR**

Run:
```bash
gh pr create --title "feat(ai): add Claude as second provider alongside Codex with side-by-side tabs" \
  --body "$(cat <<'EOF'
## Summary
- Migration 053 adds `provider` column to `trade_insight_ai_analyses` + extends cache-reuse indexes
- New `ClaudeRunner` shells out to `claude --print` with locked-down tools/MCP, uses OAuth keychain auth
- Shared `AiProviderRunner` Protocol + `RUNNERS` registry — extensible to a 3rd provider
- POST returns `{analyses: [stub_codex, stub_claude]}`; /latest returns `{codex: row|null, claude: row|null}`
- Web stock page gets `[Codex] [Claude]` tabs with independent per-provider polling
- Both providers default-enabled (`TRADE_INSIGHTS_AI_ENABLED=true`, `TRADE_INSIGHTS_AI_CLAUDE_ENABLED=true`)
- Phase B operational split (`ai-codex`/`ai-claude` worker roles) included

## Test plan
- [ ] Unit tests pass: `uv run pytest tests/unit/worker/`
- [ ] Repository integration tests pass: `uv run pytest tests/integration/storage/test_trade_insights_ai_repository.py`
- [ ] API integration tests pass: `uv run pytest tests/integration/api/test_trade_insights_ai_endpoint.py`
- [ ] Worker dispatch tests pass: `uv run pytest tests/integration/worker/test_trade_insights_ai_tick_dispatch.py`
- [ ] Vitest passes: `cd web && npm run test`
- [ ] End-to-end smoke per spec §12.5 / Task 11 of the plan
- [ ] Per-provider isolation smoke per Task 16

## Spec / Plan
- Spec: `docs/superpowers/archive/specs/2026-05-22-trade-insights-ai-claude-provider-design.md`
- Plan: `docs/superpowers/archive/plans/2026-05-22-trade-insights-ai-claude-provider.md`
EOF
)"
```

---

## Self-review checklist (run before declaring "done")

- [ ] All migrations idempotent (`IF NOT EXISTS` / `DROP ... IF EXISTS` everywhere)
- [ ] No `Co-Authored-By: Claude` trailer on any commit
- [ ] `claude` binary on PATH in dev environment (verified in pre-flight)
- [ ] OAuth keychain auth works (manual `claude --print` test in pre-flight)
- [ ] Both AI workers heartbeat in `/api/health`
- [ ] Both Codex and Claude tabs render in browser
- [ ] Resolved model captured post-hoc (e.g. `opus` alias → `claude-opus-4-7` in `model` column)
- [ ] Cache reuse works per-provider (changing Claude model invalidates Claude only)
- [ ] Worker version-guard still rejects rows with `prompt_version` ≠ "trade-insights-ai-v4"
- [ ] No /tmp side-channel scripts in the PR

---

**End of plan.**
