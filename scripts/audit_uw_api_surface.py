"""Audit the live Unusual Whales API surface against the OpenAPI spec.

The script intentionally stores metadata only: status codes, entitlement
signals, parameter samples, response shape summaries, and short error messages.
It does not persist raw payloads or the API key.

Usage:
    uv run python scripts/audit_uw_api_surface.py --live
    uv run python scripts/audit_uw_api_surface.py --live --spec-url https://api.unusualwhales.com/api/openapi
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC_PATH = REPO_ROOT / "docs" / "uw-samples" / "unusual_whales_api_spec.yaml"
DEFAULT_JSON_OUT = REPO_ROOT / "docs" / "uw-samples" / "uw_api_capability_audit.json"
DEFAULT_MD_OUT = REPO_ROOT / "docs" / "uw-samples" / "uw_api_capability_audit.md"
DEFAULT_BASE_URL = "https://api.unusualwhales.com"
DEFAULT_SPEC_URL = "https://api.unusualwhales.com/api/openapi"

SAMPLE_STOCK = "TSLA"
SAMPLE_ETF = "SPY"
SAMPLE_COMPARISON = "AAPL"
SAMPLE_INSTITUTION = "Berkshire Hathaway Inc"
SAMPLE_SECTOR = "Technology"
SAMPLE_FLOW_GROUP = "all"
SAMPLE_COMMODITY = "wti"
SAMPLE_ECONOMY_INDICATOR = "cpi"
SAMPLE_POLITICIAN_ID = "e138f347-ae92-4cfb-8f41-7036ff09a213"
DEFAULT_OPTION_SYMBOL = "TSLA260515C00400000"


@dataclass(frozen=True)
class SampleContext:
    market_date: str
    start_date: str
    expiry: str
    iso_newer_than: str
    iso_older_than: str
    option_symbol: str
    flow_alert_id: str
    prediction_asset_id: str


def previous_weekday(today: date) -> date:
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def next_friday(today: date) -> date:
    days_ahead = (4 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def env_file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def load_api_key() -> str | None:
    return os.environ.get("UW_SCAN_API_KEY") or env_file_values(REPO_ROOT / ".env").get(
        "UW_SCAN_API_KEY"
    )


def load_spec(path: Path, spec_url: str | None) -> dict[str, Any]:
    if spec_url:
        response = httpx.get(spec_url, timeout=30.0)
        response.raise_for_status()
        return yaml.safe_load(response.text)
    return yaml.safe_load(path.read_text())


def operation_parameters(path_item: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    return list(path_item.get("parameters") or []) + list(operation.get("parameters") or [])


def operations_from_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for path, path_item in sorted((spec.get("paths") or {}).items()):
        for method, operation in sorted(path_item.items()):
            if method.lower() != "get":
                continue
            params = operation_parameters(path_item, operation)
            operations.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId"),
                    "summary": operation.get("summary"),
                    "tags": operation.get("tags") or [],
                    "description": operation.get("description") or "",
                    "parameters": params,
                }
            )
    return operations


def discover_option_symbol(client: httpx.Client, base_url: str, headers: dict[str, str]) -> str:
    try:
        response = client.get(
            f"{base_url}/api/stock/{SAMPLE_STOCK}/option-contracts",
            params={"limit": 1},
            headers=headers,
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return DEFAULT_OPTION_SYMBOL
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list) and data:
        candidate = data[0].get("option_symbol") if isinstance(data[0], dict) else None
        if isinstance(candidate, str) and candidate:
            return candidate
    return DEFAULT_OPTION_SYMBOL


def discover_flow_alert_id(client: httpx.Client, base_url: str, headers: dict[str, str]) -> str:
    try:
        response = client.get(
            f"{base_url}/api/option-trades/flow-alerts",
            params={"limit": 1},
            headers=headers,
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return "00000000-0000-0000-0000-000000000000"
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list) and data:
        candidate = data[0].get("id") if isinstance(data[0], dict) else None
        if isinstance(candidate, str) and candidate:
            return candidate
    return "00000000-0000-0000-0000-000000000000"


def discover_prediction_asset_id(
    client: httpx.Client, base_url: str, headers: dict[str, str]
) -> str:
    try:
        response = client.get(f"{base_url}/api/predictions/unusual", headers=headers)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return "59252515735652674747158950210016502214756531287333895140318848923768750410355"
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("data") if isinstance(data, dict) else None
    if isinstance(rows, list) and rows:
        candidate = rows[0].get("asset_id") if isinstance(rows[0], dict) else None
        if isinstance(candidate, str) and candidate:
            return candidate
    return "59252515735652674747158950210016502214756531287333895140318848923768750410355"


def build_sample_context(
    client: httpx.Client | None, base_url: str, headers: dict[str, str] | None
) -> SampleContext:
    today = date.today()
    market_date = previous_weekday(today)
    start_date = market_date - timedelta(days=30)
    option_symbol = DEFAULT_OPTION_SYMBOL
    flow_alert_id = "00000000-0000-0000-0000-000000000000"
    prediction_asset_id = (
        "59252515735652674747158950210016502214756531287333895140318848923768750410355"
    )
    if client is not None and headers is not None:
        option_symbol = discover_option_symbol(client, base_url, headers)
        flow_alert_id = discover_flow_alert_id(client, base_url, headers)
        prediction_asset_id = discover_prediction_asset_id(client, base_url, headers)
    market_dt = datetime.combine(market_date, datetime.min.time(), tzinfo=timezone.utc)
    return SampleContext(
        market_date=market_date.isoformat(),
        start_date=start_date.isoformat(),
        expiry=next_friday(today).isoformat(),
        iso_newer_than=(market_dt + timedelta(hours=13, minutes=30)).isoformat().replace(
            "+00:00", "Z"
        ),
        iso_older_than=(market_dt + timedelta(hours=20)).isoformat().replace("+00:00", "Z"),
        option_symbol=option_symbol,
        flow_alert_id=flow_alert_id,
        prediction_asset_id=prediction_asset_id,
    )


def parameter_names(parameters: list[dict[str, Any]], location: str | None = None) -> list[str]:
    return [
        str(param.get("name"))
        for param in parameters
        if param.get("name") and (location is None or param.get("in") == location)
    ]


def path_value(path: str, name: str, context: SampleContext) -> str:
    if name == "ticker":
        if path.startswith("/api/etfs/") or path.endswith("/etf-tide"):
            return SAMPLE_ETF
        return SAMPLE_STOCK
    if name == "sector":
        return SAMPLE_SECTOR
    if name == "flow_group":
        return "technology"
    if name == "expiry":
        return context.expiry
    if name == "date":
        return context.market_date
    if name == "candle_size":
        return "1m"
    if name == "month":
        return str(date.today().month)
    if name == "id":
        if path.startswith("/api/option-trades/flow-alerts/"):
            return context.flow_alert_id
        return context.option_symbol
    if name == "asset_id":
        return context.prediction_asset_id
    if name == "user_id":
        return "polymarket"
    if name == "npm_ticker":
        return "STRIPE"
    if name == "function":
        return "RSI"
    if name == "quarter":
        return "2024-Q1"
    if name == "pair":
        return "BTC-USD"
    if name == "politician_id":
        return SAMPLE_POLITICIAN_ID
    if name == "indicator":
        return SAMPLE_ECONOMY_INDICATOR
    if name == "name":
        if path.startswith("/api/commodities/"):
            return SAMPLE_COMMODITY
        return SAMPLE_INSTITUTION
    return SAMPLE_STOCK


def query_value(name: str, context: SampleContext, path: str) -> Any:
    if name in {"limit", "page"}:
        return 1
    if name == "date":
        return context.market_date
    if name == "start_date":
        return context.start_date
    if name == "end_date":
        return context.market_date
    if name == "newer_than":
        return context.iso_newer_than
    if name == "older_than":
        return context.iso_older_than
    if name in {"expiry", "expiration"}:
        return context.expiry
    if name == "expirations[]":
        return [context.expiry]
    if name == "delta":
        return 25
    if name in {"ticker", "ticker_symbol"}:
        return SAMPLE_STOCK
    if name in {"tickers", "symbols"}:
        return f"{SAMPLE_STOCK},{SAMPLE_COMPARISON}"
    if name == "q":
        return "trump"
    if name == "query":
        return "stripe"
    if name == "symbol":
        if "digital-currencies" in path:
            return "BTC"
        return SAMPLE_STOCK
    if name == "market":
        return "USD"
    if name == "from":
        return "USD"
    if name == "to":
        return "EUR"
    if name == "range":
        return "1month"
    if name == "calculations":
        return "correlation"
    if name == "interval":
        return "1d"
    if name == "timeframe":
        return "1Y"
    if name == "side":
        return "ASK"
    if name == "type":
        return "call"
    if name == "aggregate_all_portfolios":
        return "false"
    if name == "politician_id":
        return SAMPLE_POLITICIAN_ID
    if name.endswith("[]"):
        return []
    return None


def sample_request(operation: dict[str, Any], context: SampleContext) -> tuple[str, list[tuple[str, Any]], list[str]]:
    path = operation["path"]
    params = operation["parameters"]
    notes: list[str] = []

    def replace_match(match: re.Match[str]) -> str:
        name = match.group(1)
        return quote(path_value(path, name, context), safe="")

    resolved_path = re.sub(r"\{([^}]+)\}", replace_match, path)
    query_items: list[tuple[str, Any]] = []
    for param in params:
        if param.get("in") != "query":
            continue
        name = str(param.get("name"))
        required = bool(param.get("required"))
        include_optional = name in {
            "date",
            "limit",
            "start_date",
            "end_date",
            "from",
            "to",
            "symbol",
            "market",
            "range",
            "calculations",
        }
        if not required and not include_optional:
            continue
        value = query_value(name, context, path)
        if value is None or value == []:
            if required:
                notes.append(f"missing_sample_for_required_query:{name}")
            continue
        if isinstance(value, list):
            query_items.extend((name, item) for item in value)
        else:
            query_items.append((name, value))
    return resolved_path, query_items, notes


def entitlement_hint(operation: dict[str, Any]) -> str:
    text = " ".join(
        str(operation.get(key) or "") for key in ("path", "summary", "description")
    ).lower()
    if "advanced+" in text or "advanced api tier" in text:
        return "advanced+-docs"
    if "advanced plan" in text or "advanced api subscription" in text:
        return "advanced-docs"
    if "premium endpoint" in text:
        return "premium-docs"
    if "enterprise" in text:
        return "enterprise-docs"
    if "websocket" in text:
        return "websocket-docs"
    return "not-marked"


def backfill_hint(operation: dict[str, Any]) -> str:
    path = operation["path"]
    names = set(parameter_names(operation["parameters"], "query")) | set(
        parameter_names(operation["parameters"], "path")
    )
    if "full-tape" in path:
        return "archive-gated"
    if "/api/socket" in path:
        return "live-only"
    if path.endswith("/option-contracts") or path.endswith("/option-chains"):
        return "snapshot-or-current-chain"
    if {"date", "start_date", "end_date", "newer_than", "older_than"} & names:
        return "historical-selector"
    if any(token in path for token in ("history", "historic", "historical", "intraday")):
        return "historical-path"
    if any(token in path for token in ("recent", "calendar", "earnings")):
        return "recent-or-calendar"
    return "snapshot-or-reference"


def summarize_body(response: httpx.Response) -> tuple[str, int | None, list[str], str | None]:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return "text", None, [], text[:180] if text else None

    message: str | None = None
    data_count: int | None = None
    sample_keys: list[str] = []

    if isinstance(payload, dict):
        for key in ("message", "msg", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str):
                message = value[:240]
                break
        data = payload.get("data")
        if isinstance(data, list):
            data_count = len(data)
            if data and isinstance(data[0], dict):
                sample_keys = sorted(str(k) for k in data[0].keys())[:16]
            return "object:data-list", data_count, sample_keys, message
        if isinstance(data, dict):
            sample_keys = sorted(str(k) for k in data.keys())[:16]
            return "object:data-object", None, sample_keys, message
        sample_keys = sorted(str(k) for k in payload.keys())[:16]
        return "object", None, sample_keys, message
    if isinstance(payload, list):
        data_count = len(payload)
        if payload and isinstance(payload[0], dict):
            sample_keys = sorted(str(k) for k in payload[0].keys())[:16]
        return "list", data_count, sample_keys, message
    return type(payload).__name__, None, sample_keys, message


def access_result(status_code: int, message: str | None, docs_hint: str) -> str:
    text = (message or "").lower()
    if status_code == 200:
        return "accessible"
    if status_code == 401:
        return "auth-failed"
    if status_code == 403:
        if "advanced" in text or "tier" in text or "enterprise" in text:
            return "gated"
        return "forbidden"
    if status_code == 404:
        return "sample-not-found"
    if status_code == 422:
        if (
            "missing access" in text
            or "advanced" in text
            or "full tape" in text
            or "premium" in text
            or "enterprise" in text
        ):
            return "gated"
        return "sample-invalid"
    if status_code == 429:
        return "rate-limited"
    if docs_hint != "not-marked" and status_code in {400, 403, 422}:
        return "likely-gated-or-sample-invalid"
    return "unexpected"


def audit_operation(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    operation: dict[str, Any],
    context: SampleContext,
    timeout: float,
) -> dict[str, Any]:
    path, query_items, notes = sample_request(operation, context)
    url = f"{base_url}{path}"
    started = time.monotonic()
    status_code: int | None = None
    body_kind = "not-run"
    data_count: int | None = None
    sample_keys: list[str] = []
    message: str | None = None
    error: str | None = None
    try:
        response = client.get(url, params=query_items, headers=headers, timeout=timeout)
        status_code = response.status_code
        body_kind, data_count, sample_keys, message = summarize_body(response)
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    docs_hint = entitlement_hint(operation)
    return {
        "method": operation["method"],
        "path": operation["path"],
        "operation_id": operation.get("operation_id"),
        "summary": operation.get("summary"),
        "tags": operation.get("tags"),
        "sample_path": path,
        "sample_query": query_items,
        "sample_notes": notes,
        "required_path_params": [
            p.get("name")
            for p in operation["parameters"]
            if p.get("in") == "path" and p.get("required")
        ],
        "required_query_params": [
            p.get("name")
            for p in operation["parameters"]
            if p.get("in") == "query" and p.get("required")
        ],
        "historical_params": [
            name
            for name in parameter_names(operation["parameters"])
            if name in {"date", "newer_than", "older_than", "start_date", "end_date"}
        ],
        "docs_entitlement_hint": docs_hint,
        "backfill_hint": backfill_hint(operation),
        "status_code": status_code,
        "access_result": access_result(status_code or 0, message or error, docs_hint)
        if status_code is not None
        else "request-error",
        "body_kind": body_kind,
        "data_count": data_count,
        "sample_keys": sample_keys,
        "message": message,
        "error": error,
        "elapsed_ms": elapsed_ms,
    }


def planned_operation(operation: dict[str, Any], context: SampleContext) -> dict[str, Any]:
    path, query_items, notes = sample_request(operation, context)
    return {
        "method": operation["method"],
        "path": operation["path"],
        "operation_id": operation.get("operation_id"),
        "summary": operation.get("summary"),
        "tags": operation.get("tags"),
        "sample_path": path,
        "sample_query": query_items,
        "sample_notes": notes,
        "required_path_params": [
            p.get("name")
            for p in operation["parameters"]
            if p.get("in") == "path" and p.get("required")
        ],
        "required_query_params": [
            p.get("name")
            for p in operation["parameters"]
            if p.get("in") == "query" and p.get("required")
        ],
        "historical_params": [
            name
            for name in parameter_names(operation["parameters"])
            if name in {"date", "newer_than", "older_than", "start_date", "end_date"}
        ],
        "docs_entitlement_hint": entitlement_hint(operation),
        "backfill_hint": backfill_hint(operation),
        "status_code": None,
        "access_result": "not-run",
        "body_kind": "not-run",
        "data_count": None,
        "sample_keys": [],
        "message": None,
        "error": None,
        "elapsed_ms": None,
    }


def summarize(results: list[dict[str, Any]], live: bool, spec_source: str) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spec_source": spec_source,
        "live": live,
        "operation_count": len(results),
        "status_counts": dict(Counter(str(r["status_code"]) for r in results)),
        "access_counts": dict(Counter(r["access_result"] for r in results)),
        "docs_entitlement_counts": dict(Counter(r["docs_entitlement_hint"] for r in results)),
        "backfill_counts": dict(Counter(r["backfill_hint"] for r in results)),
    }


def write_json(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    payload = {"summary": summary, "operations": results}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines: list[str] = [
        "# UW API Capability Audit",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Spec source: `{summary['spec_source']}`",
        f"- Live probes: `{summary['live']}`",
        f"- Operations audited: `{summary['operation_count']}`",
        f"- Status counts: `{summary['status_counts']}`",
        f"- Access counts: `{summary['access_counts']}`",
        f"- Backfill counts: `{summary['backfill_counts']}`",
        "",
        "## Gated / Blocked / Invalid Samples",
        "",
        "| Status | Access | Docs hint | Path | Message |",
        "|---:|---|---|---|---|",
    ]
    for result in results:
        if result["access_result"] == "accessible":
            continue
        lines.append(
            "| {status} | {access} | {docs} | `{path}` | {message} |".format(
                status=md_escape(result["status_code"]),
                access=md_escape(result["access_result"]),
                docs=md_escape(result["docs_entitlement_hint"]),
                path=md_escape(result["path"]),
                message=md_escape(result["message"] or result["error"] or ""),
            )
        )
    lines.extend(
        [
            "",
            "## Complete Operation Matrix",
            "",
            "| Status | Access | Backfill | Docs hint | Method | Path | Required query | Sample query | Data |",
            "|---:|---|---|---|---|---|---|---|---|",
        ]
    )
    for result in results:
        sample_query = "&".join(f"{k}={v}" for k, v in result["sample_query"])
        lines.append(
            "| {status} | {access} | {backfill} | {docs} | {method} | `{path}` | `{required}` | `{query}` | {data} |".format(
                status=md_escape(result["status_code"]),
                access=md_escape(result["access_result"]),
                backfill=md_escape(result["backfill_hint"]),
                docs=md_escape(result["docs_entitlement_hint"]),
                method=md_escape(result["method"]),
                path=md_escape(result["path"]),
                required=md_escape(",".join(result["required_query_params"])),
                query=md_escape(sample_query),
                data=md_escape(
                    f"{result['body_kind']}; count={result['data_count']}; keys={','.join(result['sample_keys'])}"
                ),
            )
        )
    path.write_text("\n".join(lines) + "\n")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="send live GET requests")
    parser.add_argument("--spec-path", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--spec-url", default=None, help="fetch OpenAPI from URL")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD_OUT)
    parser.add_argument("--sleep-seconds", type=float, default=0.55)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=None, help="audit only first N operations")
    args = parser.parse_args()

    spec_source = args.spec_url or str(args.spec_path.relative_to(REPO_ROOT))
    spec = load_spec(args.spec_path, args.spec_url)
    operations = operations_from_spec(spec)
    if args.limit is not None:
        operations = operations[: args.limit]

    results: list[dict[str, Any]] = []
    if args.live:
        api_key = load_api_key()
        if not api_key:
            sys.exit("UW_SCAN_API_KEY is not set in the environment or .env")
        headers = {"Authorization": f"Bearer {api_key}"}
        with httpx.Client() as client:
            context = build_sample_context(client, args.base_url, headers)
            for index, operation in enumerate(operations, start=1):
                result = audit_operation(
                    client,
                    args.base_url,
                    headers,
                    operation,
                    context,
                    args.timeout,
                )
                results.append(result)
                print(
                    f"{index:3d}/{len(operations):3d} "
                    f"{result['status_code']} {result['access_result']:16s} {operation['path']}"
                )
                if index < len(operations) and args.sleep_seconds > 0:
                    if result["status_code"] == 429:
                        time.sleep(max(args.sleep_seconds, 2.0))
                    else:
                        time.sleep(args.sleep_seconds)
    else:
        context = build_sample_context(None, args.base_url, None)
        results = [planned_operation(operation, context) for operation in operations]

    summary = summarize(results, args.live, spec_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.out, summary, results)
    write_markdown(args.markdown, summary, results)
    print(f"wrote {display_path(args.out)}")
    print(f"wrote {display_path(args.markdown)}")


if __name__ == "__main__":
    main()
