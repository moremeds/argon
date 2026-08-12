-- 117_fundamental_scores.sql — method versioning + stage-2 score outputs.
-- Idempotent.
--
-- Two ideas, and the separation is the point:
--   `engine_version` identifies the METHOD; `inputs_hash` identifies the INPUTS.
-- Result identity needs both. A company_type flip or a restatement arriving on the
-- same as_of changes the inputs while leaving engine_version untouched, so a key
-- without inputs_hash collides and the second result is silently lost.

SET search_path TO uw_scan, public;


-- ---------------------------------------------------------------------------
-- Method versioning — immutable versions plus a singleton pointer
-- ---------------------------------------------------------------------------
-- A BOOLEAN `active` column with a partial unique index guarantees AT MOST one
-- active version, not exactly one: a failed activation or a stray manual UPDATE
-- leaves zero, and every computation silently has no method. Three mechanisms
-- are used instead because "exactly one" needs both bounds enforced —
-- a NOT NULL FK removes the null case, a CHECK pins the row's identity, and a
-- BEFORE DELETE trigger removes the empty case.
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_method_versions (
    engine_version  TEXT PRIMARY KEY,
    code_version    TEXT NOT NULL,
    param_hash      TEXT NOT NULL,
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.fundamental_method_versions IS
    'Immutable method versions. engine_version is derived '
    '{code_version}:{param_hash[:8]} and written once — never hand-bumped.';

-- Parameter rows are IMMUTABLE. Retuning inserts a NEW version rather than
-- editing these, so every historical score stays reproducible from the version
-- it was computed under.
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_method_params (
    engine_version  TEXT NOT NULL
                        REFERENCES uw_scan.fundamental_method_versions (engine_version),
    param_key       TEXT NOT NULL,
    param_value     NUMERIC NOT NULL,
    PRIMARY KEY (engine_version, param_key)
);

CREATE TABLE IF NOT EXISTS uw_scan.fundamental_method_state (
    singleton_id            INT PRIMARY KEY DEFAULT 1 CHECK (singleton_id = 1),
    active_engine_version   TEXT NOT NULL
                                REFERENCES uw_scan.fundamental_method_versions (engine_version),
    activated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.fundamental_method_state IS
    'Singleton pointer to the active method version. CHECK (singleton_id = 1) '
    'constrains the row VALUE, not its EXISTENCE — it happily permits DELETE, '
    'which is what the delete trigger below forbids.';

CREATE OR REPLACE FUNCTION uw_scan.fundamental_method_state_no_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'fundamental_method_state is a singleton: activate a different version '
        'with UPDATE, never DELETE (deleting leaves every computation '
        'method-less)';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fundamental_method_state_no_delete
    ON uw_scan.fundamental_method_state;
CREATE TRIGGER trg_fundamental_method_state_no_delete
    BEFORE DELETE ON uw_scan.fundamental_method_state
    FOR EACH ROW EXECUTE FUNCTION uw_scan.fundamental_method_state_no_delete();


-- ---------------------------------------------------------------------------
-- Stage-2 outputs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_scores (
    result_id       BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    as_of           DATE NOT NULL,
    engine_version  TEXT NOT NULL
                        REFERENCES uw_scan.fundamental_method_versions (engine_version),
    -- Covers the financial inputs AND company_type AND the active param set.
    -- Financial inputs alone would let a type flip produce new scores under an
    -- unchanged hash, leaving the stale row alive and indistinguishable.
    inputs_hash     TEXT NOT NULL,

    -- The period the score describes, and when the world could have known it.
    -- Both stored so a point-in-time query never has to re-derive them.
    period_end          DATE NOT NULL,
    knowledge_date      DATE NOT NULL,
    -- TRUE when knowledge_date came from a real filing_date, FALSE when it fell
    -- back to period_end + lag. A consumer that needs leak-free data filters on
    -- this; measured cost of ignoring it is composite IC 0.059 vs 0.039.
    filing_date_known   BOOLEAN NOT NULL,

    composite       NUMERIC,
    -- One column per feature rather than a JSONB blob: these are a fixed,
    -- versioned vocabulary that the card renders individually and the screen
    -- sorts on, and a typed column is what makes a stale/missing one visible.
    rev_growth              NUMERIC,
    gross_margin            NUMERIC,
    op_margin               NUMERIC,
    fcf_margin              NUMERIC,
    roe                     NUMERIC,
    neg_net_debt_ebitda     NUMERIC,
    asset_turnover          NUMERIC,

    -- How many of the seven were present. The composite refuses to score a name
    -- on fewer than four, and the card's coverage block reads this rather than
    -- recomputing it.
    features_present    INT NOT NULL,
    -- The exact tier-1 rows consumed, so an old inputs_hash can be reconstructed
    -- after later restatements arrive.
    source_obs_ids      BIGINT[] NOT NULL DEFAULT '{}',
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, as_of, engine_version, inputs_hash)
);

COMMENT ON TABLE uw_scan.fundamental_scores IS
    'Stage-2 subscores + composite. Values are RAW feature levels, not 0-100 '
    'ranks: a rank is only meaningful against a stated cross-section, and the '
    'ranking is scoped to the wide tier (spec §4.3).';

COMMENT ON COLUMN uw_scan.fundamental_scores.composite IS
    'Cross-sectional z-score mean under the active method version. Valid as a '
    'SORT KEY only across the ranked tier, never at core-25 width — and never '
    'as an expected-return estimate (2026-08-12 cost study: zero gross alpha).';

CREATE INDEX IF NOT EXISTS ix_fundamental_scores_ticker_asof
    ON uw_scan.fundamental_scores (ticker, as_of DESC);

CREATE INDEX IF NOT EXISTS ix_fundamental_scores_asof_composite
    ON uw_scan.fundamental_scores (as_of DESC, composite DESC NULLS LAST);
