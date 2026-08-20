-- Distinguish an artifact that IS a release from one that REPORTS a publication history.
--
-- Migration 115 enforced one availability rule for every observation: it may not become
-- available before the artifact carrying it.  For a release that is exactly right.  The
-- FOMC's decision became knowable when the statement went up, and an observation dated
-- earlier would be a fact predating its own evidence -- a look-ahead in the dangerous
-- direction.
--
-- A vintage record inverts the relationship.  ALFRED's whole product is telling us, in a
-- payload fetched today, that the January 2024 CPI was first published on 2024-02-13.
-- Under the single rule those bytes can only be recorded as having become available
-- today, which stamps the fetch date on every historical vintage and destroys the one
-- field point-in-time replay is built on.  That is the defect the MC2 golden-history
-- rebuild already had to undo once by hand; encoding it in the schema would have made it
-- permanent and invisible.
--
-- So the property becomes explicit on the artifact rather than inferred from its source:
--
--   vintage_bearing = FALSE (every existing artifact)
--       observation.available_at >= artifact.available_at   -- unchanged
--   vintage_bearing = TRUE
--       observation.available_at <= artifact.retrieved_at
--
-- The second bound is not weaker in the direction that matters.  It still forbids a
-- vintage that postdates the fetch reporting it, which is what a look-ahead would need.
-- What it permits is only the backward direction: learning today when something was
-- published in the past.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.macro_source_artifacts
  ADD COLUMN IF NOT EXISTS vintage_bearing BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN uw_scan.macro_source_artifacts.vintage_bearing IS
  'True when the payload states when each value it carries was first published, rather '
  'than being the publication itself. Such an artifact may carry observations older '
  'than itself; they still may not be newer than its retrieved_at.';

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
  IF artifact.vintage_bearing THEN
    IF NEW.available_at > artifact.retrieved_at THEN
      RAISE EXCEPTION
        'observation available_at % follows the retrieval of the vintage record reporting it (%)',
        NEW.available_at, artifact.retrieved_at
        USING ERRCODE = '23514';
    END IF;
  ELSIF NEW.available_at < artifact.available_at THEN
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
