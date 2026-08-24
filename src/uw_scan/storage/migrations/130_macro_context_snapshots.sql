-- 130_macro_context_snapshots.sql — four domain answers held as ONE answer.
--
-- MC2/MC3 landed macro_domain_states (the answer), macro_domain_state_evidence
-- (state -> observation) and macro_domain_state_dependencies (state -> state). Each domain
-- is therefore individually honest. What no table said is that four of them belong
-- together, so /macro composed four independent latest reads and the nightly worker --
-- which does use one as_of and the right causal order -- catches each domain's exception
-- and continues. A failed rates job lets USD read the PREVIOUS rates state (still
-- satisfying available_at <= as_of), persist a new USD state citing it, and gold consume
-- the mixture. Four cards render fresh and nothing can tell.
--
-- The snapshot exists to REFUSE. It never substitutes a fresher upstream to make a chain
-- look coherent; it records which domain broke the chain and how. Status is decided by
-- dependency-edge IDENTITY (does the upstream state_id a downstream actually cited equal
-- the one this snapshot holds for that domain), never by timestamp proximity.
--
-- The plan that first specified this reserved 117. The Fundamental lane took 117 and 118
-- long before it was written, so read the migration tail, never a plan's reservation.
--
-- Additive only. Nothing in 125 or 128 is altered.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_context_snapshots (
  snapshot_id          BIGSERIAL   PRIMARY KEY,
  as_of                TIMESTAMPTZ NOT NULL,
  assembled_at         TIMESTAMPTZ NOT NULL,
  -- Four shapes, deliberately distinguishable. "rates never ran" and "rates ran but USD
  -- ignored it" are both refusals and call for different operator actions, so collapsing
  -- them to a single "degraded" would destroy the only thing the status is for.
  status               TEXT        NOT NULL
    CHECK (status IN ('complete', 'partial', 'incompatible', 'stale')),
  -- [{domain, kind, detail}]. A refusal nobody can read is not a refusal.
  status_reasons_jsonb JSONB       NOT NULL DEFAULT '[]'::JSONB
    CHECK (jsonb_typeof(status_reasons_jsonb) = 'array'),
  -- Over the domain state IDENTITIES plus the assembler's parameters. A later evidence
  -- revision cannot change a stored snapshot's hash, because a revision produces a NEW
  -- state rather than editing one.
  inputs_hash          TEXT        NOT NULL
    CHECK (inputs_hash ~ '^[0-9a-f]{64}$'),
  assembler_version    TEXT        NOT NULL CHECK (btrim(assembler_version) <> ''),
  -- A snapshot cannot be assembled before the instant it answers for. The same shape as
  -- macro_domain_states' own computed_at >= as_of guard.
  CHECK (assembled_at >= as_of),
  -- Same question (as_of), same method (assembler_version), same inputs -> one row. A
  -- nightly rerun over unchanged states is a no-op, not a second opinion.
  UNIQUE (as_of, assembler_version, inputs_hash)
);

CREATE INDEX IF NOT EXISTS idx_macro_context_snapshots_replay
  ON uw_scan.macro_context_snapshots (as_of DESC, assembled_at DESC);

CREATE TABLE IF NOT EXISTS uw_scan.macro_context_snapshot_domains (
  snapshot_id BIGINT  NOT NULL
    REFERENCES uw_scan.macro_context_snapshots (snapshot_id) ON DELETE RESTRICT,
  domain      TEXT    NOT NULL
    CHECK (domain IN ('inflation', 'policy_rates', 'usd', 'gold')),
  -- NOT NULL on purpose. Absence is the LACK of a row, never a row carrying a null: a
  -- nullable state_id would make every reader decide again what a null meant, and one of
  -- them would decide it meant zero.
  state_id    BIGINT  NOT NULL
    REFERENCES uw_scan.macro_domain_states (state_id) ON DELETE RESTRICT,
  -- Stored rather than derived from a constant at read time, so a snapshot keeps the
  -- causal order it was assembled with even if the chain is ever reordered.
  ordinal     INTEGER NOT NULL CHECK (ordinal >= 0),
  -- Two answers for one domain in one snapshot is two snapshots.
  PRIMARY KEY (snapshot_id, domain),
  UNIQUE (snapshot_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_macro_context_snapshot_domains_state
  ON uw_scan.macro_context_snapshot_domains (state_id);
