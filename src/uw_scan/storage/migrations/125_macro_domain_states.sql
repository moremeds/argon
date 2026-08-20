-- 125_macro_domain_states.sql — versioned macro domain states and their exact evidence.
--
-- A state is a claim ("inflation is COOLING, falling, and we know 0.62 of what we would
-- need to know") and a claim is only worth keeping if it can be argued with later. So the
-- row stores the method identity (engine_version + inputs_hash) alongside the answer, and
-- macro_domain_state_evidence pins the exact observation rows the answer stood on.
--
-- The plan reserved 116 for this migration; 116..122 were taken by intervening work, so
-- the reservation moved to 123. Additive only: no legacy rates/gold table is touched.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_domain_states (
  state_id                 BIGSERIAL   PRIMARY KEY,
  domain                   TEXT        NOT NULL
    CHECK (domain IN ('inflation', 'policy_rates', 'usd', 'gold', 'cross_domain')),
  as_of                    TIMESTAMPTZ NOT NULL,
  computed_at              TIMESTAMPTZ NOT NULL,
  engine_version           TEXT        NOT NULL CHECK (btrim(engine_version) <> ''),
  inputs_hash              TEXT        NOT NULL
    CHECK (inputs_hash ~ '^[0-9a-f]{64}$'),
  state                    TEXT        NOT NULL CHECK (btrim(state) <> ''),
  direction                TEXT        NOT NULL
    CHECK (direction IN ('RISING', 'FALLING', 'FLAT', 'UNKNOWN')),
  velocity_jsonb           JSONB       NOT NULL
    CHECK (jsonb_typeof(velocity_jsonb) = 'array'),
  -- Confidence is bounded because it reports how much we know, not how large the signal
  -- is. A number outside [0,1] would mean the product of knowledge terms was built wrong.
  confidence               NUMERIC     NOT NULL
    CHECK (confidence >= 0 AND confidence <= 1),
  confidence_reasons_jsonb JSONB       NOT NULL
    CHECK (jsonb_typeof(confidence_reasons_jsonb) = 'array'),
  contradictions_jsonb     JSONB       NOT NULL
    CHECK (jsonb_typeof(contradictions_jsonb) = 'array'),
  factors_jsonb            JSONB       NOT NULL
    CHECK (jsonb_typeof(factors_jsonb) = 'array'),
  notes_jsonb              JSONB       NOT NULL DEFAULT '[]'::JSONB
    CHECK (jsonb_typeof(notes_jsonb) = 'array'),
  status                   TEXT        NOT NULL DEFAULT 'published'
    CHECK (status IN ('published', 'quarantined')),
  quarantined_at           TIMESTAMPTZ NULL,
  quarantine_reason        TEXT        NULL,
  CHECK (computed_at >= as_of),
  CHECK (
    (status = 'published' AND quarantined_at IS NULL AND quarantine_reason IS NULL)
    OR (
      status = 'quarantined'
      AND quarantined_at IS NOT NULL
      AND btrim(COALESCE(quarantine_reason, '')) <> ''
    )
  ),
  -- Method identity. The same question (domain, as_of) answered by the same method
  -- (engine_version) over the same inputs (inputs_hash) is one row, not a new one every
  -- time the job runs.
  UNIQUE (domain, as_of, engine_version, inputs_hash)
);

CREATE INDEX IF NOT EXISTS idx_macro_domain_states_replay
  ON uw_scan.macro_domain_states (domain, as_of DESC, computed_at DESC)
  WHERE status = 'published';

COMMENT ON COLUMN uw_scan.macro_domain_states.as_of IS
  'Decision instant the state answers for; evidence may not become available after it.';
COMMENT ON COLUMN uw_scan.macro_domain_states.computed_at IS
  'Wall-clock instant Argon computed the state; always at or after as_of.';
COMMENT ON COLUMN uw_scan.macro_domain_states.inputs_hash IS
  'Identity of parameters plus the exact observations used; a moved threshold changes it.';
COMMENT ON COLUMN uw_scan.macro_domain_states.confidence IS
  'How much of the required knowledge we had, in [0,1]; never the size of the signal.';
COMMENT ON COLUMN uw_scan.macro_domain_states.status IS
  'published = fit to serve; quarantined = retained for audit and never served.';

CREATE TABLE IF NOT EXISTS uw_scan.macro_domain_state_evidence (
  state_id    BIGINT NOT NULL
    REFERENCES uw_scan.macro_domain_states (state_id) ON DELETE RESTRICT,
  obs_id      BIGINT NOT NULL
    REFERENCES uw_scan.macro_observations (obs_id) ON DELETE RESTRICT,
  causal_role TEXT   NOT NULL
    CHECK (
      causal_role IN (
        'realized',
        'breadth',
        'stickiness',
        'expectations_survey',
        'expectations_market',
        'policy_actual',
        'policy_committee',
        'policy_dealer',
        'policy_market_shadow',
        'curve',
        'decomposition_component',
        'supply',
        'positioning',
        'plumbing'
      )
    ),
  ordinal     INTEGER NOT NULL CHECK (ordinal >= 0),
  PRIMARY KEY (state_id, obs_id, causal_role),
  -- An order that repeats itself is not an order.
  UNIQUE (state_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_macro_domain_state_evidence_obs
  ON uw_scan.macro_domain_state_evidence (obs_id);

COMMENT ON COLUMN uw_scan.macro_domain_state_evidence.causal_role IS
  'What the observation did in this state; a breakeven and a survey are both about future inflation and are still different evidence.';

-- A state is a historical record of a decision, so it may be withdrawn from service but
-- never rewritten. The only permitted transition is published -> quarantined: an engine
-- later found wrong must stop being served without its past outputs being edited away.
CREATE OR REPLACE FUNCTION uw_scan.macro_domain_state_write_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'macro domain states are immutable'
      USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF (to_jsonb(NEW) - ARRAY['status', 'quarantined_at', 'quarantine_reason'])
        IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status', 'quarantined_at', 'quarantine_reason'])
       OR OLD.status <> 'published'
       OR NEW.status <> 'quarantined' THEN
      RAISE EXCEPTION 'macro domain states may only be quarantined, never rewritten'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_macro_domain_state_write_guard
  ON uw_scan.macro_domain_states;
CREATE TRIGGER trg_macro_domain_state_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON uw_scan.macro_domain_states
FOR EACH ROW EXECUTE FUNCTION uw_scan.macro_domain_state_write_guard();

-- The constraint that makes this table worth trusting. A state claims to answer a
-- question at an instant; recording it as standing on an observation that only became
-- available afterwards is exactly the lookahead the whole milestone exists to refuse.
-- SQL CHECK cannot see across tables, so it is a trigger.
CREATE OR REPLACE FUNCTION uw_scan.macro_domain_state_evidence_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  state_as_of TIMESTAMPTZ;
  obs_available_at TIMESTAMPTZ;
  obs_quality TEXT;
BEGIN
  IF TG_OP IN ('DELETE', 'UPDATE') THEN
    RAISE EXCEPTION 'macro domain state evidence is immutable'
      USING ERRCODE = '23514';
  END IF;

  SELECT as_of INTO state_as_of
  FROM uw_scan.macro_domain_states
  WHERE state_id = NEW.state_id;

  SELECT available_at, quality_status INTO obs_available_at, obs_quality
  FROM uw_scan.macro_observations
  WHERE obs_id = NEW.obs_id;

  IF obs_available_at > state_as_of THEN
    RAISE EXCEPTION
      'observation % became available at %, after the state as_of %',
      NEW.obs_id, obs_available_at, state_as_of
      USING ERRCODE = '23514';
  END IF;

  IF obs_quality NOT IN ('valid', 'partial') THEN
    RAISE EXCEPTION
      'observation % has quality_status %, which may not support a state',
      NEW.obs_id, obs_quality
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_macro_domain_state_evidence_guard
  ON uw_scan.macro_domain_state_evidence;
CREATE TRIGGER trg_macro_domain_state_evidence_guard
BEFORE INSERT OR UPDATE OR DELETE ON uw_scan.macro_domain_state_evidence
FOR EACH ROW EXECUTE FUNCTION uw_scan.macro_domain_state_evidence_guard();
