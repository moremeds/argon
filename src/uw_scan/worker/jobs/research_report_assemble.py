"""Deterministic report assembly (M7.2). No model, no narrative, no network.

Every block is built from persisted, versioned rows and names either the evidence
it rests on or the derivation that produced it — the schema refuses a block with
neither. Given the same manifest, this function must produce the same content
hash forever, which is what makes an old report replayable after the data and
the methods have moved on.

WHY THE UNSUPPORTED SECTION IS A BLOCK AND NOT A FOOTER
------------------------------------------------------
A report that silently omits what it cannot answer reads as complete. Every
report assembled here carries an explicit `unsupported` block listing the killed
event classes, the dimensions capped at `descriptive`, and the coverage
denominators. It is ordinal 1 in the company report on purpose: the reader meets
the limits before the numbers.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from uw_scan.fundamentals.dimensions import AGGREGATE_DIMENSIONS
from uw_scan.storage.fundamental_dimensions import FundamentalDimensionsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.research_events import ResearchEventsRepository
from uw_scan.storage.research_reports import (
    STATUS_PARTIAL,
    STATUS_PUBLISHED,
    ResearchReportsRepository,
)
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.research_report_scaffold import (
    _manifest,
    _unsupported_block,
    check_single_basis,
)

log = logging.getLogger(__name__)


def assemble_company_report(
    conn: psycopg.Connection,
    ticker: str,
    *,
    schema: str = "uw_scan",
    engine_version: str | None = None,
    as_of: date | None = None,
    publish: bool = True,
) -> dict[str, Any]:
    """Build (and optionally publish) one company report."""
    symbol = ticker.upper()
    today = as_of or date.today()
    scores = FundamentalScoresRepository(conn, schema=schema)
    engine = engine_version or scores.active_version()
    dims_repo = FundamentalDimensionsRepository(conn, schema=schema)
    events_repo = ResearchEventsRepository(conn, schema=schema)
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    reports = ResearchReportsRepository(conn, schema=schema)

    taxonomy = tax.active_version()
    dims = dims_repo.for_ticker(symbol, engine_version=engine) if engine else {}
    events = events_repo.events_for(symbol, known_by=today, limit=25)
    risks = events_repo.risks_for(symbol, as_of=today)
    exposures = (
        tax.exposures(taxonomy, ticker=symbol) if taxonomy else []
    )

    notes: list[str] = []
    blocks: list[dict[str, Any]] = []

    blocks.append(
        {
            "ordinal": 0,
            "block_kind": "scope",
            "title": f"{symbol} — research scope",
            "payload": {
                "ticker": symbol,
                "as_of": today.isoformat(),
                "engine_version": engine,
                "taxonomy_version": taxonomy,
                "evidence_policy": "current_vintage",
            },
            "derivation": "the report manifest, restated for the reader",
        }
    )

    if not dims:
        notes.append(
            f"no dimensions computed for {symbol} under engine {engine} — "
            "the operating and priority blocks are absent, which is a gap in "
            "Argon rather than a fact about the company"
        )
    blocks.append(_unsupported_block(1, events_repo, notes))

    if dims:
        present = [
            d for d in AGGREGATE_DIMENSIONS
            if dims.get(d, {}).get("value") is not None
        ]
        blocks.append(
            {
                "ordinal": 2,
                "block_kind": "dimensions",
                "title": "Research-priority dimensions",
                "payload": {
                    "dimensions": [
                        {
                            "dimension": k,
                            "value": (
                                float(v["value"]) if v["value"] is not None else None
                            ),
                            "authority": v["authority"],
                            "inputs_present": v["inputs_present"],
                            "inputs_expected": v["inputs_expected"],
                        }
                        for k, v in sorted(dims.items())
                    ],
                    "aggregate_present": len(present),
                    "aggregate_expected": len(AGGREGATE_DIMENSIONS),
                },
                "evidence": {
                    "source": "fundamental_dimensions",
                    "engine_version": engine,
                },
                "authority": "research_priority",
            }
        )

    blocks.append(
        {
            "ordinal": 3,
            "block_kind": "risks",
            "title": "Deterministic risk facts",
            "payload": {
                "risks": [
                    {
                        "kind": r["risk_kind"],
                        "observed": (
                            float(r["observed_value"])
                            if r["observed_value"] is not None
                            else None
                        ),
                        "threshold": (
                            float(r["threshold"])
                            if r["threshold"] is not None
                            else None
                        ),
                        "breached": bool(r["breached"]),
                        "statement": r["statement"],
                        "invalidates": r["invalidates"],
                    }
                    for r in risks
                ],
                "breached": sum(1 for r in risks if r["breached"]),
                "evaluated": len(risks),
            },
            "evidence": {"source": "research_risk_facts", "as_of": today.isoformat()},
        }
    )

    blocks.append(
        {
            "ordinal": 4,
            "block_kind": "events",
            "title": "Evidence timeline",
            "payload": {
                "events": [
                    {
                        "class": e["event_class"],
                        "occurred_at": e["occurred_at"].isoformat(),
                        "first_known_at": e["first_known_at"].isoformat(),
                        "title": e["title"],
                        "source_ref": e["source_ref"],
                    }
                    for e in events
                ],
                "count": len(events),
            },
            "evidence": {
                "source": "research_events",
                # Stated so a reader knows the timeline is as-of, not current.
                "known_by": today.isoformat(),
            },
        }
    )

    blocks.append(
        {
            "ordinal": 5,
            "block_kind": "chain_exposure",
            "title": "Chain participation",
            "payload": {
                "exposures": [
                    {
                        "chain": e["chain"],
                        "role": e["role"],
                        "magnitude": (
                            float(e["magnitude"])
                            if e["magnitude"] is not None
                            else None
                        ),
                        "basis": e["magnitude_basis"],
                        "status": e["status"],
                        "source_ref": e["source_ref"],
                    }
                    for e in exposures
                ],
                "with_magnitude": sum(
                    1 for e in exposures if e["magnitude"] is not None
                ),
                "count": len(exposures),
            },
            "evidence": {
                "source": "company_exposure",
                "taxonomy_version": taxonomy,
            },
        }
    )

    manifest = _manifest(
        engine_version=engine,
        taxonomy_version=taxonomy,
        evidence_policy="current_vintage",
        as_of=today,
        scope={"ticker": symbol},
    )
    check_single_basis(manifest, blocks)
    status = STATUS_PARTIAL if notes else STATUS_PUBLISHED

    if not publish:
        from uw_scan.storage.research_reports import content_hash

        return {
            "report_key": f"company:{symbol}",
            "manifest_jsonb": manifest,
            "blocks": blocks,
            "content_hash": content_hash(blocks),
            "status": status,
        }

    out = reports.publish(
        report_key=f"company:{symbol}",
        report_type="company",
        title=f"{symbol} research report",
        manifest=manifest,
        blocks=blocks,
        status=status,
    )
    log.info(
        "assemble_company_report %s v%s changed=%s",
        symbol, out.get("version_no"), out.get("changed"),
    )
    return out


def assemble_chain_report(
    conn: psycopg.Connection,
    chain: str,
    *,
    schema: str = "uw_scan",
    engine_version: str | None = None,
    as_of: date | None = None,
    publish: bool = True,
) -> dict[str, Any]:
    """Build (and optionally publish) one chain report."""
    today = as_of or date.today()
    scores = FundamentalScoresRepository(conn, schema=schema)
    engine = engine_version or scores.active_version()
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    events_repo = ResearchEventsRepository(conn, schema=schema)
    reports = ResearchReportsRepository(conn, schema=schema)

    taxonomy = tax.active_version()
    members = tax.members(taxonomy, chain) if taxonomy else []
    exposures = tax.exposures(taxonomy, chain=chain) if taxonomy else []
    coverage = tax.exposure_coverage(taxonomy).get(chain, {}) if taxonomy else {}

    dims_repo = FundamentalDimensionsRepository(conn, schema=schema)
    # `chain_membership` is grained (chain, layer, ticker): a company placed in
    # two layers appears twice. Every count below is therefore taken over
    # DISTINCT TICKERS, or a two-layer name would be double-weighted in the mean
    # and the numerator would eventually exceed a denominator that deduped.
    priority_by_ticker: dict[str, float | None] = {}
    per_member = []
    for m in members:
        ticker = m["ticker"]
        if ticker not in priority_by_ticker:
            d = dims_repo.for_ticker(ticker, engine_version=engine) if engine else {}
            pri = d.get("priority", {}).get("value")
            priority_by_ticker[ticker] = float(pri) if pri is not None else None
        per_member.append(
            {
                "ticker": ticker,
                "layer": m["layer"],
                "evidence_class": m["evidence_class"],
                "priority": priority_by_ticker[ticker],
            }
        )
    distinct_members = sorted(priority_by_ticker)
    with_result = [t for t in distinct_members if priority_by_ticker[t] is not None]

    notes = []
    if len(with_result) < 3:
        notes.append(
            f"only {len(with_result)} of {len(distinct_members)} members carry "
            "a compatible result; the chain aggregate abstains"
        )

    blocks: list[dict[str, Any]] = [
        {
            "ordinal": 0,
            "block_kind": "scope",
            "title": f"{chain} — chain research scope",
            "payload": {
                "chain": chain,
                "as_of": today.isoformat(),
                "engine_version": engine,
                "taxonomy_version": taxonomy,
                "members": len(distinct_members),
                # Placements, not companies. Stated separately because they are
                # not the same number and a report must not let the reader
                # discover that by subtraction.
                "member_placements": len(members),
            },
            "derivation": "the report manifest, restated for the reader",
        },
        _unsupported_block(1, events_repo, notes),
        {
            "ordinal": 2,
            "block_kind": "chain_coverage",
            "title": "Coverage and denominators",
            "payload": {
                "members": coverage.get("members", len(distinct_members)),
                "with_exposure": coverage.get("with_exposure", 0),
                "with_magnitude": coverage.get("with_magnitude", 0),
                "with_compatible_result": len(with_result),
            },
            "evidence": {"source": "chain_membership + company_exposure"},
        },
        {
            "ordinal": 3,
            "block_kind": "chain_members",
            "title": "Members by layer",
            "payload": {"members": per_member},
            "evidence": {
                "source": "chain_membership",
                "taxonomy_version": taxonomy,
            },
            # Ordering members by priority exercises the composite's permission
            # and nothing stronger.
            "authority": "research_priority",
        },
        {
            "ordinal": 4,
            "block_kind": "chain_aggregate",
            "title": "Aggregate priority",
            "payload": {
                "priority_mean": (
                    sum(priority_by_ticker[t] for t in with_result)
                    / len(with_result)
                    if len(with_result) >= 3
                    else None
                ),
                "n": len(with_result),
                "abstains": len(with_result) < 3,
            },
            "derivation": (
                "mean of the priority dimension over DISTINCT members carrying a "
                "compatible result, one vote per company; abstains below 3"
            ),
            "authority": "research_priority",
        },
        {
            "ordinal": 5,
            "block_kind": "chain_exposure",
            "title": "Disclosed economic exposure",
            "payload": {
                "exposures": [
                    {
                        "ticker": e["ticker"],
                        "role": e["role"],
                        "magnitude": (
                            float(e["magnitude"])
                            if e["magnitude"] is not None
                            else None
                        ),
                        "basis": e["magnitude_basis"],
                        "status": e["status"],
                    }
                    for e in exposures
                    if e["magnitude"] is not None
                ],
                "asserted_without_magnitude": sum(
                    1 for e in exposures if e["magnitude"] is None
                ),
            },
            "evidence": {"source": "company_exposure"},
        },
    ]

    manifest = _manifest(
        engine_version=engine,
        taxonomy_version=taxonomy,
        evidence_policy="current_vintage",
        as_of=today,
        scope={"chain": chain},
    )
    check_single_basis(manifest, blocks)
    status = STATUS_PARTIAL if notes else STATUS_PUBLISHED

    if not publish:
        from uw_scan.storage.research_reports import content_hash

        return {
            "report_key": f"chain:{chain}",
            "manifest_jsonb": manifest,
            "blocks": blocks,
            "content_hash": content_hash(blocks),
            "status": status,
        }

    out = reports.publish(
        report_key=f"chain:{chain}",
        report_type="chain",
        title=f"{chain} chain report",
        manifest=manifest,
        blocks=blocks,
        status=status,
    )
    log.info(
        "assemble_chain_report %s v%s changed=%s",
        chain, out.get("version_no"), out.get("changed"),
    )
    return out


def assemble_comparison_report(
    conn: psycopg.Connection,
    tickers: Sequence[str],
    *,
    schema: str = "uw_scan",
    engine_version: str | None = None,
    as_of: date | None = None,
    publish: bool = True,
) -> dict[str, Any]:
    """Compare a named group of companies side by side.

    The third shape the north star asks for, and the one where an omission does
    the most damage: a comparison that silently drops the names it could not
    score reads as a complete ranking of the group the operator asked about. So
    every requested ticker appears in the coverage block whether or not it
    carries a result, and the ordered table names its own denominator.

    `report_key` is the SORTED ticker set, so asking the same question twice —
    in any order — versions one report rather than forking two.
    """
    symbols = sorted({t.upper() for t in tickers})
    if not symbols:
        raise ValueError("a comparison needs at least one ticker")
    today = as_of or date.today()
    scores = FundamentalScoresRepository(conn, schema=schema)
    engine = engine_version or scores.active_version()
    dims_repo = FundamentalDimensionsRepository(conn, schema=schema)
    events_repo = ResearchEventsRepository(conn, schema=schema)
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    reports = ResearchReportsRepository(conn, schema=schema)
    taxonomy = tax.active_version()

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for symbol in symbols:
        dims = dims_repo.for_ticker(symbol, engine_version=engine) if engine else {}
        if not dims:
            missing.append(symbol)
            continue
        rows.append(
            {
                "ticker": symbol,
                "priority": (
                    float(dims["priority"]["value"])
                    if dims.get("priority", {}).get("value") is not None
                    else None
                ),
                "dimensions": {
                    k: (float(v["value"]) if v["value"] is not None else None)
                    for k, v in sorted(dims.items())
                    if k != "priority"
                },
                "inputs_present": sum(v["inputs_present"] for v in dims.values()),
                "inputs_expected": sum(v["inputs_expected"] for v in dims.values()),
            }
        )
    # Ordered by priority, which is exactly the permission the composite earned:
    # it orders names cross-sectionally. A name with no priority sorts last by
    # ticker rather than as zero — zero is the cross-section MEAN.
    rows.sort(key=lambda r: (r["priority"] is None, -(r["priority"] or 0.0), r["ticker"]))

    notes: list[str] = []
    if missing:
        notes.append(
            f"{len(missing)} of {len(symbols)} requested names carry no result "
            f"under engine {engine} ({', '.join(missing)}) — a gap in Argon, "
            "not a fact about those companies, and they are absent from the "
            "ordering rather than ranked last"
        )

    shared = tax.exposures(taxonomy, ticker=None) if taxonomy else []
    by_chain: dict[str, list[str]] = {}
    for exposure in shared:
        if exposure["ticker"] in symbols:
            by_chain.setdefault(exposure["chain"], []).append(exposure["ticker"])
    common = sorted(
        ({"chain": c, "members": sorted(set(t))} for c, t in by_chain.items() if len(set(t)) > 1),
        key=lambda e: (-len(e["members"]), e["chain"]),
    )

    blocks: list[dict[str, Any]] = [
        {
            "ordinal": 0,
            "block_kind": "scope",
            "title": f"Comparison — {', '.join(symbols)}",
            "payload": {
                "tickers": symbols,
                "as_of": today.isoformat(),
                "engine_version": engine,
                "taxonomy_version": taxonomy,
                "requested": len(symbols),
            },
            "derivation": "the report manifest, restated for the reader",
        },
        _unsupported_block(1, events_repo, notes),
        {
            "ordinal": 2,
            "block_kind": "comparison_coverage",
            "title": "Who is in this comparison",
            "payload": {
                "requested": len(symbols),
                "with_result": len(rows),
                "without_result": missing,
            },
            "evidence": {
                "source": "fundamental_dimensions",
                "engine_version": engine,
            },
        },
        {
            "ordinal": 3,
            "block_kind": "comparison_table",
            "title": "Research priority, ordered",
            "payload": {"rows": rows, "n": len(rows)},
            "evidence": {
                "source": "fundamental_dimensions",
                "engine_version": engine,
            },
            # Ordering names against each other is the composite's measured
            # permission and the ceiling of this program. Nothing here sizes,
            # times, or recommends.
            "authority": "research_priority",
        },
        {
            "ordinal": 4,
            "block_kind": "chain_exposure",
            "title": "Chains these names share",
            "payload": {
                "shared_chains": common,
                # Stated so co-membership is never read as a relationship: the
                # capex-demand ledger measured +0.247 -> +0.015 (p=0.44) once
                # sector was held constant.
                "reading": (
                    "co-membership is a shared classification, not a measured "
                    "link between these companies"
                ),
            },
            "evidence": {
                "source": "company_exposure",
                "taxonomy_version": taxonomy,
            },
        },
    ]

    manifest = _manifest(
        engine_version=engine,
        taxonomy_version=taxonomy,
        evidence_policy="current_vintage",
        as_of=today,
        scope={"tickers": symbols},
    )
    check_single_basis(manifest, blocks)
    status = STATUS_PARTIAL if notes else STATUS_PUBLISHED
    report_key = f"comparison:{'-'.join(symbols)}"

    if not publish:
        from uw_scan.storage.research_reports import content_hash

        return {
            "report_key": report_key,
            "manifest_jsonb": manifest,
            "blocks": blocks,
            "content_hash": content_hash(blocks),
            "status": status,
        }

    out = reports.publish(
        report_key=report_key,
        report_type="comparison",
        title=f"{' vs '.join(symbols)} comparison",
        manifest=manifest,
        blocks=blocks,
        status=status,
    )
    log.info(
        "assemble_comparison_report %s v%s changed=%s",
        report_key, out.get("version_no"), out.get("changed"),
    )
    return out
