"""Assemble the four domain states for one instant into a snapshot, or refuse.

This job makes no network call and computes no state.  It reads answers that already
exist and asks one question of them: *do these four belong together?*  The nightly pass
runs the domains in causal order under a single ``as_of``, but each domain catches its
own exception and the loop continues -- so a failed rates job lets USD read the PREVIOUS
rates answer, persist a new state citing it, and gold consume the mixture.  Every
timestamp involved is honest and nothing is late.  What is wrong is which answer the
downstream stood on, and the only record of that is the dependency edge it wrote.

So the verdict comes from edge IDENTITY, never from timestamp proximity: does the
upstream ``state_id`` a domain actually cited equal the one this snapshot holds for that
upstream's domain.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from uw_scan.macro.snapshot import CAUSAL_ORDER, MacroContextSnapshot
from uw_scan.macro.snapshot_assembly import DomainCandidate, assemble_snapshot
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


def load_domain_candidates(
    repo: Repository, *, as_of: datetime
) -> list[DomainCandidate]:
    """Each domain's answer in force at ``as_of``, with the upstreams it actually cited.

    The edges are read back from storage rather than taken from the run that wrote them.
    That is deliberate and it is what makes one code path serve both tonight's assembly
    and a replay of any past instant: a replay has no run to ask, and a path that only
    works live would be a second implementation to keep in step.
    """
    candidates: list[DomainCandidate] = []
    for domain in CAUSAL_ORDER:
        row = repo.fetch_macro_domain_state_as_of(domain, as_of)
        if row is None:
            continue
        state_id = int(row["state_id"])
        cited = {
            str(edge["upstream_domain"]): int(edge["upstream_state_id"])
            for edge in repo.fetch_macro_domain_state_dependencies(state_id)
        }
        candidates.append(
            DomainCandidate(
                domain=domain,
                state_id=state_id,
                as_of=row["as_of"],
                cited_upstream=cited,
            )
        )
    return candidates


def macro_context_snapshot_job(
    repo: Repository,
    *,
    as_of: datetime | None = None,
    assembled_at: datetime | None = None,
) -> MacroContextSnapshot | None:
    """Assemble and persist the snapshot for ``as_of``; ``None`` when no domain answered.

    Returning ``None`` rather than an all-absent snapshot keeps "we have never computed a
    state" distinguishable from "we computed states and they disagree".  Both are
    refusals; only the second one is about the macro picture.
    """
    instant = as_of or datetime.now(UTC)
    candidates = load_domain_candidates(repo, as_of=instant)
    if not candidates:
        logger.info("macro context snapshot: no domain state at or before %s", instant)
        return None

    snapshot = assemble_snapshot(
        candidates,
        as_of=instant,
        assembled_at=assembled_at or datetime.now(UTC),
    )
    snapshot_id = repo.insert_macro_context_snapshot(snapshot)
    logger.info(
        "macro context snapshot %d: %s over %d domain(s)%s",
        snapshot_id,
        snapshot.status,
        len(snapshot.domains),
        "".join(f" [{r.domain}: {r.kind}]" for r in snapshot.reasons),
    )
    return snapshot
