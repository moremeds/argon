-- 043_gold_posture.sql — Phase A1 (Gold).
-- Persisted daily posture across the three lenses — the load-bearing replay/audit table.
--
-- Replay scaffold: inputs_jsonb pins the exact (series_id, obs_date, as_of) used to
-- compute each row. Replay queries reconstruct the same posture by re-resolving those
-- inputs and selecting the first computed row per (obs_date, computed_at ASC).
--
-- GOLD COMPASS extensions (posture chip + UI payload JSONBs) live inline in this
-- migration so the table is complete from day one — no follow-up ALTER required.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.gold_posture_daily (
  obs_date                   DATE        NOT NULL,
  computed_at                TIMESTAMPTZ NOT NULL,

  -- correlation gauge
  gauge_corr_60d             NUMERIC     NULL,
  gauge_corr_126d            NUMERIC     NULL,
  gauge_corr_252d            NUMERIC     NULL,
  gauge_corr_504d            NUMERIC     NULL,
  gauge_corr_252d_returns    NUMERIC     NULL,
  gauge_state                TEXT        NOT NULL,

  -- structural posture (Lens 1)
  structural_state_label     TEXT        NULL,
  cb_strategic_12m_sum_t     NUMERIC     NULL,
  cb_tactical_12m_sum_t      NUMERIC     NULL,
  cb_diversifier_12m_sum_t   NUMERIC     NULL,
  gld_holdings_t             NUMERIC     NULL,
  gld_30d_net_flow_t         NUMERIC     NULL,
  comex_registered_oz        NUMERIC     NULL,
  comex_20d_roc_pct          NUMERIC     NULL,
  cot_mm_net_pct             NUMERIC     NULL,

  -- cyclical posture (Lens 2)
  cyclical_zone_label        TEXT        NULL,
  cpi_yoy                    NUMERIC     NULL,
  t5yifr                     NUMERIC     NULL,
  dfii10                     NUMERIC     NULL,
  dfii10_60d_change_bps      NUMERIC     NULL,
  factors_jsonb              JSONB       NULL,

  -- valuation overlay (Lens 3)
  valuation_flag             TEXT        NULL,
  real_price_percentile      NUMERIC     NULL,
  gold_m2_ratio_percentile   NUMERIC     NULL,
  gold_spx_ratio_percentile  NUMERIC     NULL,

  -- posture text (computed, ready for UI)
  structural_posture_text    TEXT        NULL,
  cyclical_posture_text      TEXT        NULL,
  valuation_posture_text     TEXT        NULL,

  -- GOLD COMPASS posture chips (FAVORABLE / NEUTRAL / STRETCHED / SUSPENDED / DEGRADED)
  structural_posture_chip    TEXT        NULL,
  cyclical_posture_chip      TEXT        NULL,
  valuation_posture_chip     TEXT        NULL,

  -- GOLD COMPASS UI payloads
  spot_jsonb                 JSONB       NULL,
  data_freshness_jsonb       JSONB       NULL,
  decomposition_jsonb        JSONB       NULL,
  correlation_history_jsonb  JSONB       NULL,
  gld_history_jsonb          JSONB       NULL,
  gold_history_jsonb         JSONB       NULL,

  -- provenance
  inputs_jsonb               JSONB       NOT NULL,

  PRIMARY KEY (obs_date, computed_at)
);

CREATE INDEX IF NOT EXISTS idx_gold_posture_daily_latest
  ON uw_scan.gold_posture_daily (obs_date DESC, computed_at DESC);
