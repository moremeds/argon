"""Seed the versioned research taxonomy and derive disclosed exposures (M5).

Three passes, deliberately separable:

1. **mirror** the shipped `watchlist_chain` rail into a taxonomy version. Every
   row lands as `evidence_class='mirrored'`, which is neither a disclosure nor an
   analyst assertion made here — it is a copy, and saying so is what keeps the
   new object from inheriting authority the old one never had.
2. **derive** exposures from `revenue_breakdown_obs` through the published alias
   rules. These carry a real magnitude and cite both the observation and the
   alias.
3. **assert** membership-only exposures for names with no disclosure that maps.
   Role and direction, never a number — migration 140's CHECK refuses one.

Zero provider budget: every input is already in Postgres.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import psycopg

from uw_scan.fundamentals.chain_nodes import ChainSpec
from uw_scan.storage.research_taxonomy import (
    EVIDENCE_ANALYST,
    EVIDENCE_DISCLOSED,
    EVIDENCE_INFERRED,
    EVIDENCE_MIRRORED,
    ResearchTaxonomyRepository,
)

log = logging.getLogger(__name__)

TAXONOMY_V1 = "argon-research-v1"

UNCLASSIFIED = "unclassified"

#: Chain -> research domain. A chain absent from this map gets UNCLASSIFIED,
#: never a section domain: an unclassified chain must be VISIBLY unassigned
#: rather than silently swept onto a desk it does not belong to. These 38
#: entries are the complete `watchlist_chain` rail as of 2026-08-28 (verified
#: against the mini). Entries marked `# judgement` are the debatable ones —
#: deliberately surfaced as one-line data edits, not buried in logic.
CHAIN_DOMAIN: dict[str, str] = {
    # --- the optical chain (its own domain; the desk's exemplar node) ---
    "Networking/Optical": "optical_communication",
    # --- silicon and compute ---
    "Semi-Cap/EDA": "ai_infrastructure",
    "Semi-Logic/ASIC": "ai_infrastructure",
    "Computer/GPU": "ai_infrastructure",
    "Memory/Storage": "ai_infrastructure",
    "Analog/Power-Semi": "ai_infrastructure",
    "Foundry": "ai_infrastructure",
    # --- the compute buyers ---
    "Cloud/Hyperscaler": "ai_infrastructure",
    "AI-Cloud/NeoCloud": "ai_infrastructure",
    "Foundation-Model-Proxy": "ai_infrastructure",
    "AI-Native-Software": "ai_infrastructure",
    "Data-Platform": "ai_infrastructure",
    "Software/SaaS": "ai_infrastructure",  # judgement
    "DevTools/Observability": "ai_infrastructure",  # judgement
    "Cybersecurity": "ai_infrastructure",  # judgement
    "AI-App/Consumer-Net": "ai_infrastructure",  # judgement
    "Healthcare-AI/LS-Tools": "ai_infrastructure",  # judgement
    "Robotics/Automation": "ai_infrastructure",  # judgement
    "Devices/Endpoint": "ai_infrastructure",  # judgement
    "IT-Services/Integration": "ai_infrastructure",  # judgement
    # --- the physical datacenter buildout (this is what makes dc_buildout real) ---
    "Generation/Nuclear": "dc_buildout",
    "Power/Electrical": "dc_buildout",
    "EPC/Construction": "dc_buildout",
    "Cooling/Thermal": "dc_buildout",
    "DC-REIT/Colo": "dc_buildout",
    # --- everything else: real chains, not part of THIS section ---
    "Banks": UNCLASSIFIED,
    "Credit": UNCLASSIFIED,
    "Fintech": UNCLASSIFIED,
    "Consumer": UNCLASSIFIED,
    "Healthcare": UNCLASSIFIED,
    "Energy": UNCLASSIFIED,
    "Crypto": UNCLASSIFIED,
    "Space": UNCLASSIFIED,
    "Quantum": UNCLASSIFIED,  # judgement: adjacency, not today's AI supply chain
    "Macro": UNCLASSIFIED,
    "Sector-ETF": UNCLASSIFIED,
    "Beta": UNCLASSIFIED,
    "M7": UNCLASSIFIED,  # a grouping, not a supply-chain node
}

#: The layer catalogue the mirrored rail becomes. `layer_rank` is a READING
#: order, upstream to downstream — not a causal edge, and nothing propagates
#: along it. The measured basis for that restraint: the capex-demand ledger's
#: cross-name relationship collapsed from +0.247 to +0.015 (p=0.44) once
#: same-sector pairs were compared.
LAYER_RANK = {
    "Upstream": 10,
    "Semi": 20,
    "Component": 25,
    "Hardware": 30,
    "Infrastructure": 40,
    "Platform": 50,
    "Application": 60,
    "Customer": 70,
}


def _rank(layer: str) -> int:
    for key, rank in LAYER_RANK.items():
        if layer.lower().startswith(key.lower()):
            return rank
    return 0


def mirror_watchlist_chain(
    conn: psycopg.Connection,
    *,
    schema: str = "uw_scan",
    version: str = TAXONOMY_V1,
    fallback_domain: str = UNCLASSIFIED,
) -> dict[str, int]:
    """Copy the shipped chain rail into `version`. The shipped rail is untouched."""
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    repo.publish_version(
        version,
        note="mirrored from watchlist_chain; see worker/jobs/research_taxonomy_seed",
        activate=True,
    )
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT chain, layer FROM {schema}.watchlist_chain")
        pairs = cur.fetchall()
        cur.execute(f"SELECT ticker, chain, layer FROM {schema}.watchlist_chain")
        rows = cur.fetchall()
        # A name already openly a member of this CHAIN under any layer is
        # already mirrored — see the loop below for why the layer is excluded.
        cur.execute(
            f"""SELECT DISTINCT chain, ticker FROM {schema}.chain_membership
                 WHERE taxonomy_version = %s AND valid_to IS NULL""",
            (version,),
        )
        already = {(chain, ticker) for chain, ticker in cur.fetchall()}

    repo.define_chains(
        version,
        [
            {
                "domain": CHAIN_DOMAIN.get(chain, fallback_domain),
                "chain": chain,
                "layer": layer,
                "layer_rank": _rank(layer),
                "description": None,
            }
            for chain, layer in pairs
        ],
    )
    added = already_member = 0
    for ticker, chain, layer in rows:
        # The skip is keyed on (chain, ticker) and NOT on the layer, because
        # `seed_chain_spec` MOVES a mirrored name off the placeholder layer onto
        # the chain's real one. `add_membership`'s own guard keys on
        # (version, chain, LAYER, ticker), so after a seed it sees no open row
        # at the placeholder layer and re-opens one — and the next seed closes
        # it again. Two intervals per ticker per run, forever, which is exactly
        # the manufactured history `add_membership` exists to prevent and would
        # falsify the healer registry's standing claim that a reseed opens no
        # interval for an unchanged placement.
        if (chain, ticker.upper()) in already:
            already_member += 1
            continue
        added += repo.add_membership(
            version,
            chain=chain,
            layer=layer,
            ticker=ticker,
            evidence_class="mirrored",
            approved_by="watchlist_chain",
            note="copied from the shipped chain filter rail",
        )
    counters = {
        "chains": len(pairs),
        "memberships": len(rows),
        "opened": added,
        "already_member": already_member,
    }
    log.info("mirror_watchlist_chain: %s", counters)
    return counters


#: Strongest claim first. Used ONLY to pick which of a ticker's several open
#: placements a re-home carries across — never to rank or filter evidence
#: anywhere a reader sees it.
_EVIDENCE_PRECEDENCE = (
    EVIDENCE_DISCLOSED,
    EVIDENCE_ANALYST,
    EVIDENCE_INFERRED,
    EVIDENCE_MIRRORED,
)


def _rehome_note(note: str | None, from_layer: str, to_layer: str) -> str:
    """Append the move to the row's own note; provenance is not overwritten."""
    moved = f"re-homed from layer {from_layer!r} onto {to_layer!r}"
    return f"{note}; {moved}" if note else moved


def seed_chain_spec(
    conn: psycopg.Connection,
    spec: ChainSpec,
    *,
    schema: str = "uw_scan",
    version: str = TAXONOMY_V1,
) -> dict[str, int]:
    """Give one chain its real layer set and re-home its memberships onto it.

    Standing up a chain analysis node is rows and no assembler logic — the
    extension contract `chain_nodes` declares. This function is the whole of the
    "code" half, and it is generic over `ChainSpec`: a sixth chain adds a
    constant, not a branch.

    Placeholder layers (the rank-0 `L3` the watchlist mirror lays down) are
    SUPERSEDED, not deleted. The new layer rows land beside them and the
    memberships move, so "was this name in the chain when that report was
    written" stays answerable — which is the reason `chain_membership` carries
    validity intervals instead of a `removed_at`.
    """
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    # Order is load-bearing: `chain_membership` has an FK on
    # (taxonomy_version, chain, layer) -> `research_chains`, so the target layer
    # must exist before a membership can name it.
    repo.define_chains(
        version,
        [
            {
                "domain": spec.domain,
                "chain": spec.chain,
                "layer": layer.layer,
                "layer_rank": layer.rank,
                "description": layer.description,
            }
            for layer in spec.layers
        ],
    )
    moved = opened = 0
    if len(spec.layers) == 1:
        # Reinsert-THEN-retire, and never `UPDATE ... SET layer`: open membership
        # identity is the partial unique index chain_membership_open_uq
        # (taxonomy_version, chain, layer, ticker) WHERE valid_to IS NULL, so an
        # in-place UPDATE collides with a row the same statement has not closed
        # yet. A multi-layer spec cannot be re-homed automatically at all —
        # which layer a name belongs to is a research judgement, not a default.
        #
        # ORDER IS THE FAILURE MODE. Closing first and inserting after leaves a
        # window in which a crash strands the chain with ZERO open memberships,
        # and no re-run can heal it: the recovery SELECT looks for
        # `layer <> target AND valid_to IS NULL`, which by then matches nothing.
        # Inserting first cannot collide (the layer differs), and a crash in the
        # window leaves the ticker open on BOTH layers — a state the next run
        # finds and finishes. Failure-safe rather than failure-lossy.
        target = spec.layers[0].layer
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, evidence_class, approved_by, note, layer
                      FROM {schema}.chain_membership
                     WHERE taxonomy_version = %s AND chain = %s
                       AND layer <> %s AND valid_to IS NULL
                     ORDER BY ticker,
                              array_position(%s::text[], evidence_class),
                              membership_id""",
                (version, spec.chain, target, list(_EVIDENCE_PRECEDENCE)),
            )
            # One re-home per ticker. Ordered strongest-evidence-first above, so
            # a name openly placed under two layers is carried across by its
            # STRONGEST claim — a disclosure does not get overwritten by a
            # mirrored copy just because the copy sorted first.
            source: dict[str, tuple[str, str, str | None, str]] = {}
            for ticker, evidence, approver, note, layer in cur.fetchall():
                source.setdefault(ticker, (evidence, approver, note, layer))

        for ticker, (evidence, approver, note, layer) in source.items():
            # `evidence_class` and `approved_by` are CARRIED, never rewritten.
            # Migration 139 says that column exists to keep an analyst's
            # judgement distinguishable from a copy of the watchlist rail after
            # the fact; hardcoding `mirrored` here would silently demote every
            # human assertion this function is ever pointed at — and
            # `Optical-Communication`'s placements are `analyst`.
            opened += repo.add_membership(
                version,
                chain=spec.chain,
                layer=target,
                ticker=ticker,
                evidence_class=evidence,
                approved_by=approver,
                note=_rehome_note(note, layer, target),
            )
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE {schema}.chain_membership
                       SET valid_to = now()
                     WHERE taxonomy_version = %s AND chain = %s
                       AND layer <> %s AND valid_to IS NULL""",
                (version, spec.chain, target),
            )
        # Count the tickers whose placeholder row was CLOSED, not the intervals
        # opened. A ticker already open on both layers is a real re-home whose
        # `add_membership` correctly returns False, and reporting that as zero
        # would tell an operator nothing moved when something did.
        moved = len(source)
    conn.commit()
    counters = {"layers": len(spec.layers), "memberships": moved, "opened": opened}
    log.info("seed_chain_spec %s: %s", spec.chain, counters)
    return counters


def seed_aliases(
    conn: psycopg.Connection,
    rows: Sequence[dict[str, Any]],
    *,
    schema: str = "uw_scan",
    version: str = TAXONOMY_V1,
) -> int:
    """Publish segment->chain mapping rules. Idempotent."""
    if not rows:
        return 0
    sql = f"""
        INSERT INTO {schema}.chain_segment_alias
                    (taxonomy_version, chain, alias_pattern, axis, role,
                     approved_by, note)
             VALUES (%(v)s, %(chain)s, %(pattern)s, %(axis)s, %(role)s,
                     %(approved_by)s, %(note)s)
        ON CONFLICT (taxonomy_version, chain, alias_pattern, axis) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.executemany(
            sql,
            [
                {
                    "v": version,
                    "chain": r["chain"],
                    "pattern": r["pattern"],
                    "axis": r.get("axis", "us-gaap:StatementBusinessSegmentsAxis"),
                    "role": r.get("role", "beneficiary"),
                    "approved_by": r["approved_by"],
                    "note": r.get("note"),
                }
                for r in rows
            ],
        )
    conn.commit()
    return len(rows)


def derive_disclosed_exposure(
    conn: psycopg.Connection,
    *,
    schema: str = "uw_scan",
    version: str = TAXONOMY_V1,
) -> dict[str, int]:
    """Turn disclosed segment revenue into exposures with a real magnitude.

    The share's denominator is the period's UNTAGGED consolidated row — the same
    rule the concentration derivation uses, and for the same reason: a segment
    divided by the sum of its siblings is a share of what was BROKEN OUT, not a
    share of the company, and the two differ by whatever the filer left
    unallocated.

    Only the newest report_date per ticker is used. Older periods are history,
    not additional exposure, and summing them would multiply a company's
    apparent participation by the number of quarters it has filed.
    """
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    counters = {
        "candidates": 0,
        "matched": 0,
        "written": 0,
        "no_denominator": 0,
        "ambiguous": 0,
    }

    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT chain, alias_pattern, axis, role
                  FROM {schema}.chain_segment_alias
                 WHERE taxonomy_version = %s""",
            (version,),
        )
        aliases = cur.fetchall()
        if not aliases:
            log.info("derive_disclosed_exposure: no alias rules published")
            return counters

        # Newest period per ticker, its consolidated denominator, and every
        # tagged single-axis member on that period.
        cur.execute(
            f"""
            WITH latest AS (
                SELECT ticker, max(report_date) AS report_date
                  FROM {schema}.revenue_breakdown_obs
                 GROUP BY ticker
            ),
            denom AS (
                SELECT o.ticker, o.report_date, max(o.value) AS total
                  FROM {schema}.revenue_breakdown_obs o
                  JOIN latest l USING (ticker, report_date)
                 WHERE cardinality(o.axis) = 0
                 GROUP BY o.ticker, o.report_date
            )
            SELECT o.obs_id, o.ticker, o.axis[1], o.members[1], o.value, d.total
              FROM {schema}.revenue_breakdown_obs o
              JOIN latest l USING (ticker, report_date)
              LEFT JOIN denom d USING (ticker, report_date)
             WHERE cardinality(o.axis) = 1 AND cardinality(o.members) = 1
            """
        )
        candidates = cur.fetchall()

    rows: list[dict[str, Any]] = []
    for obs_id, ticker, axis, member, value, total in candidates:
        counters["candidates"] += 1
        local = member.split(":")[-1].lower()
        # EVERY match, then the most specific one — never the first the database
        # happened to return. `datacenter` is a substring of
        # `datacenterandcommunications`, so a first-match-wins loop filed
        # Coherent's optical segment (74.6% of revenue) under whichever chain the
        # unordered SELECT listed first. Longest pattern wins because a longer
        # alias is a narrower claim.
        hits = [
            (chain, pattern, role)
            for chain, pattern, alias_axis, role in aliases
            if alias_axis == axis and pattern.lower() in local
        ]
        if not hits:
            continue
        counters["matched"] += 1
        longest = max(len(p) for _, p, _ in hits)
        best = [h for h in hits if len(h[1]) == longest]
        if len({chain for chain, _, _ in best}) > 1:
            # Two chains stake an equally specific claim on one segment. There is
            # no evidence here to break the tie, so the derivation writes
            # nothing: a coin flip would publish a magnitude that reads as
            # disclosed fact.
            counters["ambiguous"] += 1
            continue
        chain, pattern, role = best[0]
        if not total or float(total) <= 0:
            # No consolidated row means no honest denominator. Recorded as a
            # gap rather than divided by the sum of siblings, which would
            # silently answer a different question.
            counters["no_denominator"] += 1
            continue
        share = float(value) / float(total)
        if not (0.0 <= share <= 1.0):
            counters["no_denominator"] += 1
            continue
        rows.append(
            {
                "taxonomy_version": version,
                "ticker": ticker,
                "chain": chain,
                "role": role,
                "direction": None,
                "counterparty": None,
                "magnitude": share,
                "magnitude_basis": "segment_share",
                "confidence": "high",
                "status": "disclosed",
                "source_kind": "revenue_breakdown_obs",
                "source_ref": member,
                "source_obs_id": obs_id,
                "note": f"alias {pattern!r} on {axis}",
            }
        )

    counters["written"] = repo.record_exposure(rows)
    log.info("derive_disclosed_exposure: %s", counters)
    return counters


def assert_membership_exposure(
    conn: psycopg.Connection,
    *,
    schema: str = "uw_scan",
    version: str = TAXONOMY_V1,
) -> dict[str, int]:
    """Record role-only exposure for members with no disclosure that maps.

    These carry NO magnitude. That is the honest state and the database enforces
    it: a member with no mapped disclosure is a company an analyst placed in a
    chain, which is a research assertion and not a measurement.
    """
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT m.ticker, m.chain
                  FROM {schema}.chain_membership m
                  LEFT JOIN {schema}.company_exposure e
                         ON e.taxonomy_version = m.taxonomy_version
                        AND e.chain = m.chain AND e.ticker = m.ticker
                        AND e.valid_to IS NULL
                 WHERE m.taxonomy_version = %s AND m.valid_to IS NULL
                   AND e.exposure_id IS NULL""",
            (version,),
        )
        gaps = cur.fetchall()

    written = repo.record_exposure(
        [
            {
                "taxonomy_version": version,
                "ticker": ticker,
                "chain": chain,
                "role": "other",
                "magnitude": None,
                "magnitude_basis": "qualitative",
                "confidence": "low",
                "status": "asserted",
                "source_kind": "chain_membership",
                "note": "membership only; no disclosed segment maps to this chain",
            }
            for ticker, chain in gaps
        ]
    )
    counters = {"gaps": len(gaps), "written": written}
    log.info("assert_membership_exposure: %s", counters)
    return counters
