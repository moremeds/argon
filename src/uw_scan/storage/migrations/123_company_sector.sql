-- 123_company_sector.sql — vendor sector per ticker, cached for company_type
-- routing. Idempotent.
--
-- WHY A CACHE AND NOT A LOOKUP AT ROUTING TIME
-- -------------------------------------------
-- `fundamental_refresh` (18:20 ET) chains routing -> subscores -> anchor bands
-- and its documented property is that the whole chain costs ZERO provider spend.
-- Routing needs a sector for the ~261 universe names that carry none locally, and
-- the only source for those is UW `/stock/{ticker}/info` — one call per ticker.
-- Fetching inside the nightly job would trade that property away for a value that
-- changes at most once a quarter. So the fetch is its own job writing here, and
-- the seeder reads this table.
--
-- WHY IT IS SEPARATE FROM `watchlist.sector`
-- ------------------------------------------
-- Different vocabularies, not different storage of one thing. `watchlist.sector`
-- is argon's hand-curated chain taxonomy (`Foundry`, `Semi-Logic`, `DC-Connect`);
-- this is the vendor's GICS-style sector (`Financial Services`, `Utilities`).
-- They collide on `Energy`, which means power generation in the first and oil and
-- gas in the second, so they route through separate maps and must not be merged
-- into one column. The chain sector stays authoritative where it exists.
--
-- WHY `sector` IS NULLABLE
-- ------------------------
-- A recorded NULL is the answer "the vendor has no sector for this ticker", which
-- is different from "not asked yet" (no row). Without that distinction the fetch
-- job re-asks every run for every name the vendor cannot classify.

CREATE TABLE IF NOT EXISTS uw_scan.company_sector (
    ticker      text        PRIMARY KEY,
    sector      text,
    source      text        NOT NULL DEFAULT 'uw',
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.company_sector IS
  'Vendor (GICS-style) sector per ticker, cached for company_type routing. '
  'Distinct vocabulary from watchlist.sector — see 123_company_sector.sql.';
