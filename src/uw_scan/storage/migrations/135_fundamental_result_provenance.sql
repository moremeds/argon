-- 135_fundamental_result_provenance.sql — typed, enforceable provenance for
-- derived fundamental results. Additive: `fundamental_scores.source_obs_ids`
-- stays exactly as it is and every existing row keeps working.
--
-- WHAT AN ARRAY OF IDS CANNOT SAY
-- -------------------------------
-- `source_obs_ids bigint[]` records which observations a score was computed
-- from. It cannot record:
--   * that an observation was CONSIDERED and EXCLUDED (M1.1 now withholds
--     violated values from the math — the array shows the same list either way);
--   * that a second content version for the same identity EXISTED and lost;
--   * which stage of the derivation consumed it;
--   * and it is unenforceable. Nothing stops an id in that array from naming an
--     observation that was deleted, or one that never existed.
--
-- The last point is why this is a table with foreign keys rather than a richer
-- JSON blob. A result that cites evidence which is not there is not a degraded
-- result; it is an unfalsifiable one.
--
-- WHY RESTRICT AND NOT CASCADE
-- ----------------------------
-- `fundamental_obs_availability` cascades on purpose: an availability CLAIM about
-- a deleted observation is meaningless, so it should go with it. Provenance is
-- the opposite. If a published score cites an observation, deleting that
-- observation must FAIL — otherwise the deletion silently converts a reproducible
-- result into one nobody can explain, with no error at the moment the damage is
-- done. RESTRICT makes the database refuse.
--
-- LEGACY ROWS STAY VISIBLY LEGACY
-- -------------------------------
-- v1 score rows get no provenance rows and are not backfilled into any. A reader
-- distinguishes "no typed provenance recorded (legacy)" from "typed provenance
-- recorded, and it lists nothing" by the presence of rows here, which is a real
-- distinction: the second would be a bug and the first is just history.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.fundamental_result_provenance (
    provenance_id   bigserial PRIMARY KEY,
    result_id       bigint NOT NULL
                    REFERENCES uw_scan.fundamental_scores(result_id)
                    ON DELETE CASCADE,
    obs_id          bigint NOT NULL
                    REFERENCES uw_scan.fundamental_statement_obs(obs_id)
                    ON DELETE RESTRICT,
    role            text NOT NULL,
    stage           text NOT NULL,
    detail_jsonb    jsonb NOT NULL DEFAULT '{}'::jsonb,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fundamental_result_provenance_role_check
        CHECK (role IN ('used', 'excluded', 'superseded')),
    CONSTRAINT fundamental_result_provenance_uq
        UNIQUE (result_id, obs_id, role, stage)
);

COMMENT ON TABLE uw_scan.fundamental_result_provenance IS
    'Typed provenance for fundamental_scores: which observations a result USED, '
    'which it considered and EXCLUDED, and which lost canonical selection '
    '(SUPERSEDED). Replaces what fundamental_scores.source_obs_ids could only '
    'gesture at; the array stays for compatibility and v1 rows are not '
    'backfilled, so absence of rows here reads as "legacy", not "cited nothing".';

COMMENT ON COLUMN uw_scan.fundamental_result_provenance.role IS
    'used = its values entered the math. excluded = considered and withheld '
    '(M1.1 validity, or a policy refusal). superseded = another content version '
    'for the same identity won canonical selection.';

COMMENT ON COLUMN uw_scan.fundamental_result_provenance.stage IS
    'Which derivation step consumed it — panel | features | scoring. A single '
    'observation can appear at more than one stage with different roles, which '
    'is exactly the case an array cannot express.';

COMMENT ON CONSTRAINT fundamental_result_provenance_obs_id_fkey
    ON uw_scan.fundamental_result_provenance IS
    'RESTRICT, not CASCADE. Deleting an observation a published result cites '
    'must fail: it would convert a reproducible result into an unexplainable one '
    'with no error at the moment the damage is done.';

CREATE INDEX IF NOT EXISTS ix_fundamental_result_provenance_result
    ON uw_scan.fundamental_result_provenance (result_id, role);

CREATE INDEX IF NOT EXISTS ix_fundamental_result_provenance_obs
    ON uw_scan.fundamental_result_provenance (obs_id);
