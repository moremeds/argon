#!/usr/bin/env python
"""Read-only inventory of the legacy rates and gold persistence surfaces.

This script never calls an external provider and refuses every database except
``option_wizard_local``. It captures live structural facts (row counts, primary
keys, date spans, and source/series dimensions) alongside a reviewed static
contract describing time semantics, consumers, and migration risks.

Reproduce::

    uv run python scripts/research/macro_legacy_inventory.py
    uv run python scripts/research/macro_legacy_inventory.py --self-check
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

DEFAULT_DB_NAME = "option_wizard_local"
DEFAULT_SCHEMA = "uw_scan"
DEFAULT_OUTPUT = Path("docs/research/2026-08-12-macro-legacy-inventory/inventory.json")
ALLOWED_DOMAINS = frozenset(
    {"inflation", "policy_rates", "usd", "gold", "cross_domain"}
)


def _contract(
    *,
    relation_kind: str = "table",
    domain: str,
    date_column: str,
    revision_identity: str,
    timestamp_semantics: str,
    source_status: str,
    consumers: list[str],
    risks: list[str],
    adapter_action: str,
    dimensions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "relation_kind": relation_kind,
        "domain": domain,
        "date_column": date_column,
        "revision_identity": revision_identity,
        "timestamp_semantics": timestamp_semantics,
        "source_status": source_status,
        "downstream_consumers": consumers,
        "risk_flags": risks,
        "adapter_action": adapter_action,
        "dimensions": dimensions or [],
    }


RELATION_CONTRACTS: dict[str, dict[str, Any]] = {
    "cb_gold_reserves_monthly": _contract(
        domain="gold",
        date_column="obs_month",
        revision_identity="(country_iso3, obs_month, as_of)",
        timestamp_semantics=(
            "release_date is publisher date when known; as_of is ingestion time"
        ),
        source_status=(
            "local workbook import present; scheduled WGC source remains blocked by login"
        ),
        consumers=["reports/gold_posture.py", "api/routers/gold.py"],
        risks=[
            "no live official fallback wired",
            "local lineage points to a non-durable /tmp workbook path",
            "estimated-vs-reported is typed but exact source artifact is absent",
        ],
        adapter_action="defer until free official IMF/WGC source is proven",
        dimensions=["source", "bucket"],
    ),
    "cot_gold_weekly": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(obs_date, as_of)",
        timestamp_semantics=(
            "obs_date is Tuesday position date; release_date is Friday publication; "
            "backtests require release_date + 3 trading days"
        ),
        source_status="free official CFTC",
        consumers=["reports/gold_posture.py", "api/routers/gold.py"],
        risks=["source URL retained but exact payload bytes are not linked"],
        adapter_action="dual-write CFTC rows with published_at=release timestamp",
        dimensions=[],
    ),
    "etf_aum_cache": _contract(
        domain="gold",
        date_column="fetched_at",
        revision_identity="ticker (overwriting cache)",
        timestamp_semantics="fetched_at is cache refresh time, not a market observation date",
        source_status="already-entitled UW operational cache",
        consumers=["storage/market_data.py", "scanner pipeline"],
        risks=["not macro evidence; historical values intentionally overwritten"],
        adapter_action="exclude from macro evidence adapters",
        dimensions=["ticker"],
    ),
    "etf_flows_daily": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(ticker, obs_date, as_of)",
        timestamp_semantics="obs_date is market date; as_of is ingestion time",
        source_status="already-entitled UW",
        consumers=["reports/gold_posture.py", "api/routers/gold.py"],
        risks=["no source URL or exact payload link"],
        adapter_action="dual-write with UW artifact reference",
        dimensions=["ticker", "source"],
    ),
    "etf_holdings_daily": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(ticker, obs_date, as_of)",
        timestamp_semantics="obs_date is issuer observation date; as_of is ingestion time",
        source_status="free first-party fund publishers",
        consumers=["reports/gold_posture.py", "api/routers/gold.py"],
        risks=["source label retained but exact issuer payload is not linked"],
        adapter_action="dual-write issuer artifact and normalized holdings",
        dimensions=["ticker", "source"],
    ),
    "exchange_inventory_daily": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(exchange, obs_date, as_of)",
        timestamp_semantics="obs_date is exchange report date; as_of is ingestion time",
        source_status="free publisher: LBMA live; CME endpoint fragile",
        consumers=["reports/gold_posture.py", "api/routers/gold.py"],
        risks=[
            "COMEX source availability is fragile",
            "source URL retained but workbook/report bytes are not linked",
        ],
        adapter_action="dual-write discovered publisher file bytes",
        dimensions=["exchange"],
    ),
    "gold_posture_daily": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(obs_date, computed_at)",
        timestamp_semantics=(
            "obs_date is posture date; computed_at is derivation time; inputs_jsonb pins "
            "legacy input coordinates"
        ),
        source_status="derived",
        consumers=["api/routers/gold.py", "web/app/gold", "gold replay page"],
        risks=[
            "replay fidelity is bounded by legacy input time semantics",
            "not an upstream source and must not be adapted as an observation",
        ],
        adapter_action="keep as legacy read model until evidence-reference parity passes",
        dimensions=["row_status", "gauge_state"],
    ),
    "macro_series_daily": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(series_id, obs_date, as_of)",
        timestamp_semantics=(
            "release_date is optional; as_of is retrieval time and is not guaranteed to "
            "equal public availability time"
        ),
        source_status="mixed free official/publisher and derived series",
        consumers=[
            "reports/gold_posture.py",
            "api/routers/gold.py",
            "api/routers/trade_insights.py",
            "worker/jobs/regime_jobs.py",
        ],
        risks=[
            "mixed source classes share one table",
            "no artifact hash/parser version",
            "release_date nullable",
        ],
        adapter_action="map each series explicitly; never infer availability from as_of",
        dimensions=["series_id", "source"],
    ),
    "macro_series_monthly": _contract(
        domain="cross_domain",
        date_column="obs_month",
        revision_identity="(series_id, obs_month, as_of)",
        timestamp_semantics=(
            "release_date is optional; as_of is retrieval time and not a release clock"
        ),
        source_status="mixed free official FRED series",
        consumers=["reports/gold_posture.py", "api/routers/gold.py"],
        risks=["no artifact hash/parser version", "release_date nullable"],
        adapter_action="map CPI/M2 series with official release availability",
        dimensions=["series_id", "source"],
    ),
    "rates_cftc_tff_weekly": _contract(
        domain="policy_rates",
        date_column="obs_date",
        revision_identity="(contract_code, obs_date, as_of)",
        timestamp_semantics=(
            "obs_date is Tuesday position date; release_date is publication date; "
            "as_of is ingestion time"
        ),
        source_status="free official CFTC",
        consumers=["rates report assembler", "web rates positioning panel"],
        risks=["exact CFTC response is not linked to normalized rows"],
        adapter_action="dual-write release-timed observations and source artifact",
        dimensions=["contract_code", "tenor_bucket"],
    ),
    "rates_fiscal_debt_daily": _contract(
        domain="policy_rates",
        date_column="record_date",
        revision_identity="(record_date, as_of)",
        timestamp_semantics="record_date is FiscalData date; as_of is ingestion time",
        source_status="free official U.S. Treasury FiscalData",
        consumers=["rates report assembler", "web rates supply panel"],
        risks=["source URL retained but response artifact is not linked"],
        adapter_action="dual-write official FiscalData artifact",
        dimensions=[],
    ),
    "rates_observations": _contract(
        domain="policy_rates",
        date_column="obs_date",
        revision_identity="(series_id, obs_date, source) overwrites revisions",
        timestamp_semantics=(
            "FRED realtime_start/end are vintage metadata; first/last_seen are local "
            "sightings; release_date may be null"
        ),
        source_status="free official FRED plus Cleveland Fed decomposition",
        consumers=["rates report assembler", "web rates curve/policy/plumbing panels"],
        risks=[
            "critical: ON CONFLICT overwrites value and vintage metadata",
            "source precedence is implicit",
            "no exact source artifact",
        ],
        adapter_action="highest-priority MC1 dual-write; preserve every vintage",
        dimensions=["series_id", "source"],
    ),
    "rates_policy_events": _contract(
        domain="policy_rates",
        date_column="event_date",
        revision_identity="(event_date, source) overwrites payload changes",
        timestamp_semantics="event_date is meeting date; first/last_seen are local sightings",
        source_status="free official Federal Reserve calendar",
        consumers=["rates report assembler", "web rates event calendar"],
        risks=[
            "calendar only: no statements, minutes, votes, transcripts, SEP, or dot plot",
            "payload changes overwrite history",
            "no source artifact hash",
        ],
        adapter_action="MC1 expand to artifact-led FOMC/SEP event model",
        dimensions=["source"],
    ),
    "rates_policy_path": _contract(
        domain="policy_rates",
        date_column="snapshot_date",
        revision_identity="(snapshot_date, meeting_date, source)",
        timestamp_semantics=(
            "snapshot_date is provider snapshot day; first/last_seen are local sightings"
        ),
        source_status="free third-party delayed FedWatch shadow",
        consumers=["rates report assembler", "web rates implied path panel"],
        risks=[
            "not official Fed data",
            "same-day corrections overwrite",
            "no exact HTML/JSON artifact",
        ],
        adapter_action="retain as labeled shadow; add official/event evidence separately",
        dimensions=["source"],
    ),
    "rates_snapshots": _contract(
        domain="policy_rates",
        date_column="snapshot_date",
        revision_identity="(snapshot_date, computed_at)",
        timestamp_semantics="snapshot_date is page date; computed_at is derivation time",
        source_status="derived",
        consumers=["api/routers/rates.py", "web/app/rates"],
        risks=["payload embeds legacy values without normalized evidence IDs"],
        adapter_action="keep authoritative until dual-read evidence parity passes",
        dimensions=[],
    ),
    "rates_treasury_auctions": _contract(
        domain="policy_rates",
        date_column="auction_date",
        revision_identity="(cusip, auction_date, as_of)",
        timestamp_semantics="auction_date is official event date; as_of is ingestion time",
        source_status="free official TreasuryDirect",
        consumers=["rates report assembler", "web rates supply panel"],
        risks=["source URL retained but response artifact is not linked"],
        adapter_action="dual-write official auction artifact and observations",
        dimensions=["security_type", "security_term"],
    ),
    "uw_gold_options_daily": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(ticker, obs_date, as_of)",
        timestamp_semantics="obs_date is market date; as_of is composite fetch time",
        source_status="already-entitled UW",
        consumers=["reports/gold_posture.py", "api/routers/gold.py"],
        risks=["composed from multiple endpoints without exact joined artifact IDs"],
        adapter_action="dual-write endpoint artifacts; keep derived snapshot separate",
        dimensions=["ticker"],
    ),
    "wgc_etf_monthly": _contract(
        domain="gold",
        date_column="obs_date",
        revision_identity="(ticker, obs_date, source_url)",
        timestamp_semantics=(
            "obs_date is workbook period; as_of is ingestion time; source_url identifies "
            "a workbook revision"
        ),
        source_status="free first-party WGC workbook",
        consumers=["storage/gold_etf.py", "gold ETF corpus research"],
        risks=["same-URL workbook changes overwrite normalized values"],
        adapter_action="store exact workbook bytes keyed by content hash",
        dimensions=["ticker", "source"],
    ),
    "wgc_etf_monthly_canonical": _contract(
        relation_kind="view",
        domain="gold",
        date_column="obs_date",
        revision_identity="latest workbook revision selected per (ticker, obs_date)",
        timestamp_semantics="inherits wgc_etf_monthly; canonical selection is query-time",
        source_status="derived view over free first-party WGC workbooks",
        consumers=["storage/gold_etf.py::fetch_wgc_etf_monthly"],
        risks=["latest-wins selection is not an as-of query"],
        adapter_action="replace consumers with explicit PIT source precedence after parity",
        dimensions=["ticker", "source"],
    ),
}

REQUIRED_RELATIONS = frozenset(RELATION_CONTRACTS)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _serialized(payload: dict[str, Any]) -> str:
    return (
        json.dumps(
            payload,
            default=_json_default,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def _relation_kind(conn: psycopg.Connection, schema: str, name: str) -> str | None:
    row = conn.execute(
        """
        SELECT c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
        """,
        (schema, name),
    ).fetchone()
    if row is None:
        return None
    return {"r": "table", "p": "table", "v": "view", "m": "view"}.get(row[0])


def _primary_key(conn: psycopg.Connection, schema: str, name: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN unnest(i.indkey) WITH ORDINALITY AS keys(attnum, ord) ON true
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = keys.attnum
        WHERE n.nspname = %s AND c.relname = %s AND i.indisprimary
        ORDER BY keys.ord
        """,
        (schema, name),
    ).fetchall()
    return [row[0] for row in rows]


def _columns(conn: psycopg.Connection, schema: str, name: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, name),
    ).fetchall()
    return {row[0] for row in rows}


def _scalar(conn: psycopg.Connection, query: sql.Composed) -> Any:
    return conn.execute(query).fetchone()[0]


def _relation_inventory(
    conn: psycopg.Connection,
    *,
    schema: str,
    name: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    actual_kind = _relation_kind(conn, schema, name)
    if actual_kind is None:
        raise ValueError(f"required relation missing: {schema}.{name}")
    if actual_kind != contract["relation_kind"]:
        raise ValueError(
            f"relation kind mismatch for {name}: {actual_kind} != "
            f"{contract['relation_kind']}"
        )
    columns = _columns(conn, schema, name)
    qualified = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(name))
    row_count = _scalar(conn, sql.SQL("SELECT count(*) FROM {}").format(qualified))

    date_column = contract["date_column"]
    if date_column not in columns:
        raise ValueError(f"{name} lacks declared date column {date_column}")
    span_row = conn.execute(
        sql.SQL("SELECT min({0}), max({0}) FROM {1}").format(
            sql.Identifier(date_column), qualified
        )
    ).fetchone()

    dimensions: dict[str, list[Any]] = {}
    for dimension in contract["dimensions"]:
        if dimension not in columns:
            raise ValueError(f"{name} lacks declared dimension {dimension}")
        rows = conn.execute(
            sql.SQL(
                "SELECT DISTINCT {0} FROM {1} WHERE {0} IS NOT NULL ORDER BY {0}"
            ).format(sql.Identifier(dimension), qualified)
        ).fetchall()
        dimensions[dimension] = [row[0] for row in rows]

    series_profiles: list[dict[str, Any]] = []
    if "series_id" in columns:
        source_expr = (
            sql.SQL(
                "array_agg(DISTINCT source ORDER BY source) FILTER "
                "(WHERE source IS NOT NULL)"
            )
            if "source" in columns
            else sql.SQL("ARRAY[]::text[]")
        )
        rows = conn.execute(
            sql.SQL(
                "SELECT series_id, count(*), min({0}), max({0}), {1} "
                "FROM {2} GROUP BY series_id ORDER BY series_id"
            ).format(sql.Identifier(date_column), source_expr, qualified)
        ).fetchall()
        series_profiles = [
            {
                "series_id": row[0],
                "row_count": row[1],
                "date_span": {"min": row[2], "max": row[3]},
                "sources": row[4],
            }
            for row in rows
        ]

    return {
        "name": name,
        "relation_kind": actual_kind,
        "row_count": row_count,
        "primary_key": _primary_key(conn, schema, name),
        "date_span": {"min": span_row[0], "max": span_row[1]},
        "dimensions": dimensions,
        "series_profiles": series_profiles,
        "contract": contract,
    }


def build_inventory(
    conn: psycopg.Connection,
    *,
    database: str,
    schema: str = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    relations = [
        _relation_inventory(
            conn,
            schema=schema,
            name=name,
            contract=RELATION_CONTRACTS[name],
        )
        for name in sorted(REQUIRED_RELATIONS)
    ]
    return {
        "scope": {
            "database": database,
            "schema": schema,
            "mode": "read_only_snapshot",
            "external_provider_calls": 0,
        },
        "relations": relations,
    }


def validate_inventory(payload: dict[str, Any]) -> None:
    relations = payload.get("relations")
    if not isinstance(relations, list):
        raise ValueError("relations must be a list")
    names = [row.get("name") for row in relations]
    if names != sorted(names):
        raise ValueError("relation inventory is not sorted")
    actual = set(names)
    if actual != REQUIRED_RELATIONS:
        missing = sorted(REQUIRED_RELATIONS - actual)
        extra = sorted(actual - REQUIRED_RELATIONS)
        raise ValueError(
            f"relation coverage mismatch: missing={missing}, extra={extra}"
        )
    for row in relations:
        domain = row.get("contract", {}).get("domain")
        if domain not in ALLOWED_DOMAINS:
            raise ValueError(
                f"relation {row.get('name')} has unknown domain {domain!r}"
            )
    for row in relations:
        contract = row.get("contract", {})
        required = {
            "domain",
            "revision_identity",
            "timestamp_semantics",
            "source_status",
            "downstream_consumers",
            "risk_flags",
            "adapter_action",
        }
        missing_keys = sorted(required - set(contract))
        if missing_keys:
            raise ValueError(f"{row['name']} contract missing: {missing_keys}")


def _connect_read_only(db_name: str) -> psycopg.Connection:
    if db_name != DEFAULT_DB_NAME:
        raise ValueError(
            f"refusing database {db_name!r}; inventory is pinned to {DEFAULT_DB_NAME!r}"
        )
    conn = psycopg.connect(dbname=db_name)
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    current_db, read_only = conn.execute(
        "SELECT current_database(), current_setting('transaction_read_only')::boolean"
    ).fetchone()
    if current_db != DEFAULT_DB_NAME or not read_only:
        conn.close()
        raise RuntimeError(
            f"read-only boundary failed: database={current_db!r}, read_only={read_only!r}"
        )
    return conn


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--schema", default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.schema != DEFAULT_SCHEMA:
        raise ValueError(
            f"refusing schema {args.schema!r}; expected {DEFAULT_SCHEMA!r}"
        )

    with _connect_read_only(args.db_name) as conn:
        payload = build_inventory(conn, database=args.db_name, schema=args.schema)
        validate_inventory(payload)
        encoded = _serialized(payload)
        if args.self_check:
            second = _serialized(
                build_inventory(conn, database=args.db_name, schema=args.schema)
            )
            if encoded != second:
                raise ValueError(
                    "inventory is not deterministic within one DB snapshot"
                )
            print(
                f"self-check ok: {len(payload['relations'])} relations, "
                "read-only, deterministic, 0 provider calls"
            )
            return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded)
    nonempty = sum(row["row_count"] > 0 for row in payload["relations"])
    print(
        f"wrote {args.output}: {len(payload['relations'])} relations, "
        f"{nonempty} non-empty, 0 provider calls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
