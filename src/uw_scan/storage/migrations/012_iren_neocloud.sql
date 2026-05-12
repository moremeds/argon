-- 012_iren_neocloud.sql
--
-- Move IREN (Iris Energy) from Crypto to NeoCloud. IREN is a former bitcoin
-- miner that has pivoted its compute footprint toward GPU/AI hosting, so it
-- belongs with the other AI-infra names (NBIS, CRWV, ORCL).

BEGIN;

UPDATE uw_scan.watchlist
   SET sector    = 'NeoCloud',
       sort_rank = 604
 WHERE ticker = 'IREN';

COMMIT;
