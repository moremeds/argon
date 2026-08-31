-- 131_macro_evidence_invalidations.sql -- saying "we accepted this and were wrong".
--
-- macro_observations rows are immutable: migration 115's macro_observation_write_guard
-- rejects every DELETE and every UPDATE that changes any column but last_seen_at. That is
-- correct and stays. Its consequence is that quality_status can never be moved to
-- 'quarantined' after the fact, so the ledger can say "we never accepted this" and cannot
-- say "we accepted this and were wrong." This table is that second sentence, added as an
-- overlay rather than as a mutation.
--
-- THE OVERLAY HAS ITS OWN POINT-IN-TIME CLOCK. `invalidated_at` is when WE DISCOVERED the
-- problem -- not when the publisher made the error. The read predicate is
-- `invalidated_at <= as_of`, the same shape as the `available_at <= as_of` that already
-- governs every macro read, and it is what makes historical replay preserve belief: a 2021
-- replay does not yet know about a 2026 discovery, so it returns the row Argon actually
-- stood on, while a read today excludes it. One predicate produces both behaviours, so no
-- caller has to choose between a "current" and a "replay" code path.
--
-- Append-only by POLICY, with no immutability trigger of its own: a mistaken invalidation is
-- corrected by a later row that supersedes it, which keeps the audit trail intact. If
-- supersession is ever needed, add `supersedes_id BIGINT NULL` -- never UPDATE.
--
-- Additive only. Nothing in 115, 125, 128 or 130 is altered.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_evidence_invalidations (
  invalidation_id  BIGSERIAL   PRIMARY KEY,
  target_kind      TEXT        NOT NULL
    CHECK (target_kind IN ('artifact', 'observation', 'series_range')),
  artifact_id      BIGINT      NULL REFERENCES uw_scan.macro_source_artifacts (artifact_id),
  obs_id           BIGINT      NULL REFERENCES uw_scan.macro_observations (obs_id),
  series_id        TEXT        NULL,
  -- NULL-open on each side, so a series_range can say "every vintage of this series before
  -- 2025-11-13" without inventing a lower bound nobody knows.
  --
  -- NAMED period_from/period_to, NOT period_start/period_end: macro_observations.period_end
  -- already exists and the join predicate references BOTH tables, so reusing that name
  -- produces a filter that silently compares a row to itself and matches everything.
  period_from      DATE        NULL,
  period_to        DATE        NULL,
  vintage_from     TIMESTAMPTZ NULL,
  vintage_to       TIMESTAMPTZ NULL,
  invalidated_at   TIMESTAMPTZ NOT NULL,
  reason           TEXT        NOT NULL CHECK (btrim(reason) <> ''),
  evidence_url     TEXT        NULL,
  -- A human owns every invalidation. This is the column that stops the overlay from
  -- becoming a place where a job quietly deletes data it did not like.
  reviewer         TEXT        NOT NULL CHECK (btrim(reviewer) <> ''),
  overlay_version  TEXT        NOT NULL CHECK (btrim(overlay_version) <> ''),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Exactly one target shape, fully specified. A row that names two targets would be two
  -- invalidations wearing one id, and the reader would have to guess which one was meant.
  CHECK (
    (target_kind = 'artifact'     AND artifact_id IS NOT NULL AND obs_id IS NULL AND series_id IS NULL)
 OR (target_kind = 'observation'  AND obs_id IS NOT NULL AND artifact_id IS NULL AND series_id IS NULL)
 OR (target_kind = 'series_range' AND series_id IS NOT NULL AND obs_id IS NULL AND artifact_id IS NULL)
  ),
  CHECK (period_from IS NULL OR period_to IS NULL OR period_from <= period_to),
  CHECK (vintage_from IS NULL OR vintage_to IS NULL OR vintage_from <= vintage_to)
);

-- The read predicate filters on invalidated_at first and then matches a target, so the
-- clock leads the index.
CREATE INDEX IF NOT EXISTS idx_macro_evidence_invalidations_clock
  ON uw_scan.macro_evidence_invalidations (invalidated_at);

CREATE INDEX IF NOT EXISTS idx_macro_evidence_invalidations_series
  ON uw_scan.macro_evidence_invalidations (series_id, invalidated_at)
  WHERE series_id IS NOT NULL;
