# UW Scan Data Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the data-side v1 gaps after the foundation plan: UW endpoint registry, audited request payloads, response normalization, complete v1 schema expansion, and capped request planning.

**Architecture:** Keep external IO behind small modules. The UW API client only fetches and fingerprints responses; audit helpers compress raw payloads; normalizers turn stringly UW payloads into typed rows; SQL migrations define relational query tables; the planner bounds request volume before live polling.

**Tech Stack:** Python 3.11+, uv, httpx, pydantic, pytest, psycopg 3, Postgres SQL migrations.

---

## Prerequisites

Complete `docs/superpowers/plans/2026-05-11-uw-scan-foundation-layout.md` first. Do not commit the Unusual Whales token; use `UW_SCAN_API_KEY` at runtime.

Keep all code in logical `src/uw_scan/` subpackages. Do not add top-level one-off scripts.

## Files

- Create: `src/uw_scan/api/__init__.py`
- Create: `src/uw_scan/api/endpoints.py`
- Create: `src/uw_scan/api/client.py`
- Create: `src/uw_scan/audit.py`
- Create: `src/uw_scan/normalize/__init__.py`
- Create: `src/uw_scan/normalize/options.py`
- Create: `src/uw_scan/storage/migrations/002_expand_v1_tables.sql`
- Create: `src/uw_scan/ingest/__init__.py`
- Create: `src/uw_scan/ingest/planner.py`
- Modify: `src/uw_scan/models.py`
- Test: `tests/test_api_client.py`
- Test: `tests/test_audit.py`
- Test: `tests/test_normalize_options.py`
- Test: `tests/test_repository_sql.py`
- Test: `tests/test_request_planner.py`

## Task 1: UW Endpoint Registry And Fingerprints

**Files:**
- Create: `src/uw_scan/api/__init__.py`
- Create: `src/uw_scan/api/endpoints.py`
- Create: `src/uw_scan/api/client.py`
- Test: `tests/test_api_client.py`

- [ ] **Step 1: Write endpoint tests**

Create `tests/test_api_client.py`:

```python
from uw_scan.api.client import build_request_fingerprint, normalize_params
from uw_scan.api.endpoints import UwEndpoint


def test_endpoint_paths_match_documented_operations():
    assert UwEndpoint.FLOW_ALERTS.path == "/api/option-trades/flow-alerts"
    assert UwEndpoint.FULL_TAPE.path == "/api/option-trades/full-tape/{date}"
    assert UwEndpoint.OPTION_CHAINS.path == "/api/stock/{ticker}/option-chains"
    assert UwEndpoint.OPTION_CONTRACTS.path == "/api/stock/{ticker}/option-contracts"
    assert UwEndpoint.OI_CHANGE.path == "/api/stock/{ticker}/oi-change"
    assert UwEndpoint.OI_PER_EXPIRY.path == "/api/stock/{ticker}/oi-per-expiry"
    assert UwEndpoint.OI_PER_STRIKE.path == "/api/stock/{ticker}/oi-per-strike"
    assert UwEndpoint.VOL_OI_PER_EXPIRY.path == "/api/stock/{ticker}/option/volume-oi-expiry"
    assert UwEndpoint.IV_RANK.path == "/api/stock/{ticker}/iv-rank"
    assert UwEndpoint.VOLATILITY_STATS.path == "/api/stock/{ticker}/volatility/stats"
    assert UwEndpoint.INTERPOLATED_IV.path == "/api/stock/{ticker}/interpolated-iv"
    assert UwEndpoint.REALIZED_VOLATILITY.path == "/api/stock/{ticker}/volatility/realized"
    assert UwEndpoint.IV_TERM_STRUCTURE.path == "/api/stock/{ticker}/volatility/term-structure"
    assert UwEndpoint.GREEKS.path == "/api/stock/{ticker}/greeks"
    assert UwEndpoint.GREEK_EXPOSURE_BY_STRIKE_EXPIRY.path == "/api/stock/{ticker}/greek-exposure/strike-expiry"
    assert UwEndpoint.SPOT_EXPOSURES_BY_STRIKE_EXPIRY.path == "/api/stock/{ticker}/spot-exposures/expiry-strike"
    assert UwEndpoint.MAX_PAIN.path == "/api/stock/{ticker}/max-pain"
    assert UwEndpoint.DARKPOOL_RECENT.path == "/api/darkpool/recent"
    assert UwEndpoint.DARKPOOL_TICKER.path == "/api/darkpool/{ticker}"


def test_normalize_params_sorts_keys_and_list_values():
    assert normalize_params({"b": "2", "a": ["NVDA", "AMD"], "empty": None}) == "a=AMD,NVDA&b=2"


def test_request_fingerprint_is_stable():
    first = build_request_fingerprint(
        endpoint="/api/stock/NVDA/option-contracts",
        params={"option_symbol": ["NVDA260619C00650000", "AMD260619C00210000"]},
        market_date="2026-05-11",
        api_base_url="https://api.unusualwhales.com",
    )
    second = build_request_fingerprint(
        endpoint="/api/stock/NVDA/option-contracts",
        params={"option_symbol": ["AMD260619C00210000", "NVDA260619C00650000"]},
        market_date="2026-05-11",
        api_base_url="https://api.unusualwhales.com",
    )
    assert first == second
    assert len(first) == 64
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_api_client.py -v`

Expected: FAIL with missing `uw_scan.api`.

- [ ] **Step 3: Implement endpoint registry**

Create `src/uw_scan/api/__init__.py`:

```python
"""Unusual Whales API helpers."""
```

Create `src/uw_scan/api/endpoints.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class EndpointDef:
    operation: str
    path: str
    docs_url: str


class UwEndpoint(Enum):
    FLOW_ALERTS = EndpointDef("flow_alerts", "/api/option-trades/flow-alerts", "https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts")
    FULL_TAPE = EndpointDef("full_tape", "/api/option-trades/full-tape/{date}", "https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.full_tape")
    OPTION_CHAINS = EndpointDef("option_chains", "/api/stock/{ticker}/option-chains", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.option_chains")
    OPTION_CONTRACTS = EndpointDef("option_contracts", "/api/stock/{ticker}/option-contracts", "https://api.unusualwhales.com/docs/operations/PublicApi.OptionContractController.option_contracts")
    OI_CHANGE = EndpointDef("oi_change", "/api/stock/{ticker}/oi-change", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_change")
    OI_PER_EXPIRY = EndpointDef("oi_per_expiry", "/api/stock/{ticker}/oi-per-expiry", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_per_expiry")
    OI_PER_STRIKE = EndpointDef("oi_per_strike", "/api/stock/{ticker}/oi-per-strike", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_per_strike")
    VOL_OI_PER_EXPIRY = EndpointDef("vol_oi_per_expiry", "/api/stock/{ticker}/option/volume-oi-expiry", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.vol_oi_per_expiry")
    IV_RANK = EndpointDef("iv_rank", "/api/stock/{ticker}/iv-rank", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.iv_rank")
    VOLATILITY_STATS = EndpointDef("volatility_stats", "/api/stock/{ticker}/volatility/stats", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.volatility_stats")
    INTERPOLATED_IV = EndpointDef("interpolated_iv", "/api/stock/{ticker}/interpolated-iv", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.interpolated_iv")
    REALIZED_VOLATILITY = EndpointDef("realized_volatility", "/api/stock/{ticker}/volatility/realized", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.realized_volatility")
    IV_TERM_STRUCTURE = EndpointDef("iv_term_structure", "/api/stock/{ticker}/volatility/term-structure", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.implied_volatility_term_structure")
    GREEKS = EndpointDef("greeks", "/api/stock/{ticker}/greeks", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greeks")
    GREEK_EXPOSURE_BY_STRIKE_EXPIRY = EndpointDef("greek_exposure_by_strike_expiry", "/api/stock/{ticker}/greek-exposure/strike-expiry", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greek_exposure_by_strike_expiry")
    SPOT_EXPOSURES_BY_STRIKE_EXPIRY = EndpointDef("spot_exposures_by_strike_expiry", "/api/stock/{ticker}/spot-exposures/expiry-strike", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.spot_exposures_by_strike_expiry_v2")
    MAX_PAIN = EndpointDef("max_pain", "/api/stock/{ticker}/max-pain", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.max_pain")
    DARKPOOL_RECENT = EndpointDef("darkpool_recent", "/api/darkpool/recent", "https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.darkpool_recent")
    DARKPOOL_TICKER = EndpointDef("darkpool_ticker", "/api/darkpool/{ticker}", "https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.darkpool_ticker")

    @property
    def operation(self) -> str:
        return self.value.operation

    @property
    def path(self) -> str:
        return self.value.path

    @property
    def docs_url(self) -> str:
        return self.value.docs_url
```

- [ ] **Step 4: Implement client helpers**

Create `src/uw_scan/api/client.py`:

```python
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx


def normalize_params(params: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(params):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(f"{key}={value}")
        elif isinstance(value, Sequence) and not isinstance(value, bytes):
            parts.append(f"{key}={','.join(sorted(str(item) for item in value if item is not None))}")
        else:
            parts.append(f"{key}={value}")
    return "&".join(parts)


def build_request_fingerprint(*, endpoint: str, params: Mapping[str, Any], market_date: str, api_base_url: str) -> str:
    raw = f"{api_base_url}|{endpoint}|{market_date}|{normalize_params(params)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UwApiResponse:
    endpoint: str
    params: dict[str, Any]
    status_code: int
    json_payload: Any
    latency_ms: int
    request_fingerprint: str


class UwApiClient:
    def __init__(self, *, api_key: str, base_url: str = "https://api.unusualwhales.com", timeout: float = 30.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, *, endpoint: str, params: Mapping[str, Any], market_date: str) -> UwApiResponse:
        fingerprint = build_request_fingerprint(
            endpoint=endpoint,
            params=params,
            market_date=market_date,
            api_base_url=self.base_url,
        )
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}{endpoint}",
                params={key: value for key, value in params.items() if value is not None},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        response.raise_for_status()
        return UwApiResponse(
            endpoint=endpoint,
            params=dict(params),
            status_code=response.status_code,
            json_payload=response.json(),
            latency_ms=int(response.elapsed.total_seconds() * 1000),
            request_fingerprint=fingerprint,
        )
```

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_api_client.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/api/__init__.py src/uw_scan/api/endpoints.py src/uw_scan/api/client.py tests/test_api_client.py
git commit -m "Add UW API endpoint registry"
```

## Task 2: Raw Payload Audit Helpers

**Files:**
- Create: `src/uw_scan/audit.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write audit tests**

Create `tests/test_audit.py`:

```python
from uw_scan.audit import compress_json_payload, sha256_text


def test_compress_json_payload_round_trip():
    encoded = compress_json_payload({"ticker": "NVDA", "value": "123.45"})
    assert encoded.content_encoding == "gzip"
    assert encoded.payload_size_bytes > 0
    assert encoded.decompressed_json() == {"ticker": "NVDA", "value": "123.45"}


def test_sha256_text_is_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abcd")
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_audit.py -v`

Expected: FAIL with missing `uw_scan.audit`.

- [ ] **Step 3: Implement audit helpers**

Create `src/uw_scan/audit.py`:

```python
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from typing import Any


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CompressedPayload:
    payload_compressed: bytes
    content_encoding: str
    content_sha256: str
    payload_size_bytes: int

    def decompressed_json(self) -> Any:
        return json.loads(gzip.decompress(self.payload_compressed).decode("utf-8"))


def compress_json_payload(payload: Any) -> CompressedPayload:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CompressedPayload(
        payload_compressed=gzip.compress(raw),
        content_encoding="gzip",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        payload_size_bytes=len(raw),
    )
```

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest tests/test_audit.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/audit.py tests/test_audit.py
git commit -m "Add raw payload audit helpers"
```

## Task 3: UW Option Normalizers

**Files:**
- Create: `src/uw_scan/normalize/__init__.py`
- Create: `src/uw_scan/normalize/options.py`
- Modify: `src/uw_scan/models.py`
- Test: `tests/test_normalize_options.py`

- [ ] **Step 1: Write normalizer tests**

Create `tests/test_normalize_options.py`:

```python
from decimal import Decimal

from uw_scan.normalize.options import normalize_oi_by_expiry, normalize_option_contract_snapshot, parse_decimal


def test_parse_decimal_preserves_nulls():
    assert parse_decimal(None) is None
    assert parse_decimal("") is None
    assert parse_decimal("123.45") == Decimal("123.45")


def test_normalize_option_contract_snapshot_maps_string_numbers():
    row = normalize_option_contract_snapshot(
        run_id="run-1",
        market_date="2026-05-11",
        fetched_at_utc="2026-05-11T14:00:00Z",
        payload={
            "option_symbol": "NVDA260619C00650000",
            "ticker": "NVDA",
            "expiry": "2026-06-19",
            "strike": "650",
            "option_type": "call",
            "implied_volatility": "0.54",
            "open_interest": "900",
            "prev_oi": "700",
            "volume": "2400",
            "premium": "1250000",
            "bid": "19.20",
            "ask": "19.80",
        },
    )
    assert row.option_symbol == "NVDA260619C00650000"
    assert row.strike == Decimal("650")
    assert row.mid == Decimal("19.50")
    assert row.open_interest == 900


def test_normalize_oi_by_expiry_maps_calls_and_puts():
    row = normalize_oi_by_expiry(
        run_id="run-1",
        ticker="NVDA",
        market_date="2026-05-11",
        fetched_at_utc="2026-05-11T14:00:00Z",
        payload={"expiry": "2026-06-19", "call_oi": "12000", "put_oi": "8000"},
    )
    assert row.call_open_interest == 12000
    assert row.put_open_interest == 8000
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_normalize_options.py -v`

Expected: FAIL with missing normalizer module or model classes.

- [ ] **Step 3: Add persistence models**

Append to `src/uw_scan/models.py`:

```python

class OptionContractSnapshot(BaseModel):
    run_id: str
    option_symbol: str
    ticker: str
    market_date: date
    fetched_at_utc: datetime
    expiry: date
    strike: Decimal
    option_type: str
    implied_volatility: Decimal | None = None
    open_interest: int | None = None
    previous_open_interest: int | None = None
    volume: int | None = None
    premium: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None


class OiByExpiryRow(BaseModel):
    run_id: str
    ticker: str
    market_date: date
    fetched_at_utc: datetime
    expiry: date
    call_open_interest: int | None = None
    put_open_interest: int | None = None
```

- [ ] **Step 4: Implement normalizers**

Create `src/uw_scan/normalize/__init__.py`:

```python
"""UW response normalizers."""
```

Create `src/uw_scan/normalize/options.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from uw_scan.models import OiByExpiryRow, OptionContractSnapshot


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(Decimal(str(value)))


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_option_contract_snapshot(*, run_id: str, market_date: str, fetched_at_utc: str, payload: dict[str, Any]) -> OptionContractSnapshot:
    bid = parse_decimal(payload.get("bid"))
    ask = parse_decimal(payload.get("ask"))
    mid = (bid + ask) / Decimal("2") if bid is not None and ask is not None else None
    return OptionContractSnapshot(
        run_id=run_id,
        option_symbol=str(payload["option_symbol"]),
        ticker=str(payload["ticker"]).upper(),
        market_date=parse_date(market_date),
        fetched_at_utc=parse_datetime(fetched_at_utc),
        expiry=parse_date(str(payload["expiry"])),
        strike=parse_decimal(payload["strike"]) or Decimal("0"),
        option_type=str(payload["option_type"]).lower(),
        implied_volatility=parse_decimal(payload.get("implied_volatility")),
        open_interest=parse_int(payload.get("open_interest")),
        previous_open_interest=parse_int(payload.get("prev_oi") or payload.get("previous_open_interest")),
        volume=parse_int(payload.get("volume")),
        premium=parse_decimal(payload.get("premium")),
        bid=bid,
        ask=ask,
        mid=mid,
    )


def normalize_oi_by_expiry(*, run_id: str, ticker: str, market_date: str, fetched_at_utc: str, payload: dict[str, Any]) -> OiByExpiryRow:
    return OiByExpiryRow(
        run_id=run_id,
        ticker=ticker.upper(),
        market_date=parse_date(market_date),
        fetched_at_utc=parse_datetime(fetched_at_utc),
        expiry=parse_date(str(payload["expiry"])),
        call_open_interest=parse_int(payload.get("call_oi") or payload.get("call_open_interest")),
        put_open_interest=parse_int(payload.get("put_oi") or payload.get("put_open_interest")),
    )
```

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_normalize_options.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/models.py src/uw_scan/normalize/__init__.py src/uw_scan/normalize/options.py tests/test_normalize_options.py
git commit -m "Add UW option normalizers"
```

## Task 4: Full V1 Schema Expansion

**Files:**
- Create: `src/uw_scan/storage/migrations/002_expand_v1_tables.sql`
- Test: `tests/test_repository_sql.py`

- [ ] **Step 1: Write schema tests**

Create `tests/test_repository_sql.py`:

```python
from pathlib import Path


MIGRATION = Path("src/uw_scan/storage/migrations/002_expand_v1_tables.sql")


def test_v1_expansion_creates_missing_design_tables():
    sql = MIGRATION.read_text()
    for table in [
        "flow_events",
        "option_surface_snapshots",
        "exposures_by_expiry_strike",
        "oi_by_strike",
        "oi_change_events",
        "iv_rank_history",
        "iv_term_snapshots",
        "interpolated_iv_snapshots",
        "realized_volatility_history",
        "risk_reversal_skew_history",
        "max_pain_by_expiry",
        "dark_pool_events",
        "short_interest_snapshots",
        "tracked_items",
        "tracking_observations",
        "structure_ideas",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS uw_scan.{table}" in sql


def test_v1_expansion_records_schema_version():
    assert "002_expand_v1_tables" in MIGRATION.read_text()
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_repository_sql.py -v`

Expected: FAIL because migration file does not exist.

- [ ] **Step 3: Create migration**

Create `src/uw_scan/storage/migrations/002_expand_v1_tables.sql`:

```sql
CREATE TABLE IF NOT EXISTS uw_scan.flow_events (
    flow_event_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    option_symbol TEXT NOT NULL,
    event_timestamp_utc TIMESTAMPTZ,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    market_date DATE NOT NULL,
    side TEXT,
    premium NUMERIC,
    volume INTEGER,
    open_interest INTEGER,
    ask_side_pct NUMERIC,
    UNIQUE (run_id, option_symbol, event_timestamp_utc, premium, volume)
);

CREATE TABLE IF NOT EXISTS uw_scan.option_surface_snapshots (
    option_surface_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    page_number INTEGER NOT NULL,
    row_count INTEGER NOT NULL,
    complete BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (run_id, ticker, market_date, expiry, page_number)
);

CREATE TABLE IF NOT EXISTS uw_scan.exposures_by_expiry_strike (
    exposure_row_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    strike NUMERIC NOT NULL,
    delta_exposure NUMERIC,
    gamma_exposure NUMERIC,
    vanna_exposure NUMERIC,
    charm_exposure NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry, strike)
);

CREATE TABLE IF NOT EXISTS uw_scan.oi_by_strike (
    oi_by_strike_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    strike NUMERIC NOT NULL,
    call_open_interest INTEGER,
    put_open_interest INTEGER,
    UNIQUE (run_id, ticker, market_date, strike)
);

CREATE TABLE IF NOT EXISTS uw_scan.oi_change_events (
    oi_change_event_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    option_symbol TEXT NOT NULL,
    ticker TEXT NOT NULL,
    oi_change_date DATE NOT NULL,
    open_interest INTEGER,
    previous_open_interest INTEGER,
    open_interest_change INTEGER,
    UNIQUE (run_id, option_symbol, oi_change_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.iv_rank_history (
    iv_rank_history_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    iv_rank NUMERIC,
    implied_volatility NUMERIC,
    realized_volatility NUMERIC,
    UNIQUE (ticker, market_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.iv_term_snapshots (
    iv_term_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    dte INTEGER,
    implied_volatility NUMERIC,
    implied_move NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry)
);

CREATE TABLE IF NOT EXISTS uw_scan.interpolated_iv_snapshots (
    interpolated_iv_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    dte_bucket INTEGER NOT NULL,
    implied_volatility NUMERIC,
    percentile NUMERIC,
    implied_move NUMERIC,
    UNIQUE (run_id, ticker, market_date, dte_bucket)
);

CREATE TABLE IF NOT EXISTS uw_scan.realized_volatility_history (
    realized_volatility_history_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    window TEXT NOT NULL,
    realized_volatility NUMERIC,
    underlying_price NUMERIC,
    UNIQUE (ticker, market_date, window)
);

CREATE TABLE IF NOT EXISTS uw_scan.risk_reversal_skew_history (
    risk_reversal_skew_history_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry DATE NOT NULL,
    delta NUMERIC NOT NULL,
    put_volatility NUMERIC,
    call_volatility NUMERIC,
    skew_magnitude NUMERIC,
    UNIQUE (ticker, market_date, expiry, delta)
);

CREATE TABLE IF NOT EXISTS uw_scan.max_pain_by_expiry (
    max_pain_by_expiry_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    max_pain NUMERIC,
    spot_price NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry)
);

CREATE TABLE IF NOT EXISTS uw_scan.dark_pool_events (
    dark_pool_event_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    event_timestamp_utc TIMESTAMPTZ,
    price NUMERIC,
    premium NUMERIC,
    size INTEGER,
    venue TEXT
);

CREATE TABLE IF NOT EXISTS uw_scan.short_interest_snapshots (
    short_interest_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    short_interest_pct_float NUMERIC,
    utilization NUMERIC,
    days_to_cover NUMERIC,
    cost_to_borrow NUMERIC,
    UNIQUE (run_id, ticker, market_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.tracked_items (
    tracked_item_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    option_symbol TEXT,
    expiry DATE,
    tracking_kind TEXT NOT NULL,
    source_run_id TEXT REFERENCES uw_scan.scan_runs(run_id),
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS uw_scan.tracking_observations (
    tracking_observation_id BIGSERIAL PRIMARY KEY,
    tracked_item_id BIGINT NOT NULL REFERENCES uw_scan.tracked_items(tracked_item_id),
    observed_at_utc TIMESTAMPTZ NOT NULL,
    metric_family TEXT NOT NULL,
    iv_change NUMERIC,
    oi_change INTEGER,
    reconciliation_status TEXT,
    UNIQUE (tracked_item_id, observed_at_utc, metric_family)
);

CREATE TABLE IF NOT EXISTS uw_scan.structure_ideas (
    structure_idea_id BIGSERIAL PRIMARY KEY,
    opportunity_score_id BIGINT NOT NULL REFERENCES uw_scan.opportunity_scores(opportunity_score_id),
    structure_type TEXT NOT NULL,
    rationale TEXT NOT NULL,
    invalidation TEXT NOT NULL,
    max_risk_note TEXT NOT NULL DEFAULT 'Sizing deferred',
    UNIQUE (opportunity_score_id, structure_type)
);

INSERT INTO uw_scan.schema_versions (version)
VALUES ('002_expand_v1_tables')
ON CONFLICT (version) DO NOTHING;
```

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest tests/test_repository_sql.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/storage/migrations/002_expand_v1_tables.sql tests/test_repository_sql.py
git commit -m "Expand uw_scan v1 schema"
```

## Task 5: Capped Request Planner

**Files:**
- Create: `src/uw_scan/ingest/__init__.py`
- Create: `src/uw_scan/ingest/planner.py`
- Test: `tests/test_request_planner.py`

- [ ] **Step 1: Write planner tests**

Create `tests/test_request_planner.py`:

```python
from uw_scan.config import UwScanConfig
from uw_scan.ingest.planner import SourceCandidate, build_call_plan


def test_call_plan_dedupes_tickers_and_respects_cap():
    config = UwScanConfig(max_requests_per_cycle=20, max_deep_surface_tickers=2)
    candidates = [
        SourceCandidate(ticker="NVDA", option_symbol="NVDA260619C00650000", source_label="UW"),
        SourceCandidate(ticker="NVDA", option_symbol="NVDA260619C00650000", source_label="TV"),
        SourceCandidate(ticker="AMD", option_symbol=None, source_label="TV"),
    ]
    plan = build_call_plan(candidates, market_date="2026-05-11", config=config)
    assert plan.total_requests <= 20
    assert plan.unique_tickers == ["AMD", "NVDA"]
    assert plan.unique_option_symbols == ["NVDA260619C00650000"]


def test_call_plan_marks_truncated_when_cap_exceeded():
    config = UwScanConfig(max_requests_per_cycle=5)
    candidates = [SourceCandidate(ticker=f"T{idx}", option_symbol=None, source_label="TV") for idx in range(10)]
    plan = build_call_plan(candidates, market_date="2026-05-11", config=config)
    assert plan.truncated is True
    assert plan.total_requests == 5
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_request_planner.py -v`

Expected: FAIL with missing ingest planner.

- [ ] **Step 3: Implement planner**

Create `src/uw_scan/ingest/__init__.py`:

```python
"""Polling and snapshot ingest orchestration."""
```

Create `src/uw_scan/ingest/planner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from uw_scan.config import UwScanConfig


@dataclass(frozen=True)
class SourceCandidate:
    ticker: str
    option_symbol: str | None
    source_label: str


@dataclass(frozen=True)
class PlannedCall:
    tier: str
    endpoint_name: str
    ticker: str | None = None
    option_symbol: str | None = None


@dataclass(frozen=True)
class CallPlan:
    market_date: str
    unique_tickers: list[str]
    unique_option_symbols: list[str]
    calls: list[PlannedCall]
    total_requests: int
    truncated: bool


def build_call_plan(candidates: list[SourceCandidate], *, market_date: str, config: UwScanConfig) -> CallPlan:
    tickers = sorted({candidate.ticker.upper() for candidate in candidates})
    option_symbols = sorted({candidate.option_symbol for candidate in candidates if candidate.option_symbol})
    calls: list[PlannedCall] = [
        PlannedCall(tier="discovery", endpoint_name="flow_alerts"),
        PlannedCall(tier="discovery", endpoint_name="tradingview_import"),
    ]
    for symbol in option_symbols:
        calls.append(PlannedCall(tier="tracking", endpoint_name="option_contracts", option_symbol=symbol))
    for ticker in tickers[: config.max_watchlist_tickers]:
        calls.extend(
            [
                PlannedCall(tier="enrichment", endpoint_name="option_chains", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="option_contracts", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="oi_change", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="oi_per_expiry", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="oi_per_strike", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="vol_oi_per_expiry", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="max_pain", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="iv_rank", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="volatility_stats", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="interpolated_iv", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="realized_volatility", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="iv_term_structure", ticker=ticker),
            ]
        )
    for ticker in tickers[: config.max_deep_surface_tickers]:
        calls.extend(
            [
                PlannedCall(tier="deep_surface", endpoint_name="greeks", ticker=ticker),
                PlannedCall(tier="deep_surface", endpoint_name="greek_exposure_by_strike_expiry", ticker=ticker),
                PlannedCall(tier="deep_surface", endpoint_name="spot_exposures_by_strike_expiry", ticker=ticker),
            ]
        )
    truncated = len(calls) > config.max_requests_per_cycle
    calls = calls[: config.max_requests_per_cycle]
    return CallPlan(
        market_date=market_date,
        unique_tickers=tickers,
        unique_option_symbols=option_symbols,
        calls=calls,
        total_requests=len(calls),
        truncated=truncated,
    )
```

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest tests/test_request_planner.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/ingest/__init__.py src/uw_scan/ingest/planner.py tests/test_request_planner.py
git commit -m "Add capped request planner"
```

## Plan Self-Review Checklist

- Spec coverage: Covers data-side gaps from the design: live endpoint registry, request fingerprints, raw payload compression, normalizers, full schema expansion, and capped request planning.
- Required remaining v1 scope: opportunity scoring, structure ideas, tracking reconciliation, snapshot replay wiring, and Streamlit live-mode wiring are covered by `2026-05-11-uw-scan-opportunity-layer.md`.
- Red-flag scan: No secret token is included. The plan uses `UW_SCAN_API_KEY` only as an environment variable name.
- Execution gate: Run only after the foundation/layout plan passes.
