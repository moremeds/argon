-- 027_matrix_state_vrp_sign_flip.sql — persist VRP sign-flip override inputs.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.matrix_state_snapshots
    ADD COLUMN IF NOT EXISTS vrp_sign_flip_status TEXT,
    ADD COLUMN IF NOT EXISTS vrp_sign_flip_aligned_days INTEGER DEFAULT 0;

UPDATE uw_scan.matrix_state_snapshots
SET
    vrp_sign_flip_status = COALESCE(
        vrp_sign_flip_status,
        'insufficient_history'
    ),
    vrp_sign_flip_aligned_days = COALESCE(vrp_sign_flip_aligned_days, 0);

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.vrp_sign_flip_status
    IS 'VRP sign-flip override status: true, false, or insufficient_history.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.vrp_sign_flip_aligned_days
    IS 'Count of aligned IV/RV days used for the 30-day VRP sign-flip check.';

COMMIT;
