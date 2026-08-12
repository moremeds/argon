-- 114_fundamental_observations.sql — tier-1 immutable fundamental observations
-- plus the two-tier universe they are ingested for. Idempotent.
--
-- Design contract (spec §4.4, decision A10): the payload and its identity
-- columns are IMMUTABLE. A restatement is a NEW row; the old one is never
-- altered or deleted. The single mutable column is `last_seen_at`, which is
-- sighting metadata rather than a fact.
--
-- Identity is CONTENT, not fetch time. Keying on an observed-at timestamp would
-- insert a new row on every unchanged refresh, which contradicts the idempotence
-- the ingest job is required to have. `content_hash` over the normalized payload
-- means an unchanged refresh bumps one timestamp and writes no fact.

SET search_path TO uw_scan, public;


-- ---------------------------------------------------------------------------
-- Universe — two tiers, split by pipeline stage (spec §4.3 rev 5)
-- ---------------------------------------------------------------------------
-- Not one list. `core` sizes the stages a human hand-verifies (valuation
-- anchors, narrative); `ranked` sizes the stages that only cost API calls
-- (statement ingest, subscores) and is the width at which the composite is a
-- legitimate sort key. Rev 4 measured composite IC 0.024 (t 0.68) at 25 names
-- against 0.039 leak-free (t 2.67) at 245 — so the ranking is scoped to the
-- wide tier rather than removed from the product.
--
-- Tier keys carry no count. An earlier draft used `ranked_245`; the 245 came
-- from local lake price depth (needed only to compute forward returns during
-- validation) and statement ingest does not read the lake at all, so that number
-- moves as soon as the mirror deepens. `reason` records per row whether a name
-- is inside the validated panel — that is where the count belongs.
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_universe (
    tier        TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    -- Taxonomy layer (L1..L5). Meaningful for core_25, which was picked to span
    -- the chain; NULL for ranked_245, which was picked for price+statement
    -- history and has no curated layer.
    layer       TEXT,
    -- Why this name is in this tier, in words. A tier whose membership cannot be
    -- explained later is a tier nobody can safely edit.
    reason      TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at  TIMESTAMPTZ,
    PRIMARY KEY (tier, ticker)
);

COMMENT ON TABLE uw_scan.fundamental_universe IS
    'Two-tier fundamental universe: core_25 (hand-verifiable stages) and '
    'ranked_245 (mechanical stages, the width the composite was validated at). '
    'See 114_fundamental_observations.sql and spec §4.3.';

CREATE INDEX IF NOT EXISTS ix_fundamental_universe_active
    ON uw_scan.fundamental_universe (tier) WHERE removed_at IS NULL;


-- ---------------------------------------------------------------------------
-- Tier 1 — immutable source observations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_statement_obs (
    obs_id              BIGSERIAL PRIMARY KEY,
    source              TEXT NOT NULL,       -- 'uw' | 'massive_vx' | 'sec_xbrl'
    ticker              TEXT NOT NULL,
    -- The period the statement DESCRIBES. Never the calendar date the provider
    -- assigned: UW's `fiscal_date_ending` is the filer's own quarter end, and
    -- filers do not share a fiscal calendar.
    period_end          DATE NOT NULL,
    period_type         TEXT NOT NULL,       -- 'quarterly' | 'annual' | 'ttm'
    statement           TEXT NOT NULL,       -- 'income' | 'balance' | 'cash_flow'
    -- Hash over the NORMALIZED payload with an explicit exclusion list. Provider
    -- envelopes carry request ids and generation timestamps that differ on every
    -- call; hashing those would make every refresh look like a restatement.
    content_hash        TEXT NOT NULL,
    -- A stable upstream id beats a hash we computed. Stored when the provider
    -- supplies one, NULL when it does not.
    provider_record_id  TEXT,
    filing_accession    TEXT,
    -- When the WORLD could have known this. Point-in-time queries filter on this
    -- column, not on first_observed_at — that is what stops look-ahead. NULL
    -- means the provider gave us no filing date and the consumer must decide
    -- whether to apply a lag fallback (and record that it did).
    filing_published_at DATE,
    raw_jsonb           JSONB NOT NULL,
    -- Which normalization produced content_hash. A field-map change re-hashes
    -- everything, so the version has to travel with the row or old hashes become
    -- unreproducible.
    field_map_version   TEXT NOT NULL,
    first_observed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, ticker, period_end, period_type, statement, content_hash)
);

COMMENT ON TABLE uw_scan.fundamental_statement_obs IS
    'Immutable point-in-time statement observations. One row per distinct thing '
    'a provider said. Restatement = new row. Only last_seen_at is mutable.';

COMMENT ON COLUMN uw_scan.fundamental_statement_obs.filing_published_at IS
    'When the filing became public. PIT queries filter on this, never on '
    'first_observed_at, which is merely when we fetched.';

-- The read pattern for stage 2 is "every period for this ticker, newest first".
CREATE INDEX IF NOT EXISTS ix_fundamental_statement_obs_ticker_period
    ON uw_scan.fundamental_statement_obs (ticker, statement, period_end DESC);

-- The read pattern for a point-in-time sweep is "everything public by date D".
CREATE INDEX IF NOT EXISTS ix_fundamental_statement_obs_published
    ON uw_scan.fundamental_statement_obs (filing_published_at)
    WHERE filing_published_at IS NOT NULL;


-- ---------------------------------------------------------------------------
-- Data-quality violations against tier-1 rows
-- ---------------------------------------------------------------------------
-- What makes the ingest gate auditable. Keyed on (obs_id, check_name) so
-- re-running INGEST over an unchanged observation is idempotent, and so a
-- restatement that fixes a bad figure gets a NEW obs_id with no violation rather
-- than an edit to the old verdict — the record that the provider once served a
-- negative liability survives the correction.
--
-- Rates measured in the §3.3 source probe: ~5% negative liabilities, ~15%
-- implausible share counts. This table exists because those are expected, not
-- exceptional, and a pipeline that silently drops them reports false coverage.
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_obs_violations (
    violation_id    BIGSERIAL PRIMARY KEY,
    obs_id          BIGINT NOT NULL
                        REFERENCES uw_scan.fundamental_statement_obs (obs_id)
                        ON DELETE CASCADE,
    check_name      TEXT NOT NULL,
    field           TEXT,
    observed_value  NUMERIC,
    detail_jsonb    JSONB,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (obs_id, check_name)
);

COMMENT ON TABLE uw_scan.fundamental_obs_violations IS
    'Deterministic data-quality failures against a tier-1 observation. A '
    'violation never blocks ingest — it records that the provider served a '
    'figure we do not believe, so downstream can exclude it explicitly.';

CREATE INDEX IF NOT EXISTS ix_fundamental_obs_violations_check
    ON uw_scan.fundamental_obs_violations (check_name);
