-- 131_fundamental_scores_evidence_policy.sql — record WHICH statement versions a
-- score was computed from, and under what admission rule. Additive, idempotent,
-- and it rewrites no existing row.
--
-- WHY EXISTING ROWS ARE CORRECTLY LABELLED current_vintage
-- --------------------------------------------------------
-- Every score written before this migration came from the current statement
-- panel — newest version per identity, selected by `obs_id DESC`. That is an
-- honest description of what those rows are, so the DEFAULT is not a
-- placeholder: it is the true provenance of the existing panel, and it is what
-- keeps an old row visibly old rather than silently reinterpreted as a
-- point-in-time replay it never was.
--
-- WHY THE UNIQUE KEY DOES NOT NEED TO CHANGE
-- ------------------------------------------
-- `UNIQUE (ticker, as_of, engine_version, inputs_hash)` still holds, because the
-- evidence policy enters `inputs_hash` for historical runs (see
-- `fundamentals.scoring.inputs_hash`). A true-PIT replay and a capture-bounded
-- replay of the same quarter therefore land as two rows rather than colliding,
-- and neither can overwrite the current-vintage row already there.
--
-- WHY THERE IS NO RUN LEDGER HERE
-- -------------------------------
-- Excluded counts, timings and the run's own identity belong to a run ledger,
-- which is M2's deliverable. Pre-Job 0 stores what is needed to reconstruct ONE
-- row's provenance — the policy, the cutoff, and the exact claims selection
-- rested on — and reports run-level counts to its caller. Building half a ledger
-- here would have to be unbuilt there.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.fundamental_scores
    ADD COLUMN IF NOT EXISTS evidence_policy TEXT NOT NULL DEFAULT 'current_vintage';

ALTER TABLE uw_scan.fundamental_scores
    ADD COLUMN IF NOT EXISTS as_of_cutoff TIMESTAMPTZ;

ALTER TABLE uw_scan.fundamental_scores
    ADD COLUMN IF NOT EXISTS availability_ids BIGINT[] NOT NULL DEFAULT '{}';

-- `current_vintage` is not one of the historical policies in
-- `fundamentals.observation_time.EvidencePolicy` — deliberately. It names the
-- absence of a historical claim, and admitting it as a policy value there would
-- give a replay a way to ask for the very rows that fail closed.
ALTER TABLE uw_scan.fundamental_scores
    DROP CONSTRAINT IF EXISTS fundamental_scores_evidence_policy_check;
ALTER TABLE uw_scan.fundamental_scores
    ADD CONSTRAINT fundamental_scores_evidence_policy_check
    CHECK (evidence_policy IN ('current_vintage', 'true_pit_only', 'capture_bounded'));

-- A historical replay must name its cutoff; the current panel has none to name.
ALTER TABLE uw_scan.fundamental_scores
    DROP CONSTRAINT IF EXISTS fundamental_scores_cutoff_check;
ALTER TABLE uw_scan.fundamental_scores
    ADD CONSTRAINT fundamental_scores_cutoff_check
    CHECK (
        (evidence_policy = 'current_vintage' AND as_of_cutoff IS NULL)
        OR (evidence_policy <> 'current_vintage' AND as_of_cutoff IS NOT NULL)
    );

COMMENT ON COLUMN uw_scan.fundamental_scores.evidence_policy IS
    'Which admission rule selected the statement versions behind this row. '
    'current_vintage = newest-version panel (today''s page), NOT a replay.';

COMMENT ON COLUMN uw_scan.fundamental_scores.as_of_cutoff IS
    'The instant the replay claimed to stand at. NULL for current_vintage rows, '
    'which stand at no particular time.';

COMMENT ON COLUMN uw_scan.fundamental_scores.availability_ids IS
    'The availability claims selection rested on, alongside source_obs_ids. '
    'Together they reconstruct WHICH version was used and WHY it was admissible.';

-- A replay is read back by (policy, cutoff); the existing indexes are keyed on
-- ticker/as_of and answer a different question.
CREATE INDEX IF NOT EXISTS ix_fundamental_scores_policy_cutoff
    ON uw_scan.fundamental_scores (evidence_policy, as_of_cutoff DESC);
