-- 134_company_identity.sql — governed, HISTORIZED issuer identity.
--
-- WHAT `fundamental_company_type` CANNOT DO
-- ----------------------------------------
-- It is keyed on `ticker` alone, so an assignment is an UPDATE. When a name is
-- reclassified, the previous classification is gone — and with it the ability to
-- answer "which type was this under when that score was computed". Every result
-- derived under the old type silently reads as though it had been computed under
-- the new one. `fundamental_scores.inputs_hash` already covers `company_type`
-- precisely so a flip produces new rows rather than reinterpreting old ones; that
-- protection is worth nothing if the old value cannot be recovered.
--
-- This table stores identity as INTERVALS. An assignment closes the open interval
-- and opens a new one. Nothing is ever overwritten, so a historical result can be
-- explained with the classification that actually produced it.
--
-- `fundamental_company_type` is NOT dropped and NOT migrated away from. It stays
-- the current-state cache every existing reader already uses; this table is the
-- history behind it, and `assign_identity` writes both.
--
-- WHY `issuer_cik` AND NOT A HAND-MAINTAINED ISSUER LIST
-- -----------------------------------------------------
-- Two tickers can be one issuer: GOOG/GOOGL share CIK 0001652044 and FOX/FOXA
-- share 0001754301 (verified 2026-08-25). Their fundamentals are the SAME
-- filings, so admitting both into one cross-section would double-count the issuer
-- and hand it twice the weight. SEC's CIK already answers "same issuer?" from
-- evidence Argon now mirrors (migration 132), so no separate list is maintained
-- and none can drift.
--
-- WHY `status` IS SEPARATE FROM `company_type`
-- --------------------------------------------
-- `unclassified` currently means two different things that must not be conflated:
-- "we looked and no rule matched" and "we never looked". Worse, a defaulted
-- classification and an evidenced one are indistinguishable once written, so a
-- routing decision made by a fallback reads exactly like one made from evidence.
-- `status` records which it was, which is what makes the coverage number
-- meaningful rather than decorative.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.company_identity (
    identity_id  bigserial PRIMARY KEY,
    ticker       text NOT NULL,
    issuer_cik   text,
    company_type text NOT NULL,
    sector       text,
    currency     text,
    status       text NOT NULL,
    evidence     text NOT NULL,
    note         text,
    valid_from   timestamptz NOT NULL DEFAULT now(),
    valid_to     timestamptz,
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT company_identity_status_check
        CHECK (status IN ('evidenced', 'defaulted', 'manual')),
    CONSTRAINT company_identity_interval_check
        CHECK (valid_to IS NULL OR valid_to > valid_from)
);

COMMENT ON TABLE uw_scan.company_identity IS
    'Historized issuer identity: company_type, sector, currency and issuer CIK as '
    'validity intervals. fundamental_company_type stays the current-state cache; '
    'this is the history behind it, so a historical score can be explained with '
    'the classification that actually produced it rather than today''s.';

COMMENT ON COLUMN uw_scan.company_identity.status IS
    'evidenced = a rule matched real evidence. defaulted = nothing matched and the '
    'pooled fallback was applied. manual = a human override. Without this, a '
    'routing decision made by a fallback is indistinguishable from one made from '
    'evidence, and the coverage number means nothing.';

COMMENT ON COLUMN uw_scan.company_identity.issuer_cik IS
    'SEC CIK from sec_cik_map. Two tickers sharing one CIK are ONE issuer with '
    'two share classes (GOOG/GOOGL, FOX/FOXA), whose fundamentals are the same '
    'filings — admitting both to a cross-section double-counts the issuer.';

COMMENT ON COLUMN uw_scan.company_identity.valid_to IS
    'NULL = the open, current interval. At most one per ticker, enforced below.';

-- At most one open interval per ticker. Without this, a failed close leaves two
-- "current" classifications and every as-of read becomes non-deterministic.
CREATE UNIQUE INDEX IF NOT EXISTS company_identity_open_uq
    ON uw_scan.company_identity (ticker)
    WHERE valid_to IS NULL;

CREATE INDEX IF NOT EXISTS ix_company_identity_asof
    ON uw_scan.company_identity (ticker, valid_from DESC);

CREATE INDEX IF NOT EXISTS ix_company_identity_issuer
    ON uw_scan.company_identity (issuer_cik)
    WHERE issuer_cik IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_company_identity_status
    ON uw_scan.company_identity (status);
