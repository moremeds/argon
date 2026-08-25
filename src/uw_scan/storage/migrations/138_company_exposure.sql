-- 138_company_exposure.sql — ECONOMIC exposure, kept structurally apart from
-- semantic membership (migration 137).
--
-- THE CONSTRAINT THAT MATTERS
-- ---------------------------
-- `magnitude` may be non-NULL ONLY when the row is `disclosed` AND its
-- `magnitude_basis` names something that discloses a number. That is the design
-- requirement "no hand-authored percentage masquerades as measured exposure",
-- made structural instead of reviewable. An analyst may still record that a
-- company is a supplier to a chain — that is a legitimate research assertion —
-- but the database will not let that assertion carry a percentage.
--
-- Without the constraint, the failure is silent and total: a hand-typed 38%
-- renders identically to a 38% read off a segment disclosure, and every chain
-- aggregate built on top inherits the fiction with no way to detect it.
--
-- WHY A COUNTERPARTY IS NULLABLE AND A ROLE IS NOT
-- ------------------------------------------------
-- "NVDA supplies the AI-infrastructure chain" is evidenced by its own revenue
-- disclosure. "NVDA supplies MSFT specifically" is a NAMED EDGE and needs a
-- named source. Most exposures Argon can evidence are the first kind, so
-- `counterparty` is null far more often than not, and a null there is the honest
-- state rather than an incomplete row.
--
-- NO PROPAGATION IS IMPLIED
-- -------------------------
-- Nothing in this schema licenses walking an edge and inferring a consequence.
-- The measured basis says not to: the capex-demand ledger's cross-name signal
-- collapsed from +0.247 to +0.015 (p=0.44) among same-sector pairs, so a chain
-- edge carries no demonstrated forward information. This table describes; it
-- does not conduct.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.company_exposure (
    exposure_id      bigserial PRIMARY KEY,
    taxonomy_version text NOT NULL,
    ticker           text NOT NULL,
    chain            text NOT NULL,
    role             text NOT NULL,
    direction        text,
    counterparty     text,
    magnitude        numeric,
    magnitude_basis  text NOT NULL,
    confidence       text NOT NULL,
    status           text NOT NULL,
    source_kind      text NOT NULL,
    source_ref       text,
    source_obs_id    bigint
                     REFERENCES uw_scan.revenue_breakdown_obs(obs_id)
                     ON DELETE RESTRICT,
    note             text,
    valid_from       timestamptz NOT NULL DEFAULT now(),
    valid_to         timestamptz,
    recorded_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT company_exposure_role_check
        CHECK (role IN ('supplier', 'manufacturer', 'component', 'integrator',
                        'customer', 'beneficiary', 'competitor', 'other')),
    CONSTRAINT company_exposure_direction_check
        CHECK (direction IS NULL OR direction IN ('upstream', 'downstream',
                                                  'lateral')),
    CONSTRAINT company_exposure_basis_check
        CHECK (magnitude_basis IN ('disclosed_revenue', 'segment_share',
                                   'geographic_share', 'customer_concentration',
                                   'capacity', 'capex', 'qualitative',
                                   'unknown')),
    CONSTRAINT company_exposure_confidence_check
        CHECK (confidence IN ('high', 'medium', 'low')),
    CONSTRAINT company_exposure_status_check
        CHECK (status IN ('disclosed', 'inferred', 'asserted')),
    CONSTRAINT company_exposure_interval_check
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    -- THE constraint. A number requires a disclosure that produced it.
    CONSTRAINT company_exposure_magnitude_requires_evidence
        CHECK (
            magnitude IS NULL
            OR (status = 'disclosed'
                AND magnitude_basis IN ('disclosed_revenue', 'segment_share',
                                        'geographic_share',
                                        'customer_concentration', 'capacity',
                                        'capex'))
        ),
    CONSTRAINT company_exposure_magnitude_range
        CHECK (magnitude IS NULL OR (magnitude >= 0 AND magnitude <= 1))
);

COMMENT ON TABLE uw_scan.company_exposure IS
    'Where a company economically participates in a chain: role, direction, '
    'counterparty, and a magnitude that may exist ONLY when something disclosed '
    'it. Distinct from chain_membership, which is a semantic claim.';

COMMENT ON CONSTRAINT company_exposure_magnitude_requires_evidence
    ON uw_scan.company_exposure IS
    'No hand-authored percentage may masquerade as measured exposure. An '
    'asserted or inferred row may name a role and a direction; it may not carry '
    'a number. Without this the failure is silent: a typed 38% renders exactly '
    'like a disclosed one.';

COMMENT ON COLUMN uw_scan.company_exposure.magnitude IS
    'Share in [0,1], NOT a percentage — a column that accepts both 0.38 and 38 '
    'gets both. NULL is the normal state.';

COMMENT ON COLUMN uw_scan.company_exposure.counterparty IS
    'A NAMED edge. Null for the common case: "sells into this chain" is '
    'evidenced by a revenue disclosure, "sells to MSFT" needs a named source.';

COMMENT ON COLUMN uw_scan.company_exposure.source_obs_id IS
    'RESTRICT: an exposure derived from a revenue breakdown must not outlive the '
    'observation that produced it, or the magnitude becomes unfalsifiable.';

CREATE UNIQUE INDEX IF NOT EXISTS company_exposure_open_uq
    ON uw_scan.company_exposure
       (taxonomy_version, ticker, chain, role, coalesce(counterparty, ''))
    WHERE valid_to IS NULL;

CREATE INDEX IF NOT EXISTS ix_company_exposure_chain
    ON uw_scan.company_exposure (taxonomy_version, chain, role);

CREATE INDEX IF NOT EXISTS ix_company_exposure_ticker
    ON uw_scan.company_exposure (ticker, taxonomy_version);
