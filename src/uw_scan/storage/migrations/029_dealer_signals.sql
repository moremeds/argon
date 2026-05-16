-- 029_dealer_signals.sql — durable Dealer-tab derived signals.
-- Research contract:
-- docs/superpowers/research/six-dimension-matrix/01-vanna.md §7
-- docs/superpowers/research/six-dimension-matrix/02-charm.md §7

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vanna_signals (
    ticker                 TEXT NOT NULL,
    market_date            DATE NOT NULL,
    dealer_net_vanna_proxy NUMERIC,
    flow_color_lookback_3d TEXT CHECK (
        flow_color_lookback_3d IN ('put_heavy', 'call_heavy', 'neutral')
    ),
    flow_put_premium_3d    NUMERIC,
    flow_call_premium_3d   NUMERIC,
    iv_30d_delta_5d        NUMERIC,
    generated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.charm_signals (
    ticker                 TEXT NOT NULL,
    market_date            DATE NOT NULL,
    pin_candidate_strike   NUMERIC,
    pin_candidate_expiry   DATE,
    pin_distance_sigma     NUMERIC,
    pin_regime_flag        BOOLEAN,
    dealer_net_charm_proxy NUMERIC,
    net_gamma              NUMERIC,
    net_gamma_sign         TEXT CHECK (
        net_gamma_sign IN ('positive', 'negative', 'neutral')
    ),
    gamma_regime           TEXT CHECK (
        gamma_regime IN ('long_gamma', 'short_gamma', 'neutral')
    ),
    generated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON TABLE uw_scan.vanna_signals
    IS 'Durable vanna-derived Dealer signals for forward validation and replay.';

COMMENT ON TABLE uw_scan.charm_signals
    IS 'Durable charm-derived Dealer signals for forward validation and replay.';

COMMIT;
