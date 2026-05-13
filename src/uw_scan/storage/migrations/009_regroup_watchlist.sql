-- 009_regroup_watchlist.sql
--
-- Retag `sector` on uw_scan.watchlist with thematic groupings (ETF / M7 /
-- Semiconductor / Memory / Optical / NeoCloud / SaaS / Networking / Crypto /
-- Fintech / Space / Defense / Healthcare / Energy / Banks / Consumer /
-- Telecom-Media / Airlines) and set `sort_rank` so the card grid orders
-- sections in that sequence. Adds four optical names (AAOI, COHR, FN, ALAB)
-- to the watchlist.
--
-- Convention: sort_rank = group_index * 100 + within_group_alpha_rank.

BEGIN;

-- 1. Make sure the four new optical tickers exist in the active watchlist.
INSERT INTO uw_scan.watchlist (ticker, sector, sort_rank, pinned, notes)
VALUES
  ('AAOI', 'Optical',   503, FALSE, 'Applied Optoelectronics — 800G transceivers'),
  ('ALAB', 'Optical',   504, FALSE, 'Astera Labs — PCIe / silicon photonics'),
  ('COHR', 'Optical',   505, FALSE, 'Coherent — lasers, optical comms'),
  ('FN',   'Optical',   506, FALSE, 'Fabrinet — contract optical manufacturing')
ON CONFLICT (ticker) DO UPDATE
  SET sector     = EXCLUDED.sector,
      sort_rank  = EXCLUDED.sort_rank,
      removed_at = NULL;

-- 2. Retag every active ticker. The CASE/WHEN below is the single source of
--    truth for both `sector` and `sort_rank`.
WITH new_groups (ticker, sector, sort_rank) AS (VALUES
  -- ETF · 大盘
  ('SPY',  'ETF',           101),
  ('QQQ',  'ETF',           102),
  ('IWM',  'ETF',           103),
  ('DIA',  'ETF',           104),
  ('SMH',  'ETF',           105),
  ('XLE',  'ETF',           106),
  ('XLF',  'ETF',           107),
  ('TLT',  'ETF',           108),
  ('GLD',  'ETF',           109),
  ('ARKK', 'ETF',           110),
  -- M7
  ('AAPL', 'M7',            201),
  ('MSFT', 'M7',            202),
  ('GOOGL','M7',            203),
  ('AMZN', 'M7',            204),
  ('META', 'M7',            205),
  ('TSLA', 'M7',            206),
  ('NVDA', 'M7',            207),
  -- Semiconductor
  ('AMD',  'Semiconductor', 301),
  ('AVGO', 'Semiconductor', 302),
  ('ASML', 'Semiconductor', 303),
  ('ARM',  'Semiconductor', 304),
  ('MRVL', 'Semiconductor', 305),
  ('QCOM', 'Semiconductor', 306),
  ('INTC', 'Semiconductor', 307),
  ('TXN',  'Semiconductor', 308),
  ('SMCI', 'Semiconductor', 309),
  ('TSM',  'Semiconductor', 310),
  ('TSEM', 'Semiconductor', 311),
  -- Memory
  ('MU',   'Memory',        401),
  ('SNDK', 'Memory',        402),
  -- Optical (existing watchlist members; new entries inserted above)
  ('LITE', 'Optical',       501),
  ('CRDO', 'Optical',       502),
  ('GLW',  'Optical',       507),
  -- NeoCloud
  ('NBIS', 'NeoCloud',      601),
  ('CRWV', 'NeoCloud',      602),
  -- SaaS
  ('PLTR', 'SaaS',          701),
  ('ORCL', 'SaaS',          702),
  ('CRM',  'SaaS',          703),
  ('SNOW', 'SaaS',          704),
  ('DDOG', 'SaaS',          705),
  ('NET',  'SaaS',          706),
  ('CRWD', 'SaaS',          707),
  ('ZS',   'SaaS',          708),
  ('PANW', 'SaaS',          709),
  ('APP',  'SaaS',          710),
  -- Networking
  ('ANET', 'Networking',    801),
  ('NOK',  'Networking',    802),
  -- Crypto
  ('COIN', 'Crypto',        901),
  ('MSTR', 'Crypto',        902),
  ('MARA', 'Crypto',        903),
  ('RIOT', 'Crypto',        904),
  ('IREN', 'Crypto',        905),
  ('CRCL', 'Crypto',        906),
  -- Fintech
  ('SOFI', 'Fintech',      1001),
  ('HOOD', 'Fintech',      1002),
  -- Space
  ('RKLB', 'Space',        1101),
  ('ASTS', 'Space',        1102),
  ('PL',   'Space',        1103),
  ('BKSY', 'Space',        1104),
  ('FLY',  'Space',        1105),
  -- Defense · 防御
  ('LMT',  'Defense',      1201),
  ('RTX',  'Defense',      1202),
  ('BA',   'Defense',      1203),
  ('CRS',  'Defense',      1204),
  -- Healthcare
  ('LLY',  'Healthcare',   1301),
  ('JNJ',  'Healthcare',   1302),
  ('MRK',  'Healthcare',   1303),
  ('PFE',  'Healthcare',   1304),
  ('ABBV', 'Healthcare',   1305),
  ('HIMS', 'Healthcare',   1306),
  -- Energy
  ('XOM',  'Energy',       1401),
  ('CVX',  'Energy',       1402),
  ('OXY',  'Energy',       1403),
  -- Banks
  ('JPM',  'Banks',        1501),
  ('BAC',  'Banks',        1502),
  ('WFC',  'Banks',        1503),
  ('MS',   'Banks',        1504),
  ('GS',   'Banks',        1505),
  ('BLK',  'Banks',        1506),
  -- Consumer
  ('HD',   'Consumer',     1601),
  ('NKE',  'Consumer',     1602),
  ('SBUX', 'Consumer',     1603),
  ('MCD',  'Consumer',     1604),
  ('COST', 'Consumer',     1605),
  ('KO',   'Consumer',     1606),
  ('TGT',  'Consumer',     1607),
  ('WMT',  'Consumer',     1608),
  -- Telecom / Media
  ('T',    'Telecom-Media',1701),
  ('VZ',   'Telecom-Media',1702),
  ('DIS',  'Telecom-Media',1703),
  -- Airlines
  ('DAL',  'Airlines',     1801)
)
UPDATE uw_scan.watchlist w
   SET sector    = g.sector,
       sort_rank = g.sort_rank
  FROM new_groups g
 WHERE w.ticker = g.ticker;

COMMIT;
