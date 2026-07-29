-- 110_research_universe.sql — named, tagged ticker cohorts for research backfills.
-- Idempotent.
--
-- Deliberately NOT the watchlist. Adding a name to `watchlist` enlists it in every
-- per-ticker scheduled job and permanently raises the daily UW burn. A research
-- cohort only needs to exist so a backfill can iterate it and so analysis SQL can
-- GROUP BY its tags, neither of which requires live scanning.
--
-- `sector` is the tag the analysis groups on. It is stored rather than derived
-- because the source (UW screener) is a point-in-time query — re-running it later
-- reclassifies names and silently changes historical groupings.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.research_universe (
    cohort        TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    sector        TEXT NOT NULL,
    marketcap     NUMERIC,
    -- Total option open interest at selection. Stored alongside marketcap because
    -- for an options study the two are NOT interchangeable: large caps routinely
    -- have untradeable chains (EQIX 18k OI vs a 657k watchlist median), and the
    -- most active chains skew retail. A cohort is only defensible if both are
    -- recorded and can be re-checked.
    option_oi     BIGINT,
    source        TEXT NOT NULL,
    -- The date the cohort was selected. Market caps and sector labels are as of
    -- this date; both drift, so a number quoted from this table must be read
    -- against it rather than against today.
    selected_on   DATE NOT NULL,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cohort, ticker)
);

COMMENT ON TABLE uw_scan.research_universe IS
    'Named ticker cohorts for research backfills. Not a trade surface and not '
    'scanned live — see 110_research_universe.sql for why this is separate from '
    'uw_scan.watchlist.';

CREATE INDEX IF NOT EXISTS ix_research_universe_cohort_sector
    ON uw_scan.research_universe (cohort, sector);
