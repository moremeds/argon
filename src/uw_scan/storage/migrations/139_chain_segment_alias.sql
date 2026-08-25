-- 139_chain_segment_alias.sql — the recorded rule that maps a DISCLOSED segment
-- to a chain, so a derived magnitude is auditable in both halves.
--
-- THE PROBLEM THIS SOLVES
-- -----------------------
-- A company discloses `avgo:SemiconductorSolutionsMember = 15,009m` against a
-- 22,187m consolidated total. The 67.6% is a fact. Attributing it to the
-- "AI-Infrastructure" chain is a judgement. An exposure row built from the two
-- is therefore neither fully disclosed nor purely asserted, and collapsing it to
-- either is wrong in a different direction each time:
--
--   * calling it `disclosed` hides that a human chose the chain;
--   * calling it `asserted` forfeits the number entirely (migration 138's CHECK
--     forbids a magnitude on an asserted row), which would leave the exposure
--     table with no measured content at all.
--
-- The resolution is to make the JUDGEMENT a recorded artifact too. A derived
-- exposure names the observation that produced its number AND the alias rule
-- that produced its attribution, and a reader can audit both. That is how a
-- research system publishes a mapping rather than hiding one.
--
-- WHY A PATTERN AND NOT A FULL MEMBER STRING
-- ------------------------------------------
-- XBRL member tags carry a company prefix (`avgo:`, `nvda:`) so the same concept
-- is spelled differently by every filer. Matching on a case-insensitive
-- substring of the local name is what lets one rule cover a chain across filers.
-- It is deliberately blunt: a rule that matched too much would be visible in the
-- coverage counts, and a rule that matches nothing costs nothing.
--
-- M5.5 EXTENSIBILITY, CONCRETELY
-- ------------------------------
-- Adding the optical-communication chain is adding rows here plus rows in
-- `research_chains`/`chain_membership`. No new table, no new job, no scoring
-- fork. If that turns out to be false, this migration is where the special case
-- would have to appear, and its absence is the proof.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.chain_segment_alias (
    alias_id         bigserial PRIMARY KEY,
    taxonomy_version text NOT NULL,
    chain            text NOT NULL,
    -- Case-insensitive substring matched against the XBRL member local name.
    alias_pattern    text NOT NULL,
    axis             text NOT NULL DEFAULT 'us-gaap:StatementBusinessSegmentsAxis',
    role             text NOT NULL DEFAULT 'beneficiary',
    approved_by      text NOT NULL,
    note             text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chain_segment_alias_uq
        UNIQUE (taxonomy_version, chain, alias_pattern, axis)
);

COMMENT ON TABLE uw_scan.chain_segment_alias IS
    'Published rules mapping a disclosed XBRL segment member to a chain. A '
    'derived exposure cites BOTH the observation that produced its number and '
    'the alias that produced its attribution, so the judgement is auditable '
    'rather than baked into a magnitude.';

COMMENT ON COLUMN uw_scan.chain_segment_alias.alias_pattern IS
    'Case-insensitive substring of the member LOCAL name (after the colon). '
    'Blunt on purpose: filers spell the same concept differently, an over-broad '
    'rule shows up in the coverage counts, and a rule matching nothing is free.';

COMMENT ON COLUMN uw_scan.chain_segment_alias.approved_by IS
    'Who published this mapping. An unattributed rule is an anonymous judgement '
    'wearing the authority of a derived number.';

CREATE INDEX IF NOT EXISTS ix_chain_segment_alias_chain
    ON uw_scan.chain_segment_alias (taxonomy_version, chain);
