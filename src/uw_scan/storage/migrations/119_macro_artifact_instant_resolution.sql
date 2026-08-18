-- 119_macro_artifact_instant_resolution.sql — let a known-unknown publication
-- instant be resolved exactly once.
--
-- Migration 115 treats every artifact column except retrieved_at/last_seen_at as
-- immutable, which is right for a publisher fact.  But `published_at` is NULL in
-- two very different situations: the publisher states no release time at all, and
-- the publisher states one this parser could not yet read.  In the second case the
-- artifact is persisted (exact bytes are evidence and must survive a parse failure)
-- with `available_at` falling back to our retrieval clock.  Under 115 that row was
-- permanent: a later parser that CAN read the instant produced a differing
-- immutable column, so the upsert matched nothing, `insert_macro_artifact` raised
-- `artifact identity collision`, and the failure degraded the whole source rather
-- than the one release.
--
-- This migration allows a single NULL -> value transition on `published_at`, and
-- only when `available_at` is moved to that same resolved instant.  It stays a
-- one-way door: a non-NULL instant can never be changed or cleared, so a real
-- correction still creates a new artifact rather than mutating evidence.  Moving
-- availability off our retrieval clock and onto the publisher's own instant makes
-- point-in-time replay more correct, not less -- the release really was public
-- then, and `fetch_macro_observation_as_of` gates on artifact availability.

SET search_path TO uw_scan, public;

CREATE OR REPLACE FUNCTION uw_scan.macro_artifact_write_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  payload BYTEA;
  actual_hash TEXT;
  actual_length BIGINT;
  resolving BOOLEAN;
  mutable TEXT[];
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'macro source artifacts are immutable'
      USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    resolving := OLD.published_at IS NULL AND NEW.published_at IS NOT NULL;
    mutable := CASE
      WHEN resolving
        THEN ARRAY['retrieved_at', 'last_seen_at', 'published_at', 'available_at']
      ELSE ARRAY['retrieved_at', 'last_seen_at']
    END;
    IF (to_jsonb(NEW) - mutable) IS DISTINCT FROM (to_jsonb(OLD) - mutable)
       OR NEW.retrieved_at > OLD.retrieved_at
       OR NEW.last_seen_at < OLD.last_seen_at THEN
      RAISE EXCEPTION 'macro source artifacts are immutable'
        USING ERRCODE = '23514';
    END IF;
    IF resolving AND NEW.available_at IS DISTINCT FROM NEW.published_at THEN
      RAISE EXCEPTION
        'a resolved publication instant must become the availability instant'
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

COMMENT ON FUNCTION uw_scan.macro_artifact_write_guard() IS
  'Artifact rows are immutable except retrieved_at/last_seen_at bounds and a '
  'single NULL -> value resolution of published_at, which must carry '
  'available_at to the same instant.';
