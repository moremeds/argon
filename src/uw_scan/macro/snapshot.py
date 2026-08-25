"""The macro context snapshot: four domain answers held as ONE answer.

The four domain states already exist and already record what they stood on. What did not
exist is the object that says they belong together. Without it ``/macro`` composes four
independent latest reads, and the nightly worker -- which does use one ``as_of`` and the
right causal order -- catches each domain's exception and continues. So a failed rates job
lets USD read the PREVIOUS rates state (still satisfying ``available_at <= as_of``),
persist a new USD state citing it, and gold consume the mixture. Four cards render fresh.

**A snapshot's job is to REFUSE, never to repair.** It may not substitute a fresher
upstream to make a chain look coherent; it names the incompatibility and lets the reader
see it. Substitution is how a monitoring layer becomes a fabrication layer, and it is the
one property of this object that must not be traded away for a tidier page.

Status is decided by dependency-edge IDENTITY, not by timestamp proximity: a downstream
state is compatible when the upstream ``state_id`` it actually cited is the one this
snapshot holds for that upstream's domain. ``macro_domain_state_dependencies``
(migration 128) already records those edges, so the check reads them rather than inferring
anything from clocks.

The assembler that computes the status lives in the next slice; this module is the shape
it produces and the storage layer consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

#: Worst-finding-wins, in this order. ``complete`` is the only one a reader may treat as a
#: coherent chain; the other three are refusals of different shapes and must stay
#: distinguishable, because "rates never ran" and "rates ran but USD ignored it" call for
#: different operator actions.
SnapshotStatus = Literal["complete", "partial", "incompatible", "stale"]

#: Why a domain is not contributing a compatible answer.
ReasonKind = Literal["absent", "incompatible", "stale"]

#: Causal order. The snapshot stores an explicit ordinal rather than relying on this tuple
#: at read time, so a stored snapshot keeps the order it was assembled with even if the
#: chain is ever reordered.
CAUSAL_ORDER: tuple[str, ...] = ("inflation", "policy_rates", "usd", "gold")


@dataclass(frozen=True)
class SnapshotReason:
    """One named defect, attributed to the domain that carries it.

    ``detail`` is free text for an operator, not a parse target. The pair a consumer
    branches on is ``(domain, kind)``.
    """

    domain: str
    kind: ReasonKind
    detail: str

    def as_json(self) -> dict[str, str]:
        return {"domain": self.domain, "kind": self.kind, "detail": self.detail}


@dataclass(frozen=True)
class SnapshotDomain:
    """One domain's answer, pinned by state id.

    Absence is the LACK of one of these, never one carrying a null state. A nullable
    ``state_id`` would make every reader decide again what a null meant, and one of them
    would decide it meant zero.
    """

    domain: str
    state_id: int
    ordinal: int


@dataclass(frozen=True)
class MacroContextSnapshot:
    """Four domain answers, their compatibility verdict, and the identity that reproduces it.

    ``inputs_hash`` covers the state identities and the assembler's parameters, so
    re-assembling the same instant from the same states is a no-op rather than a second
    opinion. A later evidence revision cannot change a stored snapshot's hash: the hash is
    over state IDENTITIES, and a revision produces a new state rather than editing one.
    """

    as_of: datetime
    assembled_at: datetime
    status: SnapshotStatus
    domains: tuple[SnapshotDomain, ...]
    inputs_hash: str
    assembler_version: str
    reasons: tuple[SnapshotReason, ...] = field(default_factory=tuple)

    def domain_state_id(self, domain: str) -> int | None:
        return next((d.state_id for d in self.domains if d.domain == domain), None)

    def reason_for(self, domain: str) -> SnapshotReason | None:
        return next((r for r in self.reasons if r.domain == domain), None)
