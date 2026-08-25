-- 136_fundamental_dimensions.sql — research-priority dimensions, persisted
-- independently, each carrying the permission it is allowed to exercise.
--
-- WHY SEPARATE ROWS AND NOT MORE COLUMNS ON fundamental_scores
-- ------------------------------------------------------------
-- Because `authority` is per DIMENSION, not per result. `operating_quality` is
-- capped at `descriptive` (its two inputs measured INVERTED — high-margin names
-- underperformed) while `growth` reaches `research_priority`. A column layout
-- would force one authority for the whole row, which is exactly the flattening
-- that lets a contradicted sign ride along inside a validated composite.
--
-- Separate rows also make "which dimensions were missing" a queryable fact
-- rather than a NULL that could equally mean "zero".
--
-- THE PERMISSION IS DATA, NOT DOCUMENTATION
-- -----------------------------------------
-- A permission that lives only in prose is one a UI can exceed by accident. The
-- CHECK constraint below is the floor: no row may claim `investment_ranking`,
-- which needs the GX gate (active-plus-delisted PIT, out-of-sample, regime and
-- cost evidence, and an operator decision) that this program does not provide.
--
-- WHY value IS NULLABLE AND THAT IS NOT A DEFAULT
-- -----------------------------------------------
-- A dimension with no present input stores NULL, never 0.0. Zero is the
-- cross-section MEAN: writing it for a name with no balance-sheet data scores
-- that name as exactly average on it, which is a fabricated observation wearing
-- the shape of a measured one. `inputs_present` records how many of the
-- dimension's features were actually there.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.fundamental_dimensions (
    dimension_id    bigserial PRIMARY KEY,
    result_id       bigint NOT NULL
                    REFERENCES uw_scan.fundamental_scores(result_id)
                    ON DELETE CASCADE,
    ticker          text NOT NULL,
    as_of           date NOT NULL,
    engine_version  text NOT NULL,
    dimension       text NOT NULL,
    value           numeric,
    inputs_present  integer NOT NULL DEFAULT 0,
    inputs_expected integer NOT NULL DEFAULT 0,
    authority       text NOT NULL,
    detail_jsonb    jsonb NOT NULL DEFAULT '{}'::jsonb,
    computed_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fundamental_dimensions_authority_check
        CHECK (authority IN ('descriptive', 'research_priority',
                             'directional_monitor')),
    CONSTRAINT fundamental_dimensions_uq UNIQUE (result_id, dimension)
);

COMMENT ON TABLE uw_scan.fundamental_dimensions IS
    'Research-priority dimensions per score result, persisted independently so '
    'each can carry its OWN permission. A column layout would force one authority '
    'per row, which is how a contradicted sign rides along inside a validated '
    'composite.';

COMMENT ON COLUMN uw_scan.fundamental_dimensions.authority IS
    'Spec 6.4 ladder. investment_ranking is REFUSED by CHECK, not merely unused: '
    'it needs the GX gate (active-plus-delisted PIT, OOS, regime, cost, operator '
    'approval) that this program does not provide.';

COMMENT ON COLUMN uw_scan.fundamental_dimensions.value IS
    'NULL when no input was present. Never 0.0 — zero is the cross-section MEAN, '
    'so writing it would score a name with no data as exactly average.';

CREATE INDEX IF NOT EXISTS ix_fundamental_dimensions_lookup
    ON uw_scan.fundamental_dimensions (ticker, as_of DESC, dimension);

CREATE INDEX IF NOT EXISTS ix_fundamental_dimensions_engine
    ON uw_scan.fundamental_dimensions (engine_version, dimension);
