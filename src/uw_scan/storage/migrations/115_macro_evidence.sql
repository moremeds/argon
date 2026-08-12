-- 115_macro_evidence.sql — immutable point-in-time evidence for macro domains.
--
-- Additive only: legacy rates/gold read models remain untouched during dual-read.
-- Source artifacts preserve exact publisher payloads; normalized observations preserve
-- releases/revisions and are selected with available_at <= decision as_of.

SET search_path TO uw_scan, public;

CREATE OR REPLACE FUNCTION uw_scan.macro_source_kind_allowed(
  candidate TEXT,
  database_name TEXT
)
RETURNS BOOLEAN
LANGUAGE SQL
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT candidate NOT IN ('mock', 'static', 'demo')
    OR database_name LIKE 'option_wizard_test%'
$$;

CREATE OR REPLACE FUNCTION uw_scan.macro_canonical_numeric(candidate NUMERIC)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
STRICT
AS $$
BEGIN
  IF candidate::TEXT IN ('NaN', 'Infinity', '-Infinity') THEN
    RAISE EXCEPTION 'macro numeric values must be finite'
      USING ERRCODE = '22003';
  END IF;
  RETURN CASE
    WHEN candidate = 0 THEN '0'
    WHEN position('.' IN candidate::TEXT) = 0 THEN candidate::TEXT
    ELSE rtrim(rtrim(candidate::TEXT, '0'), '.')
  END;
END
$$;

CREATE OR REPLACE FUNCTION uw_scan.macro_canonical_jsonb(candidate JSONB)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
STRICT
AS $$
DECLARE
  rendered TEXT;
BEGIN
  CASE jsonb_typeof(candidate)
    WHEN 'object' THEN
      SELECT '{' || COALESCE(
        string_agg(to_jsonb(item.key)::TEXT || ':' ||
          uw_scan.macro_canonical_jsonb(item.value),
          ',' ORDER BY item.key COLLATE "C"),
        ''
      ) || '}'
      INTO rendered
      FROM jsonb_each(candidate) AS item;
    WHEN 'array' THEN
      SELECT '[' || COALESCE(
        string_agg(uw_scan.macro_canonical_jsonb(item.value), ',' ORDER BY item.ordinality),
        ''
      ) || ']'
      INTO rendered
      FROM jsonb_array_elements(candidate) WITH ORDINALITY AS item(value, ordinality);
    WHEN 'number' THEN
      rendered := uw_scan.macro_canonical_numeric((candidate #>> '{}')::NUMERIC);
    ELSE
      rendered := candidate::TEXT;
  END CASE;
  RETURN rendered;
END
$$;

CREATE TABLE IF NOT EXISTS uw_scan.macro_source_artifacts (
  artifact_id       BIGSERIAL   PRIMARY KEY,
  source            TEXT        NOT NULL CHECK (btrim(source) <> ''),
  source_kind       TEXT        NOT NULL
    CHECK (
      source_kind IN (
        'official',
        'first_party_publisher',
        'entitled_provider',
        'third_party_shadow',
        'mock',
        'static',
        'demo'
      )
    ),
  source_record_id  TEXT        NOT NULL CHECK (btrim(source_record_id) <> ''),
  source_url        TEXT        NULL,
  published_at      TIMESTAMPTZ NULL,
  available_at      TIMESTAMPTZ NOT NULL,
  retrieved_at      TIMESTAMPTZ NOT NULL,
  last_seen_at      TIMESTAMPTZ NOT NULL,
  content_hash      TEXT        NOT NULL
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  parser_version    TEXT        NOT NULL CHECK (btrim(parser_version) <> ''),
  quality_status    TEXT        NOT NULL
    CHECK (quality_status IN ('valid', 'invalid', 'partial', 'quarantined')),
  cost_class        TEXT        NOT NULL
    CHECK (
      cost_class IN (
        'free_official',
        'free_publisher',
        'already_entitled',
        'free_third_party_shadow',
        'paid_authorized'
      )
    ),
  media_type        TEXT        NOT NULL CHECK (btrim(media_type) <> ''),
  content_length    BIGINT      NOT NULL CHECK (content_length >= 0),
  raw_jsonb         JSONB       NULL,
  raw_text          TEXT        NULL,
  raw_bytes         BYTEA       NULL,
  CHECK (num_nonnulls(raw_jsonb, raw_text, raw_bytes) = 1),
  CHECK (published_at IS NULL OR published_at <= available_at),
  CHECK (retrieved_at <= last_seen_at),
  CHECK (uw_scan.macro_source_kind_allowed(source_kind, current_database())),
  UNIQUE (source, source_record_id, content_hash),
  UNIQUE (artifact_id, source, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_macro_source_artifacts_lookup
  ON uw_scan.macro_source_artifacts (
    source,
    source_record_id,
    retrieved_at DESC
  );

CREATE INDEX IF NOT EXISTS idx_macro_source_artifacts_available
  ON uw_scan.macro_source_artifacts (available_at DESC, source);

COMMENT ON COLUMN uw_scan.macro_source_artifacts.published_at IS
  'Publisher-declared release instant; NULL when the publisher supplies no reliable instant.';
COMMENT ON COLUMN uw_scan.macro_source_artifacts.available_at IS
  'Earliest instant the artifact is allowed to enter an Argon point-in-time decision.';
COMMENT ON COLUMN uw_scan.macro_source_artifacts.retrieved_at IS
  'First wall-clock instant Argon retrieved this exact payload representation.';
COMMENT ON COLUMN uw_scan.macro_source_artifacts.last_seen_at IS
  'Latest wall-clock instant Argon retrieved this identical payload representation.';

CREATE TABLE IF NOT EXISTS uw_scan.macro_observations (
  obs_id             BIGSERIAL   PRIMARY KEY,
  artifact_id        BIGINT      NOT NULL,
  domain             TEXT        NOT NULL
    CHECK (domain IN ('inflation', 'policy_rates', 'usd', 'gold', 'cross_domain')),
  series_id          TEXT        NOT NULL CHECK (btrim(series_id) <> ''),
  period_end         DATE        NOT NULL,
  frequency          TEXT        NOT NULL
    CHECK (frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'annual', 'event', 'irregular')),
  unit               TEXT        NOT NULL CHECK (btrim(unit) <> ''),
  value_numeric      NUMERIC     NULL,
  value_text         TEXT        NULL,
  value_jsonb        JSONB       NULL,
  source             TEXT        NOT NULL CHECK (btrim(source) <> ''),
  source_record_id   TEXT        NOT NULL CHECK (btrim(source_record_id) <> ''),
  published_at       TIMESTAMPTZ NULL,
  available_at       TIMESTAMPTZ NOT NULL,
  first_observed_at  TIMESTAMPTZ NOT NULL,
  last_seen_at       TIMESTAMPTZ NOT NULL,
  content_hash       TEXT        NOT NULL
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  parser_version     TEXT        NOT NULL CHECK (btrim(parser_version) <> ''),
  quality_status     TEXT        NOT NULL
    CHECK (quality_status IN ('valid', 'invalid', 'partial', 'quarantined')),
  cost_class         TEXT        NOT NULL
    CHECK (
      cost_class IN (
        'free_official',
        'free_publisher',
        'already_entitled',
        'free_third_party_shadow',
        'paid_authorized'
      )
    ),
  CHECK (num_nonnulls(value_numeric, value_text, value_jsonb) = 1),
  CHECK (
    value_numeric IS NULL
    OR value_numeric::TEXT NOT IN ('NaN', 'Infinity', '-Infinity')
  ),
  CHECK (published_at IS NULL OR published_at <= available_at),
  CHECK (first_observed_at <= last_seen_at),
  FOREIGN KEY (artifact_id, source, source_record_id)
    REFERENCES uw_scan.macro_source_artifacts (
      artifact_id,
      source,
      source_record_id
    )
    ON DELETE RESTRICT,
  UNIQUE (source, series_id, period_end, available_at, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_macro_observations_pit
  ON uw_scan.macro_observations (
    series_id,
    period_end,
    available_at DESC,
    source
  );

CREATE INDEX IF NOT EXISTS idx_macro_observations_series_pit
  ON uw_scan.macro_observations (
    series_id,
    available_at DESC,
    period_end DESC
  )
  WHERE quality_status IN ('valid', 'partial');

CREATE INDEX IF NOT EXISTS idx_macro_observations_artifact
  ON uw_scan.macro_observations (artifact_id);

COMMENT ON COLUMN uw_scan.macro_observations.period_end IS
  'Economic period represented by the observation; never the market knowledge time.';
COMMENT ON COLUMN uw_scan.macro_observations.published_at IS
  'Publisher-declared release instant; NULL when no reliable instant is supplied.';
COMMENT ON COLUMN uw_scan.macro_observations.available_at IS
  'Earliest instant this observation may enter a point-in-time decision.';
COMMENT ON COLUMN uw_scan.macro_observations.first_observed_at IS
  'First wall-clock instant Argon normalized this immutable observation.';
COMMENT ON COLUMN uw_scan.macro_observations.last_seen_at IS
  'Latest wall-clock instant Argon saw the identical immutable observation.';

CREATE OR REPLACE FUNCTION uw_scan.macro_artifact_write_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  payload BYTEA;
  actual_hash TEXT;
  actual_length BIGINT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'macro source artifacts are immutable'
      USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (to_jsonb(NEW) - ARRAY['retrieved_at', 'last_seen_at'])
        IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['retrieved_at', 'last_seen_at'])
       OR NEW.retrieved_at > OLD.retrieved_at
       OR NEW.last_seen_at < OLD.last_seen_at THEN
      RAISE EXCEPTION 'macro source artifacts are immutable'
        USING ERRCODE = '23514';
    END IF;
  END IF;

  payload := CASE
    WHEN NEW.raw_jsonb IS NOT NULL THEN
      convert_to(uw_scan.macro_canonical_jsonb(NEW.raw_jsonb), 'UTF8')
    WHEN NEW.raw_text IS NOT NULL THEN convert_to(NEW.raw_text, 'UTF8')
    ELSE NEW.raw_bytes
  END;
  actual_hash := encode(sha256(payload), 'hex');
  actual_length := octet_length(payload);
  IF NEW.content_hash <> actual_hash THEN
    RAISE EXCEPTION 'artifact content_hash does not match raw payload'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.content_length <> actual_length THEN
    RAISE EXCEPTION 'artifact content_length does not match raw payload'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_macro_artifact_write_guard
  ON uw_scan.macro_source_artifacts;
CREATE TRIGGER trg_macro_artifact_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON uw_scan.macro_source_artifacts
FOR EACH ROW EXECUTE FUNCTION uw_scan.macro_artifact_write_guard();

CREATE OR REPLACE FUNCTION uw_scan.macro_observation_write_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  artifact uw_scan.macro_source_artifacts%ROWTYPE;
  typed_value JSONB;
  canonical_record JSONB;
  actual_hash TEXT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'macro observations are immutable'
      USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (to_jsonb(NEW) - 'last_seen_at')
        IS DISTINCT FROM
       (to_jsonb(OLD) - 'last_seen_at')
       OR NEW.last_seen_at < OLD.last_seen_at THEN
      RAISE EXCEPTION 'macro observations are immutable'
        USING ERRCODE = '23514';
    END IF;
  END IF;

  SELECT * INTO artifact
  FROM uw_scan.macro_source_artifacts
  WHERE artifact_id = NEW.artifact_id
  FOR KEY SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'macro artifact % does not exist', NEW.artifact_id
      USING ERRCODE = '23503';
  END IF;
  IF (NEW.source, NEW.source_record_id)
      IS DISTINCT FROM (artifact.source, artifact.source_record_id) THEN
    RAISE EXCEPTION 'observation source identity differs from its artifact'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.available_at < artifact.available_at THEN
    RAISE EXCEPTION 'observation available_at precedes artifact available_at'
      USING ERRCODE = '23514';
  END IF;
  IF (NEW.quality_status = 'valid' AND artifact.quality_status <> 'valid')
      OR (
        NEW.quality_status = 'partial'
        AND artifact.quality_status NOT IN ('valid', 'partial')
      ) THEN
    RAISE EXCEPTION 'observation quality exceeds artifact quality'
      USING ERRCODE = '23514';
  END IF;

  typed_value := CASE
    WHEN NEW.value_numeric IS NOT NULL THEN
      jsonb_build_object(
        'type', 'numeric',
        'value', uw_scan.macro_canonical_numeric(NEW.value_numeric)
      )
    WHEN NEW.value_text IS NOT NULL THEN
      jsonb_build_object('type', 'text', 'value', NEW.value_text)
    ELSE jsonb_build_object('type', 'json', 'value', NEW.value_jsonb)
  END;
  canonical_record := jsonb_build_object(
    'artifact_id', NEW.artifact_id,
    'available_at', to_char(
      NEW.available_at AT TIME ZONE 'UTC',
      'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    ),
    'domain', NEW.domain,
    'frequency', NEW.frequency,
    'parser_version', NEW.parser_version,
    'period_end', to_char(NEW.period_end, 'YYYY-MM-DD'),
    'published_at', CASE
      WHEN NEW.published_at IS NULL THEN NULL
      ELSE to_jsonb(to_char(
        NEW.published_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
      ))
    END,
    'series_id', NEW.series_id,
    'source', NEW.source,
    'source_record_id', NEW.source_record_id,
    'unit', NEW.unit,
    'value', typed_value
  );
  actual_hash := encode(
    sha256(convert_to(uw_scan.macro_canonical_jsonb(canonical_record), 'UTF8')),
    'hex'
  );
  IF NEW.content_hash <> actual_hash THEN
    RAISE EXCEPTION 'observation content_hash does not match normalized record'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_macro_observation_write_guard
  ON uw_scan.macro_observations;
CREATE TRIGGER trg_macro_observation_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON uw_scan.macro_observations
FOR EACH ROW EXECUTE FUNCTION uw_scan.macro_observation_write_guard();
