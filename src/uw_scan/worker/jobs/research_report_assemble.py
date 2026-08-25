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
from datetime import date
from typing import Any

import psycopg

from uw_scan.fundamentals.claims import REGISTRY
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

log = logging.getLogger(__name__)


def _manifest(
    *,
    engine_version: str | None,
    taxonomy_version: str | None,
    evidence_policy: str,
    as_of: date,
    scope: dict[str, Any],
) -> dict[str, Any]:
    """The frozen question. Everything needed to reproduce the content."""
    return {
        "engine_version": engine_version,
        "taxonomy_version": taxonomy_version,
        "evidence_policy": evidence_policy,
        "as_of": as_of.isoformat(),
        "scope": scope,
        # Pinned so a change to the assembler itself invalidates the replay
        # rather than silently producing different content under the same
        # manifest.
        "assembler_version": "report-assembler-v1",
    }


#: Manifest fields a block's evidence may restate. If it restates one, it must
#: agree — a report that mixes two engine versions or two taxonomy versions is
#: not one answer, it is two answers stapled together, and the reader has no way
#: to tell which block came from which.
_PINNED_FIELDS = ("engine_version", "taxonomy_version")


def check_single_basis(
    manifest: dict[str, Any], blocks: list[dict[str, Any]]
) -> None:
    """Refuse a report whose blocks disagree with the manifest. Raises ValueError.

    Called before every publish and before every hash. The alternative — letting
    it through and noting the mixture in prose — produces a document whose
    numbers are individually true and jointly meaningless.
    """
    for block in blocks:
        evidence = block.get("evidence") or {}
        for field in _PINNED_FIELDS:
            if field not in evidence:
                continue
            if evidence[field] != manifest.get(field):
                raise ValueError(
                    f"block {block['block_kind']!r} claims {field}="
                    f"{evidence[field]!r} but the manifest froze "
                    f"{manifest.get(field)!r}; a report carries ONE basis"
                )
        as_of = evidence.get("as_of") or evidence.get("known_by")
        if as_of is not None and as_of != manifest.get("as_of"):
            raise ValueError(
                f"block {block['block_kind']!r} is as-of {as_of!r} but the "
                f"manifest froze {manifest.get('as_of')!r}"
            )


def _unsupported_block(
    ordinal: int, events_repo: ResearchEventsRepository, extra: list[str]
) -> dict[str, Any]:
    killed = [c for c in events_repo.classes() if c["status"] == "killed"]
    capped = [
        c.key for c in REGISTRY if c.authority.value == "descriptive"
    ]
    return {
        "ordinal": ordinal,
        "block_kind": "unsupported",
        "title": "What this report cannot answer",
        "payload": {
            "killed_event_classes": [
                {"class": c["event_class"], "why": c["rationale"]} for c in killed
            ],
            "descriptive_only": capped,
            "notes": extra,
        },
        "derivation": (
            "research_event_classes where status='killed', plus claim-registry "
            "entries capped at descriptive"
        ),
    }


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
