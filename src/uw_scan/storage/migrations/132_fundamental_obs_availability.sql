-- 132_fundamental_obs_availability.sql — append-only availability evidence for
-- statement content VERSIONS. Additive and idempotent; migration 114 is not
-- touched and no existing row is rewritten here.
--
-- WHY A TABLE AND NOT TWO COLUMNS ON THE OBSERVATION
-- --------------------------------------------------
-- `fundamental_statement_obs` is already an honest immutable ledger: one row per
-- normalized content version, a restatement lands BESIDE its predecessor, only
-- `last_seen_at` is mutable. What it never carried is WHEN EACH VERSION BECAME
-- AVAILABLE, so `statement_panel()` answered that question with the only
-- ordering it had — `obs_id DESC` — and applied no cutoff at all: every
-- historical question got today's panel. The missing cutoff is the defect. The
-- sort key is not: `obs_id` is a BIGSERIAL assigned in the same INSERT as
-- `first_observed_at`, so it cannot disagree with a capture-time ordering
-- (measured 0/200 multi-version identities on production, 2026-08-24). The sort
-- key starts mattering only when `true_pit` arrives from a source independent of
-- insertion order.
--
-- The evidence for ONE version strengthens over time: a capture bound today, an
-- SEC amendment artifact next month. Two columns would force that improvement to
-- be an UPDATE, destroying the record of what Argon believed and when. A child
-- table makes it an INSERT.
--
-- WHY filing_published_at IS NOT ENOUGH
-- -------------------------------------
-- `fundamental_statement_obs.filing_published_at` describes when the ORIGINAL
-- filing for the period was published. A later content hash for the same period
-- is a different artifact and inherits none of that date's authority. Promoting
-- a restatement to `true_pit` on the strength of the original's filing date
-- would reintroduce the exact look-ahead this table exists to prevent, wearing
-- an honest label. The legacy backfill (Task 5) therefore issues NO true-PIT
-- claim from that column — see uw_scan.fundamentals.observation_time.
--
-- THE FOUR CLASSES
-- ----------------
--   true_pit         positive version-level publication/amendment evidence for
--                    this exact content. The only class a leak-free replay uses.
--   capture_bounded  Argon holds this exact content and first saw it at
--                    available_at. Conservative by construction: the world may
--                    have known earlier and this class never claims otherwise.
--   current_vintage  usable for today's page, no historical claim at all.
--                    Every legacy row starts here.
--   unknown          not even a usable timestamp. Fails closed everywhere.
--
-- The two CHECK constraints below are the contract's teeth. A timed class with a
-- NULL instant would admit at EVERY cutoff; an untimed class carrying an instant
-- is indistinguishable, to any later query, from one that makes a real claim.
--
-- NOT A DATA-GAP-HEALER DATASET, DELIBERATELY
-- -------------------------------------------
-- `fundamental_statement_obs` IS registered with the healer, because a missing
-- quarter there is healed by re-fetching it from UW. Its availability claims are
-- DERIVED from rows Argon already holds: there is no provider to re-fetch from
-- and no calendar spine to be short of. A gap is repaired by re-running the
-- backfill, which is deterministic and idempotent, so this table gets no
-- `DatasetRegistryEntry` (same reasoning as migration 113).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.fundamental_obs_availability (
    availability_id   BIGSERIAL PRIMARY KEY,
    obs_id            BIGINT NOT NULL
                      REFERENCES uw_scan.fundamental_statement_obs (obs_id)
                      ON DELETE CASCADE,
    -- Identifies the RULE that produced the claim, not the row. Replaying the
    -- same rule over the same observation collides on the UNIQUE below and
    -- writes nothing, which is what makes the backfill resumable with no
    -- progress table. A rule change moves the key; it never mutates old claims.
    claim_key         TEXT NOT NULL,
    evidence_class    TEXT NOT NULL,
    -- The instant from which this version may be admitted. Meaning is set by
    -- evidence_class and by nothing else.
    available_at      TIMESTAMPTZ,
    -- WHO vouched ('argon_capture', 'argon_legacy_classification', 'sec_edgar').
    -- The class says HOW STRONGLY; the source says on whose authority.
    evidence_source   TEXT NOT NULL,
    -- Pointer to the artifact, when one exists: an accession number, a URL.
    evidence_ref      TEXT,
    evidence_jsonb    JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fundamental_obs_availability_class_check
        CHECK (evidence_class IN
               ('true_pit', 'capture_bounded', 'current_vintage', 'unknown')),
    -- A timed class MUST carry its instant; an untimed class MUST NOT.
    CONSTRAINT fundamental_obs_availability_instant_check
        CHECK (
            (evidence_class IN ('true_pit', 'capture_bounded')
             AND available_at IS NOT NULL)
            OR
            (evidence_class IN ('current_vintage', 'unknown')
             AND available_at IS NULL)
        ),
    CONSTRAINT fundamental_obs_availability_claim_uq UNIQUE (obs_id, claim_key)
);

COMMENT ON TABLE uw_scan.fundamental_obs_availability IS
    'Append-only availability evidence for statement content versions. One row '
    'per (observation, rule). Stronger evidence INSERTS another claim; nothing '
    'is ever updated in place, so what Argon believed and when survives.';

COMMENT ON COLUMN uw_scan.fundamental_obs_availability.evidence_class IS
    'true_pit | capture_bounded | current_vintage | unknown. The original '
    'period filing date does NOT promote a later content hash to true_pit — a '
    'restatement is a different artifact and inherits none of that authority.';

COMMENT ON COLUMN uw_scan.fundamental_obs_availability.available_at IS
    'Instant from which the version may be admitted. Required for the timed '
    'classes, forbidden for the untimed ones — a current_vintage row with a '
    'timestamp reads as a historical claim to every later query.';

COMMENT ON COLUMN uw_scan.fundamental_obs_availability.claim_key IS
    'Rule identity, versioned (e.g. capture:first_observed_at:v1). Makes a '
    'replay a no-op via UNIQUE (obs_id, claim_key).';

-- The as-of reader asks: which claims for these observations are of an admitted
-- class and at or before the cutoff. That is this index, in that order.
CREATE INDEX IF NOT EXISTS ix_fundamental_obs_availability_asof
    ON uw_scan.fundamental_obs_availability (obs_id, evidence_class, available_at);

-- Coverage reporting walks the table by class; the audit in Task 9 is the only
-- caller, but a sequential scan of every claim to count four buckets is a poor
-- trade against one small index.
CREATE INDEX IF NOT EXISTS ix_fundamental_obs_availability_class
    ON uw_scan.fundamental_obs_availability (evidence_class);
