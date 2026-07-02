-- 094_drop_dead_legacy_tables.sql
--
-- Four tables with zero live writers, confirmed by full-repo grep:
--
-- option_surface_snapshots — S1 (001) deferred-to-S6 placeholder; S6 never
--   built a writer. Superseded a year later by option_surface_grid_daily
--   (077), an independent design with no FK relationship to this table.
--
-- scan_universe / scan_results — S2 (002) full-scan persistence for a since-
--   deleted Streamlit prototype UI. Only ever written by pipeline.run_full_scan,
--   itself only called from an integration test. The live Scanner page reads
--   scanner_candidate_snapshots / signal_hits / signal_gates / signal_context_flags
--   instead.
--
-- structure_ideas — S1 (001) trade-structure-recommendation stub. Its writer
-- (insert_structure_idea) has zero callers; the feature was scaffolded but
-- never implemented.
--
-- Idempotent: DROP TABLE IF EXISTS.

SET search_path TO uw_scan, public;

BEGIN;

DROP TABLE IF EXISTS uw_scan.option_surface_snapshots;
DROP TABLE IF EXISTS uw_scan.scan_universe;
DROP TABLE IF EXISTS uw_scan.scan_results;
DROP TABLE IF EXISTS uw_scan.structure_ideas;

COMMIT;
