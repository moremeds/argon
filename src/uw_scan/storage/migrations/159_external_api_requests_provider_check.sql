-- 159_external_api_requests_provider_check.sql
-- Widen external_api_requests.provider CHECK to the 12 non-UW source clients.
--
-- WHY
-- ---
-- Migration 019 allowed only 'uw' and 'massive'. The shared sources/_http.py
-- telemetry path emits ExternalApiRequestEvent for eleven more providers
-- (each client's self.PROVIDER constant; ohlc reports 'massive'), and the one
-- wired job today (rates_fred_ingest) fails this CHECK on every insert — the
-- recorder swallows the violation and the telemetry is lost.
--
-- The 13-value list is: 'uw', 'massive', plus each client PROVIDER in
-- src/uw_scan/sources/{cftc_cot,cftc_tff,cleveland_fed,etf_holdings,
-- fed_funds_futures_path,fred,gpr,lbma,treasury_supply,wgc_cb,wgc_etf}.py.
-- tests/unit/storage/test_migration_159_provider_check.py drift-guards this
-- list against those constants.
--
-- Replay safety
-- -------------
-- Every API boot re-runs every file (no schema_migrations table). The DO block
-- first checks whether a constraint named external_api_requests_provider_check
-- already accepts ALL 13 providers (LIKE ALL over the widened values — not
-- text equality, so a differently-ordered or reformatted def still counts).
-- Once the widened constraint exists the guard is false and the file is a
-- catalog lookup only: the large external_api_requests table is never touched
-- on repeat boots. When the guard IS true (first apply, or a hand-edited
-- narrower constraint), DROP CONSTRAINT IF EXISTS covers the no-constraint
-- case the widened-def check cannot distinguish.
--
-- NOT VALID: the ADD performs no table scan (an unguarded ADD on this table
-- would be an every-boot rewrite risk if the guard ever regressed). Every
-- existing row satisfies the widened list because it is a superset of the old
-- one, so validation could only ever pass; the check is still enforced on
-- every new INSERT/UPDATE from the moment it is added.

SET search_path TO uw_scan, public;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'external_api_requests_provider_check'
      AND conrelid = 'uw_scan.external_api_requests'::regclass
      AND pg_get_constraintdef(oid) LIKE ALL (ARRAY[
        '%''uw''%',
        '%''massive''%',
        '%''cftc_cot''%',
        '%''cftc_tff''%',
        '%''cleveland_fed''%',
        '%''etf_holdings''%',
        '%''fred''%',
        '%''frenzy_capital''%',
        '%''gpr''%',
        '%''lbma''%',
        '%''treasury_supply''%',
        '%''wgc_cb''%',
        '%''wgc_etf''%'
      ])
  ) THEN
    ALTER TABLE uw_scan.external_api_requests
      DROP CONSTRAINT IF EXISTS external_api_requests_provider_check;
    ALTER TABLE uw_scan.external_api_requests
      ADD CONSTRAINT external_api_requests_provider_check
      CHECK (provider IN (
        'uw',
        'massive',
        'cftc_cot',
        'cftc_tff',
        'cleveland_fed',
        'etf_holdings',
        'fred',
        'frenzy_capital',
        'gpr',
        'lbma',
        'treasury_supply',
        'wgc_cb',
        'wgc_etf'
      )) NOT VALID;
  END IF;
END $$;
