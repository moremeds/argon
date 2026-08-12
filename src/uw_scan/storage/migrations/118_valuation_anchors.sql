-- 118_valuation_anchors.sql — company-type assignment + stage-3 anchor bands.
-- Idempotent.
--
-- The band is a price range derived from a name's OWN valuation history: each
-- level is the price at which this company's valuation yield would sit at a
-- stated percentile of its own past. Measured basis, 2026-08-12: `sales_to_ev`
-- market-neutral 2q IC +0.0744 (t 5.77), surviving a pure-reversal control.
-- See docs/research/2026-08-12-fundamental-valuation-timeseries/VERDICT.md.
--
-- OWN-HISTORY, NEVER CROSS-SECTIONAL. Ranking a name against OTHER names on
-- value is INVERTED in this universe (book_to_price IC -0.0365, t -2.32). The
-- two quantities share a word and carry opposite signs, so the distinction is
-- structural rather than stylistic.

SET search_path TO uw_scan, public;

-- ---------------------------------------------------------------------------
-- company_type — the second axis, and NOT a chain layer
-- ---------------------------------------------------------------------------
-- Orthogonal to `watchlist_chain.layer` (spec §5.3): layer is position in the
-- supply chain, company_type is which valuation math is correct. L3 holds both
-- ANET and CEG, which need entirely different methods.
--
-- Persisted rather than derived live, deliberately. A ticker can belong to three
-- chains and therefore has no unique layer, and a valuation method that flipped
-- because someone edited a chain would silently reprice the name.
CREATE TABLE IF NOT EXISTS uw_scan.fundamental_company_type (
    ticker          TEXT PRIMARY KEY,
    company_type    TEXT NOT NULL,
    -- 'seeded' (from sector+chain) or 'manual' (hand-set). A manual assignment
    -- is never overwritten by a reseed; that is the whole point of recording it.
    source          TEXT NOT NULL DEFAULT 'seeded'
                        CHECK (source IN ('seeded', 'manual')),
    note            TEXT,
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.fundamental_company_type IS
    'Per-ticker valuation-method routing. Editing a row changes anchors and is '
    'inside inputs_hash, so a change appends new anchor rows rather than '
    'silently invalidating the old ones.';

-- ---------------------------------------------------------------------------
-- Stage-3 outputs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.valuation_anchors (
    result_id       BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    as_of           DATE NOT NULL,
    engine_version  TEXT NOT NULL
                        REFERENCES uw_scan.fundamental_method_versions (engine_version),
    -- Same two-part identity as fundamental_scores: engine_version names the
    -- METHOD, inputs_hash names the INPUTS. company_type is inside the hash, so
    -- a type flip produces a genuinely new row instead of colliding with the old.
    inputs_hash     TEXT NOT NULL,

    company_type    TEXT NOT NULL,
    -- The yield the band was built from: sales_to_ev | fcf_yield | ebitda_to_ev.
    -- Stored per row rather than looked up from company_type at read time, so a
    -- later remapping cannot retroactively relabel what a historical band used.
    method          TEXT NOT NULL,

    -- Ascending in price. NULL where the yield inversion diverges (a
    -- non-positive target yield) or lands below zero after net debt.
    buy_below       NUMERIC,
    observe_low     NUMERIC,
    observe_mid     NUMERIC,
    observe_high    NUMERIC,
    risk_above      NUMERIC,

    -- Spot at compute time and where it sat in the name's own yield history.
    -- Both persisted: recomputing the percentile later against a longer history
    -- would silently restate what the card said on the day.
    spot                NUMERIC,
    spot_percentile     NUMERIC CHECK (
                            spot_percentile IS NULL
                            OR (spot_percentile >= 0 AND spot_percentile <= 1)
                        ),

    history_quarters    INT NOT NULL,
    confidence          TEXT NOT NULL
                            CHECK (confidence IN ('high', 'medium', 'low', 'none')),
    -- Every reason, never a collapsed badge. "medium because the filing is 180
    -- days old" is actionable; "medium" is not.
    confidence_reasons_jsonb    JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- The numerator, net debt and share count the levels were inverted from, so
    -- any single level can be recomputed by hand from this row alone.
    inputs_jsonb        JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_obs_ids      BIGINT[] NOT NULL DEFAULT '{}',
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (ticker, as_of, engine_version, inputs_hash),

    -- The band must ascend in price. Enforced in the schema and not only in the
    -- builder because an out-of-order band is not a bad number, it is an
    -- inverted recommendation: `buy_below` above `risk_above` tells the reader
    -- to buy high. NULL comparisons yield NULL and pass, which is intended —
    -- an absent level is unknown, not disordered.
    CONSTRAINT valuation_anchors_band_ascends CHECK (
        (buy_below IS NULL OR observe_low IS NULL OR buy_below <= observe_low)
        AND (observe_low IS NULL OR observe_mid IS NULL OR observe_low <= observe_mid)
        AND (observe_mid IS NULL OR observe_high IS NULL OR observe_mid <= observe_high)
        AND (observe_high IS NULL OR risk_above IS NULL OR observe_high <= risk_above)
    )
);

COMMENT ON TABLE uw_scan.valuation_anchors IS
    'Stage-3 price band from a name OWN valuation history. Each level is the '
    'price at which its valuation yield would sit at a stated percentile of its '
    'own past. Not a forecast and not a cross-sectional rank.';

COMMENT ON COLUMN uw_scan.valuation_anchors.spot_percentile IS
    'Fraction of this ticker own yield history at or below the current yield. '
    'High = cheap versus its own past, because every method is a yield.';

-- The card reads "newest band for this ticker under the active method".
CREATE INDEX IF NOT EXISTS ix_valuation_anchors_ticker_asof
    ON uw_scan.valuation_anchors (ticker, engine_version, as_of DESC);
