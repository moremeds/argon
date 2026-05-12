-- 011_add_be_power.sql
--
-- Add BE (Bloom Energy — fuel cells, AI data-center power) to the same group
-- as OKLO, and rename the group from "Nuclear/Power" to plain "Power" so it
-- reads cleanly with both nuclear and fuel-cell names.

BEGIN;

-- 1. Rename existing OKLO entry.
UPDATE uw_scan.watchlist
   SET sector = 'Power'
 WHERE sector = 'Nuclear/Power';

-- 2. Insert BE alongside OKLO (sort_rank 652 = right after OKLO=651).
INSERT INTO uw_scan.watchlist (ticker, sector, sort_rank, pinned, notes)
VALUES ('BE', 'Power', 652, FALSE, 'Bloom Energy — fuel cells for AI data center power')
ON CONFLICT (ticker) DO UPDATE
  SET sector     = EXCLUDED.sector,
      sort_rank  = EXCLUDED.sort_rank,
      removed_at = NULL;

COMMIT;
