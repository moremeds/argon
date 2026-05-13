-- 008_extend_watchlist.sql — round out the seed with another ~30 commonly-traded names.
-- Slotted into the existing sort_rank bands (M7 1-7, Semis 10-29, Growth 30-39,
-- Value/Industrials 40-59, Crypto 60-69, ETF 70-89). Idempotent.

SET search_path TO uw_scan, public;

INSERT INTO uw_scan.watchlist (ticker, sector, notes, sort_rank) VALUES
  -- Mega-cap tech, software platforms
  ('ORCL',  'Technology',              'Mega-cap — enterprise / cloud',           8),
  ('CRM',   'Technology',              'Mega-cap — SaaS / CRM',                   9),
  -- Semiconductors (extend the 10-29 band)
  ('ARM',   'Technology',              'Semiconductor — IP licensing',           26),
  ('ASML',  'Technology',              'Semiconductor — lithography',            27),
  ('TXN',   'Technology',              'Semiconductor — analog',                 28),
  ('SMCI',  'Technology',              'Semiconductor — AI servers',             29),
  ('ANET',  'Technology',              'Semiconductor — data-center networking', 19), -- sandwich into infra
  -- Growth tech additions
  ('SNOW',  'Technology',              'Growth / tech — data cloud',             39),
  ('CRWD',  'Technology',              'Growth / tech — cybersecurity',          37), -- alongside PANW
  ('DDOG',  'Technology',              'Growth / tech — observability',          38),
  ('ZS',    'Technology',              'Growth / tech — cybersecurity',          39),
  -- Financials (banks + asset managers)
  ('BAC',   'Financials',              'Industrials / value — bank',             56),
  ('WFC',   'Financials',              'Industrials / value — bank',             57),
  ('BLK',   'Financials',              'Industrials / value — asset manager',    58),
  -- Consumer
  ('NKE',   'Consumer Discretionary',  'Industrials / value — apparel',          59),
  ('DIS',   'Communication Services',  'Industrials / value — media',            60),
  ('HD',    'Consumer Discretionary',  'Industrials / value — retail',           61),
  ('SBUX',  'Consumer Discretionary',  'Industrials / value — retail',           62),
  ('TGT',   'Consumer Staples',        'Industrials / value — retail',           63),
  -- Healthcare / pharma
  ('PFE',   'Healthcare',              'Industrials / value — pharma',           64),
  ('JNJ',   'Healthcare',              'Industrials / value — pharma',           65),
  ('MRK',   'Healthcare',              'Industrials / value — pharma',           66),
  ('ABBV',  'Healthcare',              'Industrials / value — pharma',           67),
  -- Communications / telco
  ('T',     'Communication Services',  'Industrials / value — telco',            68),
  ('VZ',    'Communication Services',  'Industrials / value — telco',            69),
  -- Aerospace / defense
  ('LMT',   'Industrials',             'Industrials / value — defense',          50),
  ('RTX',   'Industrials',             'Industrials / value — defense',          51),
  -- Crypto miners
  ('MARA',  'Financials',              'Crypto proxy — BTC mining',              63),
  ('RIOT',  'Financials',              'Crypto proxy — BTC mining',              64),
  -- ETFs (sector + macro)
  ('DIA',   'ETF',                     'Dow Jones ETF',                          73),
  ('SMH',   'ETF',                     'Semiconductor ETF',                      74),
  ('XLE',   'ETF',                     'Energy sector ETF',                      75),
  ('XLF',   'ETF',                     'Financial sector ETF',                   76),
  ('TLT',   'ETF',                     '20Y+ Treasury ETF',                      77),
  ('GLD',   'ETF',                     'Gold ETF',                               78),
  ('ARKK',  'ETF',                     'ARK Innovation ETF',                     79)
ON CONFLICT (ticker) DO NOTHING;
