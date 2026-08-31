-- 139_research_taxonomy.sql — a VERSIONED research taxonomy, separate from the
-- shipped watchlist chain filter, which is not touched.
--
-- WHAT `watchlist_chain` CANNOT DO
-- -------------------------------
-- It is `(ticker, layer, chain)` with a `source` column. It carries no version,
-- so a re-classification is invisible; no validity interval, so a membership
-- that ended looks like one that never existed; and no evidence class, so an
-- analyst's judgement and a disclosed fact are the same row. It is a good
-- filter rail and it is not a research object.
--
-- This is additive. `watchlist_chain` keeps working, keeps its filter, and is
-- MIRRORED into the first taxonomy version rather than migrated away from — a
-- dual read, so the shipped surface cannot regress while this one is built.
--
-- MEMBERSHIP IS NOT EXPOSURE, AND THE SEPARATION IS MEASURED
-- ----------------------------------------------------------
-- Being in a chain is a SEMANTIC claim ("this company belongs to the AI
-- infrastructure story"). Exposure is an ECONOMIC one ("38% of its revenue is
-- sold into it"). Argon measured the difference and it is not cosmetic: the
-- capex-demand ledger's cross-name relationship collapsed from +0.247 to +0.015
-- (p=0.44) once same-SECTOR pairs were compared, which is the finding that a
-- chain, as membership, is a sector by another name. Exposure lives in
-- migration 140 and may carry a number only when something disclosed one.
--
-- WHY validity INTERVALS AND NOT A `removed_at`
-- ---------------------------------------------
-- A company enters and leaves a chain, and the question "was this name in the
-- AI-infrastructure chain when that report was written" has to stay answerable.
-- A single `removed_at` answers "is it now"; intervals answer "was it then",
-- which is the question a versioned report asks.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.research_taxonomy_versions (
    taxonomy_version text PRIMARY KEY,
    note             text,
    is_active        boolean NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.research_taxonomy_versions IS
    'One row per published taxonomy. A re-classification publishes a NEW version '
    'rather than editing rows, so a report can name the taxonomy it was written '
    'against and still resolve it later.';

-- Exactly one active version. Two would make every unqualified read
-- non-deterministic.
CREATE UNIQUE INDEX IF NOT EXISTS research_taxonomy_active_uq
    ON uw_scan.research_taxonomy_versions ((true))
    WHERE is_active;

CREATE TABLE IF NOT EXISTS uw_scan.research_chains (
    taxonomy_version text NOT NULL
                     REFERENCES uw_scan.research_taxonomy_versions(taxonomy_version)
                     ON DELETE CASCADE,
    domain           text NOT NULL,
    chain            text NOT NULL,
    layer            text NOT NULL,
    layer_rank       integer NOT NULL DEFAULT 0,
    description      text,
    PRIMARY KEY (taxonomy_version, chain, layer)
);

COMMENT ON TABLE uw_scan.research_chains IS
    'The layer catalogue for each chain in a taxonomy version. `layer_rank` '
    'orders layers upstream -> downstream for display ONLY: it is a reading '
    'order, never a causal claim, and nothing propagates along it.';

COMMENT ON COLUMN uw_scan.research_chains.layer_rank IS
    'Display order, upstream to downstream. NOT a causal edge — a node-link '
    'propagation view stays unbuilt until a measured named-edge yield justifies '
    'it, and the measured yield so far does not.';

CREATE TABLE IF NOT EXISTS uw_scan.chain_membership (
    membership_id    bigserial PRIMARY KEY,
    taxonomy_version text NOT NULL,
    chain            text NOT NULL,
    layer            text NOT NULL,
    ticker           text NOT NULL,
    evidence_class   text NOT NULL,
    approved_by      text NOT NULL,
    note             text,
    valid_from       timestamptz NOT NULL DEFAULT now(),
    valid_to         timestamptz,
    CONSTRAINT chain_membership_evidence_check
        CHECK (evidence_class IN ('disclosed', 'analyst', 'mirrored', 'inferred')),
    CONSTRAINT chain_membership_interval_check
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT chain_membership_chain_fk
        FOREIGN KEY (taxonomy_version, chain, layer)
        REFERENCES uw_scan.research_chains(taxonomy_version, chain, layer)
        ON DELETE CASCADE
);

COMMENT ON TABLE uw_scan.chain_membership IS
    'Which companies are in a chain layer, under one taxonomy version, over a '
    'validity interval. SEMANTIC membership only — see migration 140 for '
    'economic exposure, which is a different claim with a different burden.';

COMMENT ON COLUMN uw_scan.chain_membership.evidence_class IS
    'disclosed = the company said so. analyst = a human asserted it. mirrored = '
    'copied from the legacy watchlist_chain rail. inferred = derived. An analyst '
    'assertion is a legitimate research object; it is not a measurement, and the '
    'column is what keeps the two distinguishable after the fact.';

CREATE UNIQUE INDEX IF NOT EXISTS chain_membership_open_uq
    ON uw_scan.chain_membership (taxonomy_version, chain, layer, ticker)
    WHERE valid_to IS NULL;

CREATE INDEX IF NOT EXISTS ix_chain_membership_ticker
    ON uw_scan.chain_membership (ticker, taxonomy_version);

CREATE INDEX IF NOT EXISTS ix_chain_membership_chain
    ON uw_scan.chain_membership (taxonomy_version, chain, layer);
