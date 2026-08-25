"""The assembler decides compatibility from dependency-edge IDENTITY, not from clocks.

The defect this exists for: each domain job catches its own exception and the loop
continues, so a failed rates job lets USD read the PREVIOUS rates state -- which still
satisfies ``available_at <= as_of`` -- persist a new USD state citing it, and gold consume
the mixture. Every timestamp involved is honest. Four cards render fresh.

No clock can catch that, because nothing is late. What is wrong is WHICH answer the
downstream stood on, and the only thing that knows is the upstream state_id the downstream
actually cited. These tests fix that, plus the rule that must never be traded away: the
assembler names the break, it never substitutes a fresher upstream to hide it.

Pure: the assembler takes rows and returns a verdict, so it is tested without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from uw_scan.macro.snapshot import CAUSAL_ORDER
from uw_scan.macro.snapshot_assembly import DomainCandidate, assemble_snapshot

AS_OF = datetime(2026, 8, 24, 7, 40, tzinfo=UTC)


def _candidate(
    domain: str,
    state_id: int,
    *,
    cited: dict[str, int] | None = None,
    as_of: datetime = AS_OF,
) -> DomainCandidate:
    """One domain's answer plus the upstream state ids it actually cited."""
    return DomainCandidate(
        domain=domain, state_id=state_id, as_of=as_of, cited_upstream=cited or {}
    )


def _coherent() -> list[DomainCandidate]:
    """The four domains as production had them on 2026-08-24: one as_of, edges agreeing."""
    return [
        _candidate("inflation", 101),
        _candidate("policy_rates", 102),
        _candidate("usd", 103, cited={"policy_rates": 102}),
        _candidate(
            "gold", 104, cited={"inflation": 101, "policy_rates": 102, "usd": 103}
        ),
    ]


class TestACoherentChainIsComplete:
    def test_four_agreeing_domains_are_complete(self) -> None:
        snap = assemble_snapshot(_coherent(), as_of=AS_OF, assembled_at=AS_OF)
        assert snap.status == "complete"
        assert snap.reasons == ()

    def test_the_domains_are_stored_in_causal_order(self) -> None:
        # Reversed input: the ordinal must come from the causal chain, not arrival order.
        snap = assemble_snapshot(
            list(reversed(_coherent())), as_of=AS_OF, assembled_at=AS_OF
        )
        assert [d.domain for d in snap.domains] == list(CAUSAL_ORDER)
        assert [d.ordinal for d in snap.domains] == [0, 1, 2, 3]

    def test_a_domain_citing_no_upstream_is_normal(self) -> None:
        # Inflation is the head of the chain; having no upstream is not a defect.
        snap = assemble_snapshot(_coherent(), as_of=AS_OF, assembled_at=AS_OF)
        assert snap.reason_for("inflation") is None


class TestTheStaleUpstreamCannotHide:
    """The failure the snapshot was built for, and it is invisible to every timestamp."""

    def test_a_downstream_citing_a_different_upstream_is_incompatible(self) -> None:
        rows = _coherent()
        rows[2] = _candidate(
            "usd", 103, cited={"policy_rates": 99}
        )  # last night's rates
        snap = assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF)
        assert snap.status == "incompatible"

    def test_the_reason_names_the_domain_that_broke_the_chain(self) -> None:
        rows = _coherent()
        rows[2] = _candidate("usd", 103, cited={"policy_rates": 99})
        snap = assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF)
        reason = snap.reason_for("usd")
        assert reason is not None and reason.kind == "incompatible"
        assert "policy_rates" in reason.detail

    def test_an_incompatible_domain_is_still_held(self) -> None:
        # Dropping it would turn "USD answered, from the wrong evidence" into "USD is
        # missing" -- a different defect, and one an operator would chase in the wrong
        # place. The snapshot names the break; it does not hide the answer.
        rows = _coherent()
        rows[2] = _candidate("usd", 103, cited={"policy_rates": 99})
        snap = assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF)
        assert snap.domain_state_id("usd") == 103

    def test_the_assembler_never_substitutes_a_fresher_upstream(self) -> None:
        # THE rule. Repairing the chain here would make the page look coherent and make
        # the snapshot a fabrication layer. The stored edge stays what USD really cited.
        rows = _coherent()
        rows[2] = _candidate("usd", 103, cited={"policy_rates": 99})
        snap = assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF)
        assert snap.domain_state_id("policy_rates") == 102
        assert snap.status != "complete"

    def test_timestamps_alone_would_have_missed_it(self) -> None:
        # Every candidate shares one as_of; only the cited identity differs. A proximity
        # check sees nothing wrong here, which is exactly why identity is the test.
        rows = _coherent()
        rows[2] = _candidate("usd", 103, cited={"policy_rates": 99}, as_of=AS_OF)
        assert len({c.as_of for c in rows}) == 1
        assert (
            assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF).status
            != "complete"
        )


class TestAMissingDomainIsPartial:
    def test_three_of_four_is_partial(self) -> None:
        rows = [c for c in _coherent() if c.domain != "gold"]
        snap = assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF)
        assert snap.status == "partial"
        assert snap.reason_for("gold").kind == "absent"

    def test_a_domain_citing_an_absent_upstream_is_incompatible_not_absent(
        self,
    ) -> None:
        # USD cited rates; rates is not in this snapshot at all. USD is present and
        # answered -- from something this snapshot cannot show -- so it is incompatible.
        rows = [c for c in _coherent() if c.domain != "policy_rates"]
        snap = assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF)
        assert snap.reason_for("policy_rates").kind == "absent"
        assert snap.reason_for("usd").kind == "incompatible"

    def test_incompatible_outranks_partial(self) -> None:
        # Worst finding wins. A chain that is BOTH missing a domain and internally
        # inconsistent must not report the milder of the two.
        rows = [c for c in _coherent() if c.domain != "gold"]
        rows[2] = _candidate("usd", 103, cited={"policy_rates": 99})
        assert (
            assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF).status
            == "incompatible"
        )

    def test_no_domains_at_all_is_partial_not_complete(self) -> None:
        snap = assemble_snapshot([], as_of=AS_OF, assembled_at=AS_OF)
        assert snap.status == "partial"
        assert len(snap.reasons) == len(CAUSAL_ORDER)


class TestTheIdentityReproduces:
    def test_the_same_states_produce_the_same_hash(self) -> None:
        a = assemble_snapshot(_coherent(), as_of=AS_OF, assembled_at=AS_OF)
        b = assemble_snapshot(
            list(reversed(_coherent())),
            as_of=AS_OF,
            assembled_at=AS_OF + timedelta(hours=2),
        )
        # Assembly TIME is not an input: rerunning the same states later is the same answer.
        assert a.inputs_hash == b.inputs_hash

    def test_a_different_state_id_is_a_different_hash(self) -> None:
        rows = _coherent()
        rows[0] = _candidate("inflation", 999)
        assert (
            assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF).inputs_hash
            != assemble_snapshot(
                _coherent(), as_of=AS_OF, assembled_at=AS_OF
            ).inputs_hash
        )

    def test_a_missing_domain_is_a_different_hash(self) -> None:
        rows = [c for c in _coherent() if c.domain != "gold"]
        assert (
            assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF).inputs_hash
            != assemble_snapshot(
                _coherent(), as_of=AS_OF, assembled_at=AS_OF
            ).inputs_hash
        )

    def test_the_status_is_part_of_the_identity(self) -> None:
        # Two assemblies over the same state ids that disagree about coherence are two
        # different answers, and storing one under the other's identity would lose one.
        rows = _coherent()
        rows[2] = _candidate("usd", 103, cited={"policy_rates": 99})
        assert (
            assemble_snapshot(rows, as_of=AS_OF, assembled_at=AS_OF).inputs_hash
            != assemble_snapshot(
                _coherent(), as_of=AS_OF, assembled_at=AS_OF
            ).inputs_hash
        )
