-- 128_macro_state_dependencies.sql — one state standing on another, recorded as a fact.
--
-- MC2 landed macro_domain_states and macro_domain_state_evidence (state -> observation).
-- Part B adds the edge that milestone did not need: state -> STATE. USD is a transmission
-- domain and gold reads three upstream answers, and both must reference those answers
-- rather than re-reading their inputs. Without this table the reference would live only
-- inside inputs_hash -- present in the identity, invisible in the record, and impossible
-- to traverse.
--
-- Why a separate table rather than a column on macro_domain_states: a downstream state
-- references SEVERAL upstreams with DIFFERENT causal roles, and the role is the whole
-- point. "USD consulted policy_rates as policy_actual" and "gold consulted usd as curve"
-- are different edges between the same kinds of node.
--
-- Additive only. Nothing in 125 is altered and no legacy gold or rates table is touched.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_domain_state_dependencies (
  downstream_state_id BIGINT NOT NULL
    REFERENCES uw_scan.macro_domain_states (state_id) ON DELETE RESTRICT,
  upstream_state_id   BIGINT NOT NULL
    REFERENCES uw_scan.macro_domain_states (state_id) ON DELETE RESTRICT,
  -- The same vocabulary as macro_domain_state_evidence, because a role means the same
  -- thing whether the thing playing it is an observation or another domain's answer.
  -- A second, shorter list here would be the first place the two drift.
  causal_role         TEXT   NOT NULL
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
  ordinal             INTEGER NOT NULL CHECK (ordinal >= 0),
  -- A state cannot stand on itself. Cheap to state, and the only cycle a single edge
  -- can express; longer cycles are refused by the writer, which knows the domain graph.
  CHECK (downstream_state_id <> upstream_state_id),
  PRIMARY KEY (downstream_state_id, upstream_state_id, causal_role),
  -- An order that repeats itself is not an order.
  UNIQUE (downstream_state_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_macro_state_deps_upstream
  ON uw_scan.macro_domain_state_dependencies (upstream_state_id);

COMMENT ON TABLE uw_scan.macro_domain_state_dependencies IS
  'Typed edges from a downstream state to the upstream ANSWERS it consumed, never their inputs.';
COMMENT ON COLUMN uw_scan.macro_domain_state_dependencies.causal_role IS
  'What the upstream state DID in the downstream one; same vocabulary as state evidence.';
COMMENT ON COLUMN uw_scan.macro_domain_state_dependencies.upstream_state_id IS
  'Must resolve to a state whose as_of is at or before the downstream as_of. Enforced by '
  'the writer rather than a CHECK: the rule spans two rows, and a trigger that reads '
  'macro_domain_states on every insert would fire on the hot path of every state write '
  'to catch a violation only Argon itself could commit.';
