-- 032_charm_signal_pin_source_date.sql — mark stale OI-chain source for pin metrics.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.charm_signals
    ADD COLUMN IF NOT EXISTS pin_source_date DATE;

COMMENT ON COLUMN uw_scan.charm_signals.pin_source_date
    IS 'option_chain_per_strike snapshot_date used for pin candidate metrics; may lag market_date.';

COMMIT;
