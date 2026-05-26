-- 061_classification_accuracy_composite_method.sql
-- Extend regime_backtest_runs.composite_method CHECK to allow 'classification_accuracy'.
--
-- v0.3 patches:
--   CO-5: verify existing distinct composite_method values are all in the new
--         allow-list before drop; raise otherwise.
--   CL-12: wrap in explicit BEGIN/COMMIT (migrate.sh uses psql autocommit
--          per-statement; without BEGIN, table briefly has no constraint).

SET search_path = uw_scan, public;

BEGIN;

DO $$
DECLARE
    observed TEXT;
    allowed TEXT[] := ARRAY[
        'single_proxy',
        'risk_parity_3',
        'risk_parity_hyjk',
        'hy_minus_ig_spread',
        'equal_weight_3',
        'classification_accuracy'
    ];
    constraint_name TEXT;
BEGIN
    -- CO-5: assert every observed value is in the allow-list
    FOR observed IN
        SELECT DISTINCT composite_method FROM uw_scan.regime_backtest_runs
        WHERE composite_method IS NOT NULL
    LOOP
        IF NOT (observed = ANY(allowed)) THEN
            RAISE EXCEPTION
                'Migration 061 would regress composite_method %; not in allow-list',
                observed;
        END IF;
    END LOOP;

    -- Drop any pre-existing composite_method CHECK constraints
    FOR constraint_name IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'uw_scan'
          AND rel.relname = 'regime_backtest_runs'
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) LIKE '%composite_method%'
    LOOP
        EXECUTE format(
            'ALTER TABLE uw_scan.regime_backtest_runs DROP CONSTRAINT IF EXISTS %I',
            constraint_name
        );
    END LOOP;
END $$;

ALTER TABLE uw_scan.regime_backtest_runs
    ADD CONSTRAINT regime_backtest_runs_composite_method_check
    CHECK (composite_method IN (
        'single_proxy',
        'risk_parity_3',
        'risk_parity_hyjk',
        'hy_minus_ig_spread',
        'equal_weight_3',
        'classification_accuracy'
    ));

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'Migration 061: composite_method now accepts classification_accuracy';
END $$;
