-- 028_cockpit_research_fields.sql — persist remaining Cockpit research features.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.matrix_state_snapshots
    ADD COLUMN IF NOT EXISTS threshold_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS vanna_conditional_reading TEXT,
    ADD COLUMN IF NOT EXISTS directional_imbalance_3d NUMERIC,
    ADD COLUMN IF NOT EXISTS vanna_oi_change_bias TEXT,
    ADD COLUMN IF NOT EXISTS charm_regime TEXT,
    ADD COLUMN IF NOT EXISTS charm_stress_override BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS skew_25d_5d_change NUMERIC,
    ADD COLUMN IF NOT EXISTS skew_regime TEXT,
    ADD COLUMN IF NOT EXISTS skew_term_structure NUMERIC,
    ADD COLUMN IF NOT EXISTS single_point_bump_pct NUMERIC,
    ADD COLUMN IF NOT EXISTS full_curve_slope_pct NUMERIC,
    ADD COLUMN IF NOT EXISTS front_back_spread NUMERIC,
    ADD COLUMN IF NOT EXISTS term_johnson_slope_pc1 NUMERIC,
    ADD COLUMN IF NOT EXISTS atm_straddle_mid NUMERIC,
    ADD COLUMN IF NOT EXISTS implied_move_expected_abs NUMERIC,
    ADD COLUMN IF NOT EXISTS implied_move_event_percentile NUMERIC,
    ADD COLUMN IF NOT EXISTS vrp_zscore_252d NUMERIC;

ALTER TABLE uw_scan.vanna_signals
    ADD COLUMN IF NOT EXISTS vanna_conditional_reading TEXT,
    ADD COLUMN IF NOT EXISTS directional_imbalance_3d NUMERIC,
    ADD COLUMN IF NOT EXISTS vanna_oi_change_bias TEXT;

ALTER TABLE uw_scan.charm_signals
    ADD COLUMN IF NOT EXISTS charm_regime TEXT,
    ADD COLUMN IF NOT EXISTS charm_stress_override BOOLEAN DEFAULT false;

ALTER TABLE uw_scan.flow_events
    ADD COLUMN IF NOT EXISTS flow_footprint_label TEXT,
    ADD COLUMN IF NOT EXISTS aggressor_label_confidence NUMERIC;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_30d_settlements (
    ticker          TEXT NOT NULL,
    market_date     DATE NOT NULL,
    iv_30d          NUMERIC,
    settlement_date DATE,
    rv_subsequent   NUMERIC,
    vrp_strict      NUMERIC,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON TABLE uw_scan.vrp_30d_settlements
    IS 'Strict VRP settlement rows: IV_30d(t) against subsequent realized volatility.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.vanna_conditional_reading
    IS 'Four-way vanna conditional reading for replay and validation.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.directional_imbalance_3d
    IS '3-trading-event-day ask/bid call-put premium imbalance feeding vanna.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.implied_move_expected_abs
    IS 'Expected absolute move proxy, 0.7979 x straddle/spot or term implied_move_perc fallback.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.threshold_version
    IS 'Threshold/config version used to derive this matrix state for replay.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.front_back_spread
    IS 'Back minus front ATM IV term spread; positive means contango.';

COMMIT;
