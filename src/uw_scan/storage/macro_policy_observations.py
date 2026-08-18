"""Policy observations keyed by what the publisher said, not by which bytes said it.

Separate from :mod:`uw_scan.storage.macro_context`, which owns the general MC0
observation identity used by every other macro series.  That identity includes
``artifact_id`` and ``available_at``, both properties of our fetch: re-fetching
an unchanged release through a new artifact row produces a "new" observation
that is not a new fact.  For policy releases -- where one release is legitimately
served as several exact artifacts (HTML and PDF, or a cosmetic markup reissue) --
that turns one committee decision into several.

Here the identity is :func:`uw_scan.macro_evidence.macro_policy_semantic_hash`,
so an unchanged release re-read from different bytes resolves to the single
existing observation with an extra lineage link, while a genuinely changed fact
or a corrected semantic parser earns a new observation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from uw_scan.macro_evidence import (
    macro_observation_content_hash,
    macro_policy_semantic_hash,
)

from .macro_context import _require_aware, _validate_artifact_bounds

LINEAGE_RELATIONS: Final = frozenset({"parsed_from", "corroborates"})


class _MacroPolicyObservationMixin:
    """Write policy observations under a byte-independent semantic identity."""

    _conn: psycopg.Connection

    def upsert_macro_policy_observation(
        self,
        row: dict[str, Any],
        *,
        seen_at: datetime,
        relation: str = "parsed_from",
    ) -> tuple[int, bool]:
        """Resolve one policy fact, returning ``(obs_id, created)``.

        When the semantic identity already exists, no second observation is
        written and this artifact is added as another witness -- ``created`` is
        False, which a caller reports as "unchanged" rather than as a new
        vintage.  ``relation`` describes THIS artifact's role: the publisher may
        reissue the same page with request-varying bytes, and the parser genuinely
        read both, so both are ``parsed_from``.  A sibling that carries the same
        fact without being parsed (the PDF beside the HTML) is ``corroborates``.
        """
        if relation not in LINEAGE_RELATIONS:
            raise ValueError(f"unknown macro lineage relation {relation!r}")
        _require_aware("seen_at", seen_at)
        _require_aware("published_at", row.get("published_at"), optional=True)
        _require_aware("available_at", row.get("available_at"))
        semantic_hash = macro_policy_semantic_hash(row)
        content_hash = macro_observation_content_hash(row)
        artifact_id = int(row["artifact_id"])

        with self._conn.transaction():
            with self._conn.cursor() as cur:
                _validate_artifact_bounds(cur, self._schema, [row])
                cur.execute(
                    f"""
                    SELECT obs_id
                    FROM {self._schema}.macro_observations
                    WHERE semantic_hash = %s
                    """,
                    (semantic_hash,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    obs_id = int(existing[0])
                    cur.execute(
                        f"""
                        UPDATE {self._schema}.macro_observations
                        SET last_seen_at = GREATEST(last_seen_at, %s)
                        WHERE obs_id = %s
                        """,
                        (seen_at, obs_id),
                    )
                    _link(cur, self._schema, obs_id, artifact_id, relation)
                    return obs_id, False

                cur.execute(
                    f"""
                    INSERT INTO {self._schema}.macro_observations (
                      artifact_id, domain, series_id, period_end, frequency, unit,
                      value_numeric, value_text, value_jsonb,
                      source, source_record_id, release_key,
                      published_at, available_at,
                      first_observed_at, last_seen_at,
                      content_hash, semantic_hash, parser_version,
                      quality_status, cost_class
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s,
                      %s, %s, %s,
                      %s, %s, %s,
                      %s, %s,
                      %s, %s,
                      %s, %s, %s,
                      %s, %s
                    )
                    RETURNING obs_id
                    """,
                    (
                        artifact_id,
                        row["domain"],
                        row["series_id"],
                        row["period_end"],
                        row["frequency"],
                        row["unit"],
                        row.get("value_numeric"),
                        row.get("value_text"),
                        Jsonb(row["value_json"])
                        if row.get("value_json") is not None
                        else None,
                        row["source"],
                        row["source_record_id"],
                        row["release_key"],
                        row.get("published_at"),
                        row["available_at"],
                        seen_at,
                        seen_at,
                        content_hash,
                        semantic_hash,
                        row["parser_version"],
                        row["quality_status"],
                        row["cost_class"],
                    ),
                )
                inserted = cur.fetchone()
                assert inserted is not None
                obs_id = int(inserted[0])
                _link(cur, self._schema, obs_id, artifact_id, relation)
                return obs_id, True

    def link_macro_observation_artifact(
        self, *, obs_id: int, artifact_id: int, relation: str
    ) -> None:
        """Record another artifact that witnesses an existing observation."""
        with self._conn.cursor() as cur:
            _link(cur, self._schema, obs_id, artifact_id, relation)

    def fetch_macro_observation_artifacts(self, obs_id: int) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT artifact_id, relation
                FROM {self._schema}.macro_observation_artifacts
                WHERE obs_id = %s
                ORDER BY artifact_id, relation
                """,
                (obs_id,),
            )
            return [
                {"artifact_id": int(artifact_id), "relation": relation}
                for artifact_id, relation in cur.fetchall()
            ]


def _link(
    cur: psycopg.Cursor, schema: str, obs_id: int, artifact_id: int, relation: str
) -> None:
    if relation not in LINEAGE_RELATIONS:
        raise ValueError(f"unknown macro lineage relation {relation!r}")
    cur.execute(
        f"""
        INSERT INTO {schema}.macro_observation_artifacts (
          obs_id, artifact_id, relation
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (obs_id, artifact_id, relation) DO NOTHING
        """,
        (obs_id, artifact_id, relation),
    )
