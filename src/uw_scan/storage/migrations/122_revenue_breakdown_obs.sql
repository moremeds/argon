-- 122_revenue_breakdown_obs.sql — immutable point-in-time revenue-breakdown
-- observations (UW `rev_breakdown`). Idempotent.
--
-- WHY RAW ROWS AND NOT THE DERIVED SHARE
-- --------------------------------------
-- The concentration share is the output of rules that are new and unproven:
-- which axis wins when a filer publishes several, how a multi-level axis is
-- collapsed to its reported level, and what separates an annual total mixed
-- into a quarterly series. Those rules will change. The rows will not.
-- Re-deriving from stored rows costs nothing; re-fetching a quarter that has
-- rolled out of the provider's window is impossible. So this table stores what
-- the provider said — axis, members, value, report_date, rev_group — and the
-- derivation lives in `uw_scan.fundamentals.concentration`.
--
-- WHY IDENTITY IS CONTENT, NOT FETCH TIME
-- ---------------------------------------
-- The same contract as migration 114, for the same reason. Keying on an
-- observed-at timestamp would insert a full duplicate set on every capture,
-- so a monthly job would grow the table without end while asserting nothing
-- new. `content_hash` over the normalized payload means an unchanged row bumps
-- `last_seen_at` and writes no fact, while a genuine restatement hashes
-- differently and lands BESIDE its predecessor rather than overwriting it.
--
-- The hash covers only what the provider asserted. Any envelope field that
-- changes per call — request ids, generation timestamps, `inserted_at` /
-- `updated_at` — is excluded by the normalizer. Including such a field is not
-- a theoretical risk: it shipped in the tier-1 ingest and made every refresh
-- read as a phantom restatement.
--
-- WHY A ROLLING WINDOW IS DETECTABLE FROM THIS SHAPE
-- -------------------------------------------------
-- It is not yet known whether the provider's breakdown history rolls or has a
-- fixed start. `last_seen_at` answers it without a second table: a period the
-- provider stops returning simply stops having its `last_seen_at` advanced,
-- while `first_observed_at` preserves when we first saw it.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.revenue_breakdown_obs (
    obs_id            BIGSERIAL PRIMARY KEY,
    source            TEXT NOT NULL,       -- 'uw'
    ticker            TEXT NOT NULL,
    -- The period the breakdown DESCRIBES, as the provider labelled it. Not a
    -- fetch date, and not normalized to a calendar quarter: filers do not share
    -- a fiscal calendar.
    report_date       DATE NOT NULL,
    -- The provider's own grouping tag ('continent', 'segment', ...). Kept as a
    -- stored fact, deliberately NOT used to group the breakdown: it is not the
    -- XBRL axis, and grouping by it is one of the three bugs that produced the
    -- retracted 0/257 computability verdict.
    rev_group         TEXT NOT NULL,
    -- The XBRL concept the value is tagged with, e.g. 'us-gaap:Revenues'.
    field             TEXT,
    -- Raw, positional, as fetched: axis[i] pairs with members[i]. A row may
    -- carry a scope qualifier (srt:ConsolidationItemsAxis) alongside the real
    -- axis; stripping it is a derivation decision and does not happen here.
    axis              TEXT[] NOT NULL,
    members           TEXT[] NOT NULL,
    -- Signed. Elimination and inter-segment rows are genuinely negative, and
    -- clamping them here would silently break every total that reconciles.
    value             NUMERIC NOT NULL,
    content_hash      TEXT NOT NULL,
    -- Which normalization produced content_hash. A normalizer change re-hashes
    -- everything, so the version travels with the row or old hashes become
    -- unreproducible.
    payload_version   TEXT NOT NULL,
    raw_jsonb         JSONB NOT NULL,
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, ticker, report_date, rev_group, content_hash)
);

COMMENT ON TABLE uw_scan.revenue_breakdown_obs IS
    'Immutable point-in-time revenue-breakdown observations. One row per '
    'distinct thing a provider said. Restatement = new row. Only last_seen_at '
    'is mutable. Derived shares are computed at read time, never stored here.';

COMMENT ON COLUMN uw_scan.revenue_breakdown_obs.rev_group IS
    'Provider grouping tag, stored but not used to partition revenue — the '
    'XBRL axis is. Grouping by rev_group under-reports computability.';

COMMENT ON COLUMN uw_scan.revenue_breakdown_obs.last_seen_at IS
    'Last capture that still returned this exact row. A period whose '
    'last_seen_at stops advancing has rolled out of the provider window.';

-- The read pattern is "every period for this ticker, newest first".
CREATE INDEX IF NOT EXISTS ix_revenue_breakdown_obs_ticker_period
    ON uw_scan.revenue_breakdown_obs (ticker, report_date DESC);
