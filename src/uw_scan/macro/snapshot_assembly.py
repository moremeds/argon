"""Decide whether four domain answers are one coherent chain.

The defect: each domain job catches its own exception and the loop continues. A failed
rates job lets USD read the PREVIOUS rates state -- which still satisfies
``available_at <= as_of`` -- persist a new USD state citing it, and gold consume the
mixture. Every timestamp involved is honest, every state is individually well-formed, and
four cards render fresh.

**No clock can catch that, because nothing is late.** What is wrong is WHICH answer the
downstream stood on. The only thing that knows is the upstream ``state_id`` the downstream
actually cited, which ``macro_domain_state_dependencies`` (migration 128) already records.
So compatibility is decided by edge identity and never by timestamp proximity.

**The assembler names the break; it never repairs it.** Substituting a fresher upstream to
make the chain look coherent would make this a fabrication layer rather than a monitoring
one. An incompatible domain keeps its real answer and its real edge, and carries a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from uw_scan.macro_evidence import macro_artifact_content_identity

from .snapshot import (
    CAUSAL_ORDER,
    MacroContextSnapshot,
    SnapshotDomain,
    SnapshotReason,
    SnapshotStatus,
)

ASSEMBLER_VERSION = "snapshot/1"

#: Worst finding wins. A chain that is both missing a domain and internally inconsistent
#: must report the inconsistency: "rates never ran" sends an operator to the scheduler,
#: "USD stood on the wrong rates" sends them to the data, and reporting the milder one
#: sends them to the wrong place.
_SEVERITY: dict[SnapshotStatus, int] = {
    "complete": 0,
    "stale": 1,
    "partial": 2,
    "incompatible": 3,
}


@dataclass(frozen=True)
class DomainCandidate:
    """One domain's answer, with the upstream state ids it actually cited.

    ``cited_upstream`` maps upstream domain -> the ``state_id`` this domain stood on. It
    comes from the stored dependency edges, never from re-reading what the upstream would
    say now -- the question is what the downstream DID consult, not what was available.
    """

    domain: str
    state_id: int
    as_of: datetime
    cited_upstream: dict[str, int]


def assemble_snapshot(
    candidates: list[DomainCandidate],
    *,
    as_of: datetime,
    assembled_at: datetime,
    assembler_version: str = ASSEMBLER_VERSION,
) -> MacroContextSnapshot:
    """Compose the candidates into one snapshot with a compatibility verdict."""
    held = {c.domain: c for c in candidates}
    reasons: list[SnapshotReason] = []

    for domain in CAUSAL_ORDER:
        if domain not in held:
            reasons.append(
                SnapshotReason(
                    domain=domain,
                    kind="absent",
                    detail="no state was available for this instant",
                )
            )

    for domain in CAUSAL_ORDER:
        candidate = held.get(domain)
        if candidate is None:
            continue
        for upstream_domain, cited_id in sorted(candidate.cited_upstream.items()):
            upstream = held.get(upstream_domain)
            if upstream is None:
                # Present and answered, from something this snapshot cannot show. That is
                # an incompatibility of the DOWNSTREAM, not another absence: reporting it
                # as absent would point an operator at a domain that ran fine.
                reasons.append(
                    SnapshotReason(
                        domain=domain,
                        kind="incompatible",
                        detail=(
                            f"cited {upstream_domain} state {cited_id}, which is not in "
                            f"this snapshot"
                        ),
                    )
                )
            elif upstream.state_id != cited_id:
                reasons.append(
                    SnapshotReason(
                        domain=domain,
                        kind="incompatible",
                        detail=(
                            f"cited {upstream_domain} state {cited_id}, but this snapshot "
                            f"holds {upstream.state_id}"
                        ),
                    )
                )

    status: SnapshotStatus = "complete"
    for reason in reasons:
        candidate_status: SnapshotStatus = (
            "partial" if reason.kind == "absent" else reason.kind
        )
        if _SEVERITY[candidate_status] > _SEVERITY[status]:
            status = candidate_status

    domains = tuple(
        SnapshotDomain(domain=domain, state_id=held[domain].state_id, ordinal=ordinal)
        for ordinal, domain in enumerate(d for d in CAUSAL_ORDER if d in held)
    )

    return MacroContextSnapshot(
        as_of=as_of,
        assembled_at=assembled_at,
        status=status,
        domains=domains,
        inputs_hash=_inputs_hash(
            domains=domains, status=status, assembler_version=assembler_version
        ),
        assembler_version=assembler_version,
        reasons=tuple(reasons),
    )


def _inputs_hash(
    *,
    domains: tuple[SnapshotDomain, ...],
    status: SnapshotStatus,
    assembler_version: str,
) -> str:
    """Identify a snapshot by the state IDENTITIES it holds and the verdict it reached.

    Assembly TIME is deliberately not an input: rerunning the same states two hours later
    is the same answer, and hashing the clock would make every rerun a new row.

    The status IS an input. Two assemblies over the same state ids that disagree about
    coherence are two different answers, and storing one under the other's identity would
    silently lose one of them.

    Hashing state ids rather than their contents is what makes a stored snapshot immune to
    later evidence revision: a revision produces a NEW state with a new id, so an old
    snapshot keeps citing exactly what it stood on.
    """
    record = {
        "assembler_version": assembler_version,
        "domains": [
            {"domain": d.domain, "ordinal": d.ordinal, "state_id": d.state_id}
            for d in domains
        ],
        "status": status,
    }
    content_hash, _length = macro_artifact_content_identity(raw_json=record)
    return content_hash
