-- 010_orcl_oklo.sql
--
-- Move ORCL from SaaS to NeoCloud (it's increasingly an AI-infrastructure
-- story, not just enterprise SaaS), and add OKLO as a new "Nuclear/Power"
-- group sitting between NeoCloud and SaaS in the section order.
--
-- Section ordering (compatible with migration 009):
--   ETF=1, M7=2, Semi=3, Memory=4, Optical=5,
--   NeoCloud=6, Nuclear/Power=65, SaaS=7, ...
-- Using a fractional-style integer key (sort_rank in the 650 band) lets us
-- slot Nuclear/Power between NeoCloud (600s) and SaaS (700s) without
-- renumbering everything.

BEGIN;

-- 1. Add OKLO to the watchlist as Nuclear/Power.
INSERT INTO uw_scan.watchlist (ticker, sector, sort_rank, pinned, notes)
VALUES ('OKLO', 'Nuclear/Power', 651, FALSE, 'Small modular reactors — AI data center power')
ON CONFLICT (ticker) DO UPDATE
  SET sector     = EXCLUDED.sector,
      sort_rank  = EXCLUDED.sort_rank,
      removed_at = NULL;

-- 2. Move ORCL into NeoCloud at rank 603 (after NBIS=601, CRWV=602).
UPDATE uw_scan.watchlist
   SET sector    = 'NeoCloud',
       sort_rank = 603
 WHERE ticker = 'ORCL';

COMMIT;
