-- Per-role sub-states carried beside a domain state.
--
-- A separate column rather than a row inside factors_jsonb: a factor is one series'
-- reading, a sub-state is a role's own answer with its own confidence, and folding the
-- second into the first would give a reader no way to tell which confidence number
-- governs which claim. That confusion is the exact thing MC3's R2 ruling forbids -- the
-- policy state's confidence must never render as though it covered a positioning read.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS with a default, so re-running is a no-op and
-- states written before this migration read as carrying no sub-states, which is true.
ALTER TABLE uw_scan.macro_domain_states
  ADD COLUMN IF NOT EXISTS sub_states_jsonb JSONB NOT NULL DEFAULT '[]'::JSONB;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'macro_domain_states_sub_states_is_array'
  ) THEN
    ALTER TABLE uw_scan.macro_domain_states
      ADD CONSTRAINT macro_domain_states_sub_states_is_array
      CHECK (jsonb_typeof(sub_states_jsonb) = 'array');
  END IF;
END
$$;
