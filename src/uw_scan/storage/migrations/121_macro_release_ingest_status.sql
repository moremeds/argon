-- 121_macro_release_ingest_status.sql — per-release operational catalog,
-- observation/artifact lineage, and a policy semantic identity.
--
-- Three separate concerns land here, all of them about telling apart facts that
-- migration 115 could only conflate:
--
-- 1. macro_release_ingest_status answers "what happened to THIS release the last
--    time we tried?".  It is mutable operational state, deliberately not
--    evidence: a release that failed tonight must not erase the fact that it
--    succeeded last night, so last_success_at/last_success_artifact_id survive a
--    later failure.  Source-level macro_source_status (116) cannot express this
--    -- one bad release degraded the whole source and hid the other 24.
--
-- 2. macro_observation_artifacts records which artifacts an observation was read
--    from.  The publisher serves the same release as both HTML and PDF, and
--    reissues bytes with cosmetic markup drift, so one fact legitimately has
--    several exact byte-level witnesses.
--
-- 3. macro_observations.semantic_hash identifies a policy fact by what the
--    publisher said, not by which bytes carried it.  The general MC0 content
--    hash includes artifact_id and available_at, so re-fetching an unchanged
--    release through a new artifact row produces a "new" observation that is not
--    a new fact.  The semantic hash drops both and keys on the stable release
--    key, the publisher's own release instant, the normalized value, and the
--    SEMANTIC parser version -- so a corrected reparse is a genuinely new
--    identity while a cosmetic refetch is not.
--
-- Migration 115's general hash helper is left untouched: every non-policy macro
-- series keeps its MC0 identity exactly as it was.

SET search_path TO uw_scan, public;

-- ---------------------------------------------------------------------------
-- 1. Per-release operational catalog
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS uw_scan.macro_release_ingest_status (
  source                    TEXT        NOT NULL CHECK (btrim(source) <> ''),
  release_key               TEXT        NOT NULL CHECK (btrim(release_key) <> ''),
  release_type              TEXT        NOT NULL
    CHECK (release_type IN ('statement', 'sep')),
  status                    TEXT        NOT NULL
    CHECK (status IN ('discovered', 'artifact_only', 'ok', 'failed')),
  event_date                DATE        NOT NULL,
  event_class               TEXT        NULL,
  discovery_url             TEXT        NOT NULL CHECK (btrim(discovery_url) <> ''),
  artifact_source_record_id TEXT        NULL,
  latest_artifact_id        BIGINT      NULL,
  last_success_artifact_id  BIGINT      NULL,
  parser_version            TEXT        NOT NULL CHECK (btrim(parser_version) <> ''),
  last_attempt_at           TIMESTAMPTZ NOT NULL,
  last_success_at           TIMESTAMPTZ NULL,
  error_type                TEXT        NULL CHECK (length(error_type) <= 200),
  error_message             TEXT        NULL CHECK (length(error_message) <= 1000),
  PRIMARY KEY (source, release_key),

  -- A statement is a meeting event and always carries its class; a SEP is a
  -- projection publication and has none.  Neither may borrow the other's shape.
  CHECK (
    (
      release_type = 'statement'
      AND event_class IS NOT NULL
      AND event_class IN (
        'scheduled_meeting',
        'unscheduled_meeting',
        'notation_vote'
      )
    )
    OR (release_type = 'sep' AND event_class IS NULL)
  ),

  -- 'ok' must be backed by a real success, and must not also carry an error.
  -- 'failed' must say why.  'artifact_only' means the bytes landed but the
  -- semantic parse did not.
  CHECK (
    (
      status = 'ok'
      AND last_success_at IS NOT NULL
      AND last_success_artifact_id IS NOT NULL
      AND error_type IS NULL
      AND error_message IS NULL
    )
    OR (status = 'failed' AND error_type IS NOT NULL)
    OR (status = 'artifact_only' AND latest_artifact_id IS NOT NULL)
    OR status = 'discovered'
  ),
  CHECK (last_success_at IS NULL OR last_success_at <= last_attempt_at),
  CHECK (
    (latest_artifact_id IS NULL AND last_success_artifact_id IS NULL)
    OR artifact_source_record_id IS NOT NULL
  ),

  -- Composite keys against the artifact uniqueness contract, so a release can
  -- never point at another source's artifact by surrogate id alone.
  FOREIGN KEY (latest_artifact_id, source, artifact_source_record_id)
    REFERENCES uw_scan.macro_source_artifacts (
      artifact_id,
      source,
      source_record_id
    )
    ON DELETE RESTRICT,
  FOREIGN KEY (last_success_artifact_id, source, artifact_source_record_id)
    REFERENCES uw_scan.macro_source_artifacts (
      artifact_id,
      source,
      source_record_id
    )
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_macro_release_ingest_status_event
  ON uw_scan.macro_release_ingest_status (source, release_type, event_date DESC);

CREATE INDEX IF NOT EXISTS idx_macro_release_ingest_status_unhealthy
  ON uw_scan.macro_release_ingest_status (source, event_date DESC)
  WHERE status <> 'ok';

COMMENT ON TABLE uw_scan.macro_release_ingest_status IS
  'Mutable operational_state/liveness: the latest ingest outcome per release. '
  'Never a substitute for immutable release evidence -- it describes our '
  'attempts, not what the publisher said.';
COMMENT ON COLUMN uw_scan.macro_release_ingest_status.last_success_at IS
  'Retained across a later failure so a transient outage cannot erase the '
  'evidence that this release was once ingested cleanly.';
COMMENT ON COLUMN uw_scan.macro_release_ingest_status.event_class IS
  'Statement meeting class; NULL for SEP, which is a publication not a meeting.';

-- ---------------------------------------------------------------------------
-- 2. Observation -> artifact lineage
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS uw_scan.macro_observation_artifacts (
  obs_id      BIGINT NOT NULL
    REFERENCES uw_scan.macro_observations (obs_id) ON DELETE RESTRICT,
  artifact_id BIGINT NOT NULL
    REFERENCES uw_scan.macro_source_artifacts (artifact_id) ON DELETE RESTRICT,
  relation    TEXT   NOT NULL
    CHECK (relation IN ('parsed_from', 'corroborates')),
  PRIMARY KEY (obs_id, artifact_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_macro_observation_artifacts_artifact
  ON uw_scan.macro_observation_artifacts (artifact_id);

COMMENT ON TABLE uw_scan.macro_observation_artifacts IS
  'Which exact artifacts witness an observation. One fact may have several '
  'byte-level witnesses (HTML and PDF of one release, or a cosmetic reissue).';

CREATE OR REPLACE FUNCTION uw_scan.macro_observation_artifact_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'macro observation lineage is immutable'
    USING ERRCODE = '23514';
END
$$;

DROP TRIGGER IF EXISTS trg_macro_observation_artifact_guard
  ON uw_scan.macro_observation_artifacts;
CREATE TRIGGER trg_macro_observation_artifact_guard
BEFORE UPDATE OR DELETE ON uw_scan.macro_observation_artifacts
FOR EACH ROW EXECUTE FUNCTION uw_scan.macro_observation_artifact_guard();

-- ---------------------------------------------------------------------------
-- 3. Policy semantic identity
-- ---------------------------------------------------------------------------

-- The release key is a publisher-level fact ("which release is this?"), which
-- source_record_id cannot carry: migration 115 ties that column to the artifact
-- by composite foreign key, so one release served as HTML and PDF has two
-- different source_record_ids. Keying the semantic identity on it would make
-- the two files of one statement two different facts.
ALTER TABLE uw_scan.macro_observations
  ADD COLUMN IF NOT EXISTS release_key TEXT NULL;

ALTER TABLE uw_scan.macro_observations
  ADD COLUMN IF NOT EXISTS semantic_hash TEXT NULL;

DO $$
BEGIN
  ALTER TABLE uw_scan.macro_observations
    ADD CONSTRAINT macro_observations_semantic_hash_format
    CHECK (semantic_hash IS NULL OR semantic_hash ~ '^[0-9a-f]{64}$');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  ALTER TABLE uw_scan.macro_observations
    ADD CONSTRAINT macro_observations_semantic_needs_release_key
    CHECK (semantic_hash IS NULL OR btrim(release_key) <> '');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

COMMENT ON COLUMN uw_scan.macro_observations.release_key IS
  'Stable publisher release identity, shared by every artifact of one release.';

COMMENT ON COLUMN uw_scan.macro_observations.semantic_hash IS
  'Identity of the published fact, independent of which artifact carried it. '
  'NULL for series that keep the MC0 content-hash identity.';

-- One policy fact per (release, semantics). A cosmetic refetch reuses the row;
-- a corrected reparse changes the value or the semantic parser version and so
-- earns a new identity.
CREATE UNIQUE INDEX IF NOT EXISTS uq_macro_observations_semantic
  ON uw_scan.macro_observations (semantic_hash)
  WHERE semantic_hash IS NOT NULL;

CREATE OR REPLACE FUNCTION uw_scan.macro_policy_semantic_hash(
  p_domain TEXT,
  p_frequency TEXT,
  p_parser_version TEXT,
  p_period_end DATE,
  p_published_at TIMESTAMPTZ,
  p_release_key TEXT,
  p_series_id TEXT,
  p_source TEXT,
  p_unit TEXT,
  p_value_numeric NUMERIC,
  p_value_text TEXT,
  p_value_jsonb JSONB
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT encode(
    sha256(
      convert_to(
        uw_scan.macro_canonical_jsonb(
          jsonb_build_object(
            'domain', p_domain,
            'frequency', p_frequency,
            'parser_version', p_parser_version,
            'period_end', to_char(p_period_end, 'YYYY-MM-DD'),
            'published_at', CASE
              WHEN p_published_at IS NULL THEN NULL
              ELSE to_jsonb(to_char(
                p_published_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
              ))
            END,
            'release_key', p_release_key,
            'series_id', p_series_id,
            'source', p_source,
            'unit', p_unit,
            'value', CASE
              WHEN p_value_numeric IS NOT NULL THEN
                jsonb_build_object(
                  'type', 'numeric',
                  'value', uw_scan.macro_canonical_numeric(p_value_numeric)
                )
              WHEN p_value_text IS NOT NULL THEN
                jsonb_build_object('type', 'text', 'value', p_value_text)
              ELSE jsonb_build_object('type', 'json', 'value', p_value_jsonb)
            END
          )
        ),
        'UTF8'
      )
    ),
    'hex'
  )
$$;

COMMENT ON FUNCTION uw_scan.macro_policy_semantic_hash IS
  'Canonical policy-fact identity. Deliberately omits artifact_id and '
  'available_at so the same published fact re-read from different bytes is one '
  'observation, and includes the semantic parser version so a corrected '
  'reparse is a new one.';

-- Recompute the hash in the database as well, so direct SQL cannot assert a
-- false semantic identity -- the same defence migration 115 applies to
-- content_hash.
CREATE OR REPLACE FUNCTION uw_scan.macro_observation_semantic_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  actual_hash TEXT;
BEGIN
  IF NEW.semantic_hash IS NULL THEN
    RETURN NEW;
  END IF;
  actual_hash := uw_scan.macro_policy_semantic_hash(
    NEW.domain,
    NEW.frequency,
    NEW.parser_version,
    NEW.period_end,
    NEW.published_at,
    NEW.release_key,
    NEW.series_id,
    NEW.source,
    NEW.unit,
    NEW.value_numeric,
    NEW.value_text,
    NEW.value_jsonb
  );
  IF NEW.semantic_hash <> actual_hash THEN
    RAISE EXCEPTION 'observation semantic_hash does not match normalized record'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_macro_observation_semantic_guard
  ON uw_scan.macro_observations;
CREATE TRIGGER trg_macro_observation_semantic_guard
BEFORE INSERT OR UPDATE ON uw_scan.macro_observations
FOR EACH ROW EXECUTE FUNCTION uw_scan.macro_observation_semantic_guard();
