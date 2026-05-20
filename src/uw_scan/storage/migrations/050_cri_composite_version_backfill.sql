-- 050_cri_composite_version_backfill.sql
-- Label every snapshot written before the v3 calibration with composite_version=1
-- so version-filtered queries and replay UI don't return empty for the >99% of
-- rows pre-dating v3. Idempotent: the WHERE clause skips rows already labelled.
UPDATE uw_scan.cri_snapshots
SET payload = jsonb_set(
    payload,
    '{cri,composite_version}',
    '1'::jsonb,
    true
)
WHERE payload->'cri'->>'composite_version' IS NULL;
