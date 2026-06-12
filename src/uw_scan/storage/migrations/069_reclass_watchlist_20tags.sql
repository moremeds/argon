-- 069_reclass_watchlist_20tags.sql
--
-- Reclassifies uw_scan.watchlist into the 20-tag taxonomy:
--   Index:     Beta, Sector-ETF, Credit, Macro
--   AI/Tech:   M7, Foundry, Semi-Logic, Semi-Cap, Memory, DC-Connect,
--              NeoCloud, Power, SaaS
--   Thematic:  Crypto, Fintech, Space
--   Defensive: Healthcare, Energy, Banks, Consumer
--
-- Idempotent — every UPDATE narrows by ticker/sector, every INSERT uses
-- ON CONFLICT DO UPDATE. Safe to re-run.

SET search_path TO uw_scan, public;

-- 1. Soft-delete removed tickers (Defense/Telecom-Media/Airlines tabs +
--    individual removes: ARKK, ES, SMCI, ZS, DDOG, ABBV, MRK).
UPDATE uw_scan.watchlist SET removed_at = NOW()
 WHERE ticker IN ('ES','ARKK','SMCI','ZS','DDOG','ABBV','MRK',
                  'LMT','RTX','BA','CRS','T','VZ','DIS','DAL')
   AND removed_at IS NULL;

-- 2. Split the legacy "ETF" tag into four cohorts by driver:
--    Beta (broad equity), Sector-ETF (sector betas),
--    Credit (HY bonds), Macro (rates + real assets).
UPDATE uw_scan.watchlist SET sector = 'Beta',       sort_rank = 0
 WHERE ticker IN ('SPY','QQQ','IWM','DIA');
UPDATE uw_scan.watchlist SET sector = 'Sector-ETF', sort_rank = 0
 WHERE ticker IN ('SMH','SOXX','XLE','XLF','IGV');
UPDATE uw_scan.watchlist SET sector = 'Macro',      sort_rank = 0
 WHERE ticker IN ('TLT','GLD');

-- 3. Split "Semiconductor" into Foundry / Semi-Logic / Semi-Cap.
UPDATE uw_scan.watchlist SET sector = 'Foundry',    sort_rank = 0
 WHERE ticker IN ('TSM','TSEM','INTC');
UPDATE uw_scan.watchlist SET sector = 'Semi-Logic', sort_rank = 0
 WHERE ticker IN ('AMD','AVGO','QCOM','ARM','TXN');
UPDATE uw_scan.watchlist SET sector = 'Semi-Cap',   sort_rank = 0
 WHERE ticker = 'ASML';

-- 4. Optical → DC-Connect rename, absorb Networking (ANET, NOK) and
--    MRVL (datacenter-interconnect silicon / PAM4 DSPs).
UPDATE uw_scan.watchlist SET sector = 'DC-Connect', sort_rank = 0
 WHERE sector = 'Optical' OR ticker IN ('ANET','NOK','MRVL');

-- 5. Insert / restore 10 adds.
INSERT INTO uw_scan.watchlist (ticker, sector, sort_rank, pinned) VALUES
  ('ISRG', 'Healthcare', 0, FALSE),
  ('HYG',  'Credit',     0, FALSE),
  ('JNK',  'Credit',     0, FALSE),
  ('SLV',  'Macro',      0, FALSE),
  ('AMAT', 'Semi-Cap',   0, FALSE),
  ('LRCX', 'Semi-Cap',   0, FALSE),
  ('KLAC', 'Semi-Cap',   0, FALSE),
  ('SNPS', 'Semi-Cap',   0, FALSE),
  ('CDNS', 'Semi-Cap',   0, FALSE),
  ('TER',  'Semi-Cap',   0, FALSE)
ON CONFLICT (ticker) DO UPDATE
  SET sector     = EXCLUDED.sector,
      sort_rank  = EXCLUDED.sort_rank,
      removed_at = NULL;
