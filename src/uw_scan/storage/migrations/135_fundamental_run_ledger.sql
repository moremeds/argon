-- 135_fundamental_run_ledger.sql — what was asked, under which contract, and
-- what came back. The control plane every later product reuses.
--
-- WHY A LEDGER AND NOT JUST THE RESULT TABLES
-- -------------------------------------------
-- `fundamental_scores` records an ANSWER. It cannot record the QUESTION: which
-- universe, at which as-of, under which evidence policy, with which method
-- versions, and what the run was allowed to spend. Two runs producing the same
-- rows for different reasons are indistinguishable, and a run that produced
-- nothing leaves no trace at all — the most important case, because "the panel
-- was empty" and "the job never ran" look identical afterwards.
--
-- The report product (M7) needs exactly this row to say "this report was
-- assembled from run N, whose scope was X" and to diff against a prior version.
-- Building it later would mean retrofitting scope onto results that never
-- carried it.
--
-- IDEMPOTENCY IS A REQUEST HASH, NOT A TIMESTAMP
-- ----------------------------------------------
-- `request_hash` covers scope + as_of + evidence policy + method versions. Two
-- identical requests are the SAME logical run and reuse its result rather than
-- recomputing — which is what makes a report cheap to re-open. A run whose
-- request differs in any of those fields is a different run, even one second
-- later, because any of them changes what the answer means.
--
-- ACTIVE-RUN UNIQUENESS
-- ---------------------
-- At most one non-terminal run per request_hash, enforced by a partial unique
-- index. Without it, two workers claiming the same request both compute, both
-- write, and the ledger reports two runs where the operator asked once.
--
-- STAGES ARE ROWS, NOT A STATUS COLUMN
-- ------------------------------------
-- A run passes through panel -> features -> scoring -> anchors. A single status
-- column can say "failed" but not "failed at anchors after scoring succeeded",
-- which is the difference between re-running everything and re-running one
-- stage. Stage rows also carry the input/output hashes that let a later run
-- skip a stage whose inputs did not move.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.fundamental_runs (
    run_id          bigserial PRIMARY KEY,
    request_hash    text NOT NULL,
    scope_kind      text NOT NULL,
    scope_jsonb     jsonb NOT NULL DEFAULT '{}'::jsonb,
    as_of           date,
    evidence_policy text NOT NULL,
    engine_version  text,
    status          text NOT NULL DEFAULT 'queued',
    mode            text NOT NULL DEFAULT 'compute',
    counters_jsonb  jsonb NOT NULL DEFAULT '{}'::jsonb,
    error           text,
    requested_at    timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    heartbeat_at    timestamptz,
    CONSTRAINT fundamental_runs_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT fundamental_runs_mode_check
        CHECK (mode IN ('compute', 'reuse', 'refresh')),
    CONSTRAINT fundamental_runs_scope_check
        CHECK (scope_kind IN ('universe', 'tickers', 'chain', 'company'))
);

COMMENT ON TABLE uw_scan.fundamental_runs IS
    'What was asked of the fundamental engine and under which contract: scope, '
    'as-of, evidence policy, method version, mode, and the counters that came '
    'back. fundamental_scores records the ANSWER; this records the QUESTION, '
    'without which a run that produced nothing is indistinguishable from a job '
    'that never ran.';

COMMENT ON COLUMN uw_scan.fundamental_runs.request_hash IS
    'Identity of the REQUEST: scope + as_of + evidence_policy + engine_version. '
    'Two identical requests are one logical run and the second reuses the first, '
    'which is what makes re-opening a report cheap.';

COMMENT ON COLUMN uw_scan.fundamental_runs.mode IS
    'compute = do the work. reuse = a prior run''s result answered it. '
    'refresh = recompute even though a compatible result exists.';

COMMENT ON COLUMN uw_scan.fundamental_runs.heartbeat_at IS
    'Liveness. A ''running'' row whose heartbeat has aged out is a corpse, not '
    'progress — the same distinction the data-gap healer''s reaper draws.';

-- At most one non-terminal run per request. Two workers claiming one request
-- would both compute and both write, and the ledger would report two runs where
-- the operator asked once.
CREATE UNIQUE INDEX IF NOT EXISTS fundamental_runs_active_uq
    ON uw_scan.fundamental_runs (request_hash)
    WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS ix_fundamental_runs_status
    ON uw_scan.fundamental_runs (status, requested_at DESC);

CREATE INDEX IF NOT EXISTS ix_fundamental_runs_request
    ON uw_scan.fundamental_runs (request_hash, requested_at DESC);

CREATE TABLE IF NOT EXISTS uw_scan.fundamental_run_stages (
    stage_id      bigserial PRIMARY KEY,
    run_id        bigint NOT NULL
                  REFERENCES uw_scan.fundamental_runs(run_id) ON DELETE CASCADE,
    stage         text NOT NULL,
    status        text NOT NULL DEFAULT 'queued',
    attempt       integer NOT NULL DEFAULT 1,
    inputs_hash   text,
    outputs_hash  text,
    counters_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    error         text,
    started_at    timestamptz,
    finished_at   timestamptz,
    CONSTRAINT fundamental_run_stages_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')),
    CONSTRAINT fundamental_run_stages_uq UNIQUE (run_id, stage, attempt)
);

COMMENT ON TABLE uw_scan.fundamental_run_stages IS
    'Per-stage state for one run (panel/features/scoring/anchors). A single '
    'status column on the run can say "failed" but not "failed at anchors after '
    'scoring succeeded" — the difference between re-running everything and '
    're-running one stage. inputs_hash lets a later run SKIP a stage whose '
    'inputs did not move.';

CREATE INDEX IF NOT EXISTS ix_fundamental_run_stages_run
    ON uw_scan.fundamental_run_stages (run_id, stage);
