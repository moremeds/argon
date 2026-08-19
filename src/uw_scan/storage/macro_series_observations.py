"""Series observations keyed by the vintage, not by the fetch that carried it.

A published statistical series has a different re-read shape from a policy release, and
neither of the two identities already in this package fits it.

:mod:`uw_scan.storage.macro_context` identifies an observation partly by ``artifact_id``.
For a per-release fetch that is fine: one release, one payload.  A series query returns
the whole history in one payload, so the night a new CPI print lands the payload changes,
a new artifact is written, and *every* historical observation in it re-hashes to a new
identity.  One month of new data would rewrite eighteen months of unchanged facts.

:mod:`uw_scan.storage.macro_policy_observations` solves that with ``semantic_hash``, but
that column is not available here: migration 121 constrains it to the policy formula with
a trigger and requires a ``release_key`` alongside it, and a FRED vintage has neither.

So the identity is the vintage itself -- ``(source, series_id, period_end, available_at)``
-- which is exactly what ALFRED publishes: this series, this period, first current at this
instant.  Two different values sharing all four would be the publisher contradicting
itself, and that raises rather than quietly writing a second row.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from uw_scan.macro_evidence import macro_observation_content_hash

from .macro_context import _require_aware
from .macro_policy_observations import _link


@dataclass(frozen=True)
class MacroSeriesUpsertOutcome:
    """What one batch actually changed, counted rather than inferred from row count."""

    created: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.created + self.unchanged


class _MacroSeriesObservationMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_macro_series_observations(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        seen_at: datetime,
    ) -> MacroSeriesUpsertOutcome:
        """Resolve each published vintage, adding this artifact as a witness.

        An unchanged re-read costs one lineage link and nothing else: the observation
        keeps the ``artifact_id`` of the payload that first carried it, so ``content_hash``
        stays stable and no phantom revision appears in the history.
        """
        _require_aware("seen_at", seen_at)
        materialized = list(rows)
        if not materialized:
            return MacroSeriesUpsertOutcome(created=0, unchanged=0)
        for row in materialized:
            _require_aware("published_at", row.get("published_at"), optional=True)
            _require_aware("available_at", row["available_at"])

        created = 0
        unchanged = 0
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                _validate_series_artifact_bounds(cur, self._schema, materialized)
                for row in materialized:
                    if self._resolve_existing(cur, row, seen_at=seen_at):
                        unchanged += 1
                    else:
                        self._insert(cur, row, seen_at=seen_at)
                        created += 1
        return MacroSeriesUpsertOutcome(created=created, unchanged=unchanged)

    def _resolve_existing(
        self, cur: psycopg.Cursor, row: dict[str, Any], *, seen_at: datetime
    ) -> bool:
        cur.execute(
            f"""
            SELECT obs_id, value_numeric, unit
            FROM {self._schema}.macro_observations
            WHERE source = %s AND series_id = %s
              AND period_end = %s AND available_at = %s
            """,
            (row["source"], row["series_id"], row["period_end"], row["available_at"]),
        )
        existing = cur.fetchone()
        if existing is None:
            return False
        obs_id, stored_value, stored_unit = existing
        _assert_same_reading(row, stored_value=stored_value, stored_unit=stored_unit)
        cur.execute(
            f"""
            UPDATE {self._schema}.macro_observations
            SET last_seen_at = GREATEST(last_seen_at, %s)
            WHERE obs_id = %s
            """,
            (seen_at, obs_id),
        )
        # A later payload that carries the same vintage is a witness to it, not the
        # source it was parsed from -- that artifact is already recorded on the row.
        _link(cur, self._schema, int(obs_id), int(row["artifact_id"]), "corroborates")
        return True

    def _insert(
        self, cur: psycopg.Cursor, row: dict[str, Any], *, seen_at: datetime
    ) -> None:
        cur.execute(
            f"""
            INSERT INTO {self._schema}.macro_observations (
              artifact_id, domain, series_id, period_end, frequency, unit,
              value_numeric, source, source_record_id,
              published_at, available_at, first_observed_at, last_seen_at,
              content_hash, parser_version, quality_status, cost_class
            )
            VALUES (
              %s, %s, %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s, %s
            )
            RETURNING obs_id
            """,
            (
                row["artifact_id"],
                row["domain"],
                row["series_id"],
                row["period_end"],
                row["frequency"],
                row["unit"],
                row["value_numeric"],
                row["source"],
                row["source_record_id"],
                row.get("published_at"),
                row["available_at"],
                seen_at,
                seen_at,
                macro_observation_content_hash(row),
                row["parser_version"],
                row["quality_status"],
                row["cost_class"],
            ),
        )
        inserted = cur.fetchone()
        if inserted is None:  # pragma: no cover - RETURNING on a plain INSERT
            raise RuntimeError("macro series observation insert returned no id")
        _link(
            cur, self._schema, int(inserted[0]), int(row["artifact_id"]), "parsed_from"
        )


def _validate_series_artifact_bounds(
    cur: psycopg.Cursor, schema: str, rows: Sequence[dict[str, Any]]
) -> None:
    """The vintage bound, which runs the opposite way from the release bound.

    :func:`uw_scan.storage.macro_context._validate_artifact_bounds` refuses an
    observation older than the artifact carrying it, and for a release that is right:
    the FOMC's decision became knowable when the statement went up, so an earlier
    availability would be a fact predating its own evidence.

    A vintage record inverts it.  ALFRED's entire product is telling us, today, that the
    January 2024 CPI was first published on 2024-02-13.  Refusing that because the bytes
    arrived in 2026 would stamp every historical vintage with the date we happened to
    fetch it -- which is the defect the MC2 golden-history rebuild existed to undo.

    What must still hold is the forward direction: a vintage cannot postdate the fetch
    that reported it.  That is the bound below, and it is the one a lookahead would break.
    """
    artifact_ids = sorted({int(row["artifact_id"]) for row in rows})
    cur.execute(
        f"""
        SELECT artifact_id, source, source_record_id, retrieved_at, quality_status,
               vintage_bearing
        FROM {schema}.macro_source_artifacts
        WHERE artifact_id = ANY(%s)
        FOR KEY SHARE
        """,
        (artifact_ids,),
    )
    artifacts = {int(row[0]): row for row in cur.fetchall()}
    for row in rows:
        artifact = artifacts.get(int(row["artifact_id"]))
        if artifact is None:
            raise ValueError(f"macro artifact {row['artifact_id']} does not exist")
        _, source, source_record_id, retrieved_at, quality_status, vintage_bearing = (
            artifact
        )
        if not vintage_bearing:
            raise ValueError(
                f"macro artifact {row['artifact_id']} is not vintage-bearing; a release "
                "payload cannot be written through the series path, whose whole premise "
                "is that the artifact reports publication dates it did not itself set"
            )
        if (row["source"], row["source_record_id"]) != (source, source_record_id):
            raise ValueError("observation source identity differs from its artifact")
        if row["available_at"] > retrieved_at:
            raise ValueError(
                f"{row['series_id']} vintage for {row['period_end']} claims to have "
                f"become available at {row['available_at'].isoformat()}, after the "
                f"payload reporting it was retrieved at {retrieved_at.isoformat()}"
            )
        if (row["quality_status"] == "valid" and quality_status != "valid") or (
            row["quality_status"] == "partial"
            and quality_status not in {"valid", "partial"}
        ):
            raise ValueError("observation quality exceeds artifact quality")


def _assert_same_reading(
    row: dict[str, Any], *, stored_value: Decimal | None, stored_unit: str
) -> None:
    incoming = row["value_numeric"]
    if stored_unit != row["unit"]:
        raise ValueError(
            f"{row['series_id']} vintage for {row['period_end']} first published at "
            f"{row['available_at'].isoformat()} was stored in {stored_unit!r} and now "
            f"reads {row['unit']!r}; a unit change is a new series, not a re-read"
        )
    if stored_value is None or Decimal(stored_value) != Decimal(incoming):
        raise ValueError(
            f"{row['series_id']} vintage for {row['period_end']} first published at "
            f"{row['available_at'].isoformat()} was stored as {stored_value} and now "
            f"reads {incoming}; one vintage cannot hold two values, so this is a "
            "publisher contradiction or a parser regression"
        )
