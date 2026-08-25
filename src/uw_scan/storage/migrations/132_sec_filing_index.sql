-- 132_sec_filing_index.sql — SEC EDGAR's filing index, mirrored locally.
--
-- WHY MIRROR IT AT ALL
-- --------------------
-- The publication-evidence job asks, for every statement identity Argon holds,
-- "which periodic filing published this period, and was it ever amended". That
-- is one question per identity and ~90k identities. Answering it from the
-- network each time would be ~90k HTTP calls against a 10 req/s limit, and would
-- make a deterministic backfill depend on SEC being up.
--
-- More importantly the answer must be REPRODUCIBLE. A claim written today says
-- "SEC accession X, filed Y". If a later reviewer cannot see the index row that
-- licensed it, the claim is unfalsifiable. Mirroring makes the evidence local
-- and joinable.
--
-- IMMUTABLE AND CONTENT-KEYED
-- ---------------------------
-- An accession number is SEC's own immutable identifier for a submission. A
-- filing's form, report date, and filing date never change once accepted — a
-- correction is a NEW accession ending in "/A", which is why the amendment is a
-- separate row rather than an edit. So the natural key is the accession, and the
-- refresh is `ON CONFLICT DO NOTHING`: re-running it can never legitimately
-- change a row, and a re-run that silently rewrote history would destroy the
-- reproducibility this table exists to provide.
--
-- `ticker` is denormalized alongside `cik` deliberately. The join in the
-- evidence job is by ticker (that is what `fundamental_statement_obs` carries),
-- and a ticker change would otherwise silently retarget every historical filing
-- to whoever holds the symbol today. Storing the ticker AS FETCHED keeps the
-- index honest about which symbol the mapping was made under; `sec_cik_map` then
-- records the current mapping separately and mutably.
--
-- NOT A PROVIDER-BUDGET DATASET
-- -----------------------------
-- SEC is free and keyless. This table must never appear in the UW budget
-- governor, and its refresh job carries no provider cost accounting.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.sec_cik_map (
    ticker      text PRIMARY KEY,
    cik         text NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.sec_cik_map IS
    'ticker -> 10-digit zero-padded CIK, from SEC company_tickers.json. Mutable: '
    'a ticker can be reassigned to a different issuer, and the CURRENT mapping is '
    'what a fresh fetch needs. Historical filings keep their own ticker column in '
    'sec_filing_index so a reassignment cannot retarget them.';

COMMENT ON COLUMN uw_scan.sec_cik_map.cik IS
    'Zero-padded to 10 digits. data.sec.gov 404s on an unpadded CIK.';

CREATE TABLE IF NOT EXISTS uw_scan.sec_filing_index (
    accession       text PRIMARY KEY,
    cik             text NOT NULL,
    ticker          text NOT NULL,
    form            text NOT NULL,
    report_date     date NOT NULL,
    filing_date     date NOT NULL,
    is_amendment    boolean NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.sec_filing_index IS
    'Periodic filings (10-Q/10-K/20-F/40-F and their /A amendments) from SEC EDGAR '
    'submissions. Immutable and content-keyed on SEC accession: a correction is a '
    'NEW accession, never an edit, so refresh is ON CONFLICT DO NOTHING and a '
    're-run cannot rewrite the evidence that licensed an existing true_pit claim.';

COMMENT ON COLUMN uw_scan.sec_filing_index.report_date IS
    'SEC reportDate — the fiscal period covered. NOT reliably equal to Argon''s '
    'period_end: 52/53-week calendars disagree by a few days (NVDA 2026-04-26 vs '
    '2026-04-30), which is why the match carries a +/-7-day tolerance.';

COMMENT ON COLUMN uw_scan.sec_filing_index.is_amendment IS
    'True for a form ending in /A. An amendment does not date content — it proves '
    'the period''s content cannot be dated, because the single version Argon holds '
    'may be the restatement rather than the original.';

COMMENT ON COLUMN uw_scan.sec_filing_index.ticker IS
    'The symbol this filing was fetched under. Denormalized on purpose so a later '
    'ticker reassignment cannot silently retarget historical filings.';

CREATE INDEX IF NOT EXISTS ix_sec_filing_index_ticker_period
    ON uw_scan.sec_filing_index (ticker, report_date DESC);

CREATE INDEX IF NOT EXISTS ix_sec_filing_index_amendment
    ON uw_scan.sec_filing_index (ticker, report_date)
    WHERE is_amendment;
