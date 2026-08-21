"""Persistence for versioned macro domain states and the evidence they stood on.

Two rules shape this module.  A state is identified by its *method* -- the question
(domain, as_of), the engine that answered it, and a hash of the parameters plus the exact
observations -- so recomputing an unchanged state is a no-op rather than a new row, and a
recompute that produces a different answer from identical inputs is a defect that raises
instead of quietly appending.  And a state is only as good as the observations it can
name, so evidence rows carry real ``obs_id`` foreign keys; a state whose evidence cannot
be pointed at is refused rather than stored as an unfalsifiable claim.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from uw_scan.macro.contracts import (
    ConfidenceTerm,
    Contradiction,
    EvidenceRef,
    FactorState,
    MacroDomainState,
    MacroSubState,
    Velocity,
)

#: Fields that the method identity claims to determine.  If two rows share
#: (domain, as_of, engine_version, inputs_hash) and differ in any of these, the engine is
#: not a function of its inputs and the identity is a lie.
_DETERMINED_BY_IDENTITY = (
    "state",
    "direction",
    "confidence",
    "velocity_jsonb",
    "confidence_reasons_jsonb",
    "contradictions_jsonb",
    "factors_jsonb",
    "notes_jsonb",
    # Determined too: a sub-state is computed from the same observations, so two rows
    # sharing an inputs_hash and differing here would mean a role's answer moved without
    # its inputs moving.
    "sub_states_jsonb",
)


class _MacroDomainStateMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_macro_domain_state(
        self,
        state: MacroDomainState,
        *,
        computed_at: datetime,
    ) -> int:
        """Persist a state with its evidence, or return the id of the identical one.

        ``computed_at`` is separate from ``state.as_of`` on purpose: the first is when we
        did the arithmetic, the second is the instant the answer is about.  Collapsing
        them would make every backfilled replay look like it was known in real time.
        """
        _require_aware("computed_at", computed_at)
        _require_aware("as_of", state.as_of)
        if computed_at < state.as_of:
            raise ValueError(
                f"computed_at {computed_at.isoformat()} precedes as_of "
                f"{state.as_of.isoformat()}: a state cannot be computed before the "
                "instant it answers for"
            )
        evidence = _evidence_rows(state)
        payload = _state_payload(state, computed_at=computed_at)

        with self._conn.transaction():
            with self._conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self._schema}.macro_domain_states (
                      domain, as_of, computed_at, engine_version, inputs_hash,
                      state, direction, velocity_jsonb, confidence,
                      confidence_reasons_jsonb, contradictions_jsonb,
                      factors_jsonb, notes_jsonb, sub_states_jsonb
                    )
                    VALUES (
                      %(domain)s, %(as_of)s, %(computed_at)s, %(engine_version)s,
                      %(inputs_hash)s, %(state)s, %(direction)s, %(velocity_jsonb)s,
                      %(confidence)s, %(confidence_reasons_jsonb)s,
                      %(contradictions_jsonb)s, %(factors_jsonb)s, %(notes_jsonb)s,
                      %(sub_states_jsonb)s
                    )
                    ON CONFLICT (domain, as_of, engine_version, inputs_hash)
                    DO NOTHING
                    RETURNING state_id
                    """,
                    payload,
                )
                inserted = cur.fetchone()
                if inserted is not None:
                    state_id = int(inserted["state_id"])
                    _insert_evidence(cur, self._schema, state_id, evidence)
                    return state_id

                existing = self._existing_identical_state(cur, payload)
                state_id = int(existing["state_id"])
                _assert_same_evidence(cur, self._schema, state_id, evidence)
                return state_id

    def _existing_identical_state(
        self, cur: psycopg.Cursor, payload: dict[str, Any]
    ) -> dict[str, Any]:
        cur.execute(
            f"""
            SELECT * FROM {self._schema}.macro_domain_states
            WHERE domain = %(domain)s AND as_of = %(as_of)s
              AND engine_version = %(engine_version)s
              AND inputs_hash = %(inputs_hash)s
            """,
            payload,
        )
        existing = cur.fetchone()
        if existing is None:  # pragma: no cover - the conflict target just matched
            raise RuntimeError(
                "conflicting macro domain state vanished mid-transaction"
            )
        divergent = [
            field
            for field in _DETERMINED_BY_IDENTITY
            if _normalized(existing[field]) != _normalized(payload[field])
        ]
        if divergent:
            raise ValueError(
                f"macro domain state {payload['domain']} at "
                f"{payload['as_of'].isoformat()} recomputed to a different answer from "
                f"identical inputs (engine={payload['engine_version']}, "
                f"inputs_hash={payload['inputs_hash'][:12]}): "
                f"{', '.join(divergent)} changed"
            )
        return existing

    def fetch_macro_domain_state(self, state_id: int) -> dict[str, Any] | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT * FROM {self._schema}.macro_domain_states WHERE state_id = %s",
                (state_id,),
            )
            return cur.fetchone()

    def fetch_macro_domain_state_as_of(
        self,
        domain: str,
        as_of: datetime,
        *,
        engine_version: str | None = None,
        strictly_before: bool = False,
    ) -> dict[str, Any] | None:
        """The most recent published state that answers for a time at or before ``as_of``.

        ``strictly_before`` excludes ``as_of`` itself, which is what a recompute needs.
        Selecting the prior state with ``<=`` would let a second run of the same instant
        pick up the state the first run just wrote, so the revision term would differ
        between two runs of identical evidence -- and the identity guard would then
        (correctly) refuse the write.  A deterministic prior keeps recompute a no-op.

        Ties on ``as_of`` are broken by the later ``computed_at``.  That is not backdating:
        the evidence trigger already refuses any observation that became available after
        ``as_of``, so a later recompute of the same instant can only mean we had ingested
        more of what was already published then -- a better answer to the same question.
        """
        _require_aware("as_of", as_of)
        bound = "as_of < %s" if strictly_before else "as_of <= %s"
        clauses = ["domain = %s", bound, "status = 'published'"]
        params: list[Any] = [domain, as_of]
        if engine_version is not None:
            clauses.append("engine_version = %s")
            params.append(engine_version)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT * FROM {self._schema}.macro_domain_states
                WHERE {" AND ".join(clauses)}
                ORDER BY as_of DESC, computed_at DESC, state_id DESC
                LIMIT 1
                """,
                params,
            )
            return cur.fetchone()

    def fetch_macro_domain_state_evidence(self, state_id: int) -> list[dict[str, Any]]:
        """The exact observations behind a state, in the order the engine used them.

        The artifact is joined for ``source_kind`` and ``source_url``: whether a piece of
        evidence came from the publisher itself or from a third-party shadow is the first
        thing a reader needs about it, and it lives on the artifact, not the observation.
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT e.ordinal, e.causal_role, o.*,
                       a.source_kind, a.source_url, a.media_type
                FROM {self._schema}.macro_domain_state_evidence e
                JOIN {self._schema}.macro_observations o ON o.obs_id = e.obs_id
                JOIN {self._schema}.macro_source_artifacts a
                  ON a.artifact_id = o.artifact_id
                WHERE e.state_id = %s
                ORDER BY e.ordinal
                """,
                (state_id,),
            )
            return list(cur.fetchall())

    def quarantine_macro_domain_state(
        self, state_id: int, *, reason: str, at: datetime
    ) -> bool:
        """Withdraw a state from service without editing what it said.

        One-way and enforced in the database: a wrong answer stays on the record.
        """
        _require_aware("at", at)
        if not reason.strip():
            raise ValueError("quarantine requires a reason")
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.macro_domain_states
                SET status = 'quarantined',
                    quarantined_at = %s,
                    quarantine_reason = %s
                WHERE state_id = %s AND status = 'published'
                """,
                (at, reason, state_id),
            )
            return cur.rowcount == 1


def _insert_evidence(
    cur: psycopg.Cursor,
    schema: str,
    state_id: int,
    evidence: Sequence[tuple[int, str, int]],
) -> None:
    if not evidence:
        raise ValueError(
            "a macro domain state must name the observations it stood on; storing one "
            "with no evidence would make it unreconstructable"
        )
    cur.executemany(
        f"""
        INSERT INTO {schema}.macro_domain_state_evidence (
          state_id, obs_id, causal_role, ordinal
        )
        VALUES (%s, %s, %s, %s)
        """,
        [(state_id, obs_id, role, ordinal) for obs_id, role, ordinal in evidence],
    )


def _assert_same_evidence(
    cur: psycopg.Cursor,
    schema: str,
    state_id: int,
    evidence: Sequence[tuple[int, str, int]],
) -> None:
    cur.execute(
        f"""
        SELECT obs_id, causal_role
        FROM {schema}.macro_domain_state_evidence
        WHERE state_id = %s
        """,
        (state_id,),
    )
    stored = {(int(row["obs_id"]), row["causal_role"]) for row in cur.fetchall()}
    requested = {(obs_id, role) for obs_id, role, _ordinal in evidence}
    if stored != requested:
        raise ValueError(
            f"macro domain state {state_id} already stands on a different evidence set; "
            "the same inputs_hash cannot name different observations"
        )


def _evidence_rows(state: MacroDomainState) -> list[tuple[int, str, int]]:
    rows: list[tuple[int, str, int]] = []
    for ordinal, ref in enumerate(state.evidence_refs):
        if ref.obs_id is None:
            raise ValueError(
                f"evidence {ref.series_id} @ {ref.period_end.isoformat()} carries no "
                "obs_id; a state may only be persisted from observations that exist in "
                "the evidence store, never from values computed in memory"
            )
        rows.append((int(ref.obs_id), ref.causal_role, ordinal))
    return rows


def _state_payload(state: MacroDomainState, *, computed_at: datetime) -> dict[str, Any]:
    return {
        "domain": state.domain,
        "as_of": state.as_of,
        "computed_at": computed_at,
        "engine_version": state.engine_version,
        "inputs_hash": state.inputs_hash,
        "state": state.state,
        "direction": state.direction,
        "velocity_jsonb": Jsonb(
            [
                {
                    "metric": item.metric,
                    "value": _decimal_text(item.value),
                    "unit": item.unit,
                    "window_months": item.window_months,
                    "unavailable_reason": item.unavailable_reason,
                }
                for item in state.velocity
            ]
        ),
        "confidence": state.confidence,
        "confidence_reasons_jsonb": Jsonb(
            [
                {
                    "term": item.term,
                    "value": _decimal_text(item.value),
                    "detail": item.detail,
                    # Persisted, not re-derived on read.  A value alone cannot say
                    # whether it drags -- 1.00 is neutral for a multiplicand and
                    # total for a penalty -- so a hand-listed field set that omits
                    # this writes rows a reader can only guess at.
                    "kind": item.kind,
                }
                for item in state.confidence_reasons
            ]
        ),
        "contradictions_jsonb": Jsonb(
            [
                {"rule": item.rule, "detail": item.detail}
                for item in state.contradictions
            ]
        ),
        "factors_jsonb": Jsonb(
            [
                {
                    "name": item.name,
                    "causal_role": item.causal_role,
                    "series_id": item.series_id,
                    "period_end": item.period_end.isoformat(),
                    "value": _decimal_text(item.value),
                    "unit": item.unit,
                    "direction": item.direction,
                    "change_over_window": _decimal_text(item.change_over_window),
                    "available_at": item.available_at.isoformat(),
                    "age_days": item.age_days,
                    "freshness": _decimal_text(item.freshness),
                    "quality_status": item.quality_status,
                    "source": item.source,
                    "source_kind": item.source_kind,
                }
                for item in state.factors
            ]
        ),
        "notes_jsonb": Jsonb(list(state.notes)),
        "sub_states_jsonb": Jsonb(
            [
                {
                    "role": item.role,
                    "state": item.state,
                    "direction": item.direction,
                    "confidence": _decimal_text(item.confidence),
                    "series_ids": list(item.series_ids),
                    "latest_period_end": (
                        item.latest_period_end.isoformat()
                        if item.latest_period_end
                        else None
                    ),
                    "unavailable_reason": item.unavailable_reason,
                    "velocity": [
                        {
                            "metric": leg.metric,
                            "value": _decimal_text(leg.value),
                            "unit": leg.unit,
                            "window_months": leg.window_months,
                            "unavailable_reason": leg.unavailable_reason,
                        }
                        for leg in item.velocity
                    ],
                    "confidence_reasons": [
                        {
                            "term": reason.term,
                            "value": _decimal_text(reason.value),
                            "detail": reason.detail,
                            "kind": reason.kind,
                        }
                        for reason in item.confidence_reasons
                    ],
                }
                for item in state.sub_states
            ]
        ),
    }


def _decimal_text(value: Decimal | None) -> str | None:
    """Decimals travel through JSON as text.

    JSON has no decimal type, and a float round trip would quietly move the last digits
    of a value whose whole purpose is being reproducible from an audit trail.
    """
    return None if value is None else format(value, "f")


def _normalized(value: Any) -> Any:
    """Compare what Postgres stored against what we sent, ignoring representation."""
    if isinstance(value, Jsonb):
        return json.loads(json.dumps(value.obj))
    if isinstance(value, Decimal):
        return value.normalize()
    return value


def _require_aware(field: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def macro_domain_state_from_row(
    row: dict[str, Any], evidence_rows: Sequence[dict[str, Any]]
) -> MacroDomainState:
    """Rebuild the engine's own answer from what was stored.

    The exact inverse of :func:`_state_payload` plus the evidence join, and the pair is
    the claim this module makes: a stored state is the state, not a summary of one.
    Evidence is a required argument rather than an optional extra because a state
    reconstructed without its lineage is precisely the unfalsifiable object the table
    exists to refuse -- an empty default would let a caller produce one by omission.

    Its first consumer is revision detection: the state job feeds the preceding state
    back into the engine so ``load_bearing_input_revised_since_prior_state`` can fire.
    Without a rehydrator that term is dead code in production, because nothing else can
    turn a row back into the object the engine compares against.
    """
    return MacroDomainState(
        domain=row["domain"],
        state=row["state"],
        direction=row["direction"],
        velocity=tuple(
            Velocity(
                metric=item["metric"],
                value=_decimal_or_none(item["value"]),
                unit=item["unit"],
                window_months=item["window_months"],
                unavailable_reason=item["unavailable_reason"],
            )
            for item in row["velocity_jsonb"]
        ),
        confidence=Decimal(row["confidence"]),
        confidence_reasons=tuple(
            ConfidenceTerm(
                term=item["term"],
                value=Decimal(item["value"]),
                detail=item["detail"],
                # Rows written before the column carried a kind are multiplicands,
                # which is what every term in the product was at the time.
                kind=item.get("kind", "multiplicand"),
            )
            for item in row["confidence_reasons_jsonb"]
        ),
        contradictions=tuple(
            Contradiction(rule=item["rule"], detail=item["detail"])
            for item in row["contradictions_jsonb"]
        ),
        factors=tuple(
            FactorState(
                name=item["name"],
                causal_role=item["causal_role"],
                series_id=item["series_id"],
                period_end=date.fromisoformat(item["period_end"]),
                value=Decimal(item["value"]),
                unit=item["unit"],
                direction=item["direction"],
                change_over_window=_decimal_or_none(item["change_over_window"]),
                available_at=datetime.fromisoformat(item["available_at"]),
                age_days=item["age_days"],
                freshness=Decimal(item["freshness"]),
                quality_status=item["quality_status"],
                source=item["source"],
                source_kind=item["source_kind"],
            )
            for item in row["factors_jsonb"]
        ),
        evidence_refs=tuple(
            EvidenceRef(
                series_id=item["series_id"],
                period_end=item["period_end"],
                causal_role=item["causal_role"],
                available_at=item["available_at"],
                obs_id=item["obs_id"],
                artifact_id=item["artifact_id"],
            )
            for item in evidence_rows
        ),
        engine_version=row["engine_version"],
        inputs_hash=row["inputs_hash"],
        as_of=row["as_of"],
        notes=tuple(row["notes_jsonb"]),
        sub_states=tuple(
            MacroSubState(
                role=item["role"],
                state=item["state"],
                direction=item["direction"],
                velocity=tuple(
                    Velocity(
                        metric=leg["metric"],
                        value=_decimal_or_none(leg["value"]),
                        unit=leg["unit"],
                        window_months=leg["window_months"],
                        unavailable_reason=leg["unavailable_reason"],
                    )
                    for leg in item["velocity"]
                ),
                confidence=Decimal(item["confidence"]),
                confidence_reasons=tuple(
                    ConfidenceTerm(
                        term=reason["term"],
                        value=Decimal(reason["value"]),
                        detail=reason["detail"],
                        kind=reason["kind"],
                    )
                    for reason in item["confidence_reasons"]
                ),
                series_ids=tuple(item["series_ids"]),
                latest_period_end=(
                    date.fromisoformat(item["latest_period_end"])
                    if item["latest_period_end"]
                    else None
                ),
                unavailable_reason=item["unavailable_reason"],
            )
            # Rows written before migration 127 default to an empty array, which is
            # true of them: they carried no sub-states.
            for item in row.get("sub_states_jsonb") or []
        ),
    )


def _decimal_or_none(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
