-- 140_research_events.sql — typed event and deterministic-risk ledgers.
--
-- WHAT THIS DELIBERATELY DOES NOT STORE
-- ------------------------------------
-- No generated event facts. Every row here is DERIVED from something Argon
-- already ingested — an SEC filing index row, a statement's filing date, a
-- recorded integrity violation, a revenue breakdown — and carries a pointer back
-- to it. A model may summarise these rows; it may not create one.
--
-- That restriction is why the class list is short. The M6 spec names customer
-- concentration, supplier relationships, backlog, capex guidance, debt maturity,
-- and management guidance as candidate classes. Argon ingests no source that
-- contains them: they live in SEC document TEXT, which is not fetched. Rather
-- than represent them as empty-but-supported, the discovery gate KILLS them, and
-- `research_event_classes` records the kill with its reason so the decision
-- survives the person who made it.
--
-- WHY first_known_at IS SEPARATE FROM occurred_at
-- -----------------------------------------------
-- An event happened on one date and Argon learned of it on another. A single
-- timestamp forces a choice between a replay that sees events before they were
-- knowable and one that dates everything at discovery. Both are wrong in the
-- same way the statement panel was before migration 130, so the two clocks are
-- separate and every historical read predicates on `first_known_at`.
--
-- WHY A RISK FACT IS NUMERIC OR IT IS NOT A RISK FACT
-- ---------------------------------------------------
-- `research_risk_facts` stores a threshold, an observed value, and whether the
-- threshold was breached. A risk expressed only as a sentence cannot be checked,
-- cannot be replayed, and cannot tell a reader whether it got better. Narrative
-- inference is a separate product (M8) and is not permitted to write here.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.research_event_classes (
    event_class   text PRIMARY KEY,
    status        text NOT NULL,
    source_table  text,
    rationale     text NOT NULL,
    measured_rows integer,
    measured_on   date,
    CONSTRAINT research_event_classes_status_check
        CHECK (status IN ('live', 'killed', 'probation'))
);

COMMENT ON TABLE uw_scan.research_event_classes IS
    'The discovery gate, persisted. Each candidate event class is live, on '
    'probation, or KILLED, with the row count that decided it. A killed class '
    'is not a missing feature — it is a measured absence of source, recorded so '
    'the decision outlives whoever made it.';

CREATE TABLE IF NOT EXISTS uw_scan.research_events (
    event_id       bigserial PRIMARY KEY,
    event_class    text NOT NULL REFERENCES uw_scan.research_event_classes(event_class),
    ticker         text NOT NULL,
    occurred_at    date NOT NULL,
    first_known_at date NOT NULL,
    title          text NOT NULL,
    detail_jsonb   jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_kind    text NOT NULL,
    source_ref     text,
    superseded_by  bigint REFERENCES uw_scan.research_events(event_id),
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_events_known_after_occurred
        CHECK (first_known_at >= occurred_at),
    CONSTRAINT research_events_identity_uq
        UNIQUE (event_class, ticker, occurred_at, source_ref)
);

COMMENT ON COLUMN uw_scan.research_events.first_known_at IS
    'When ARGON could know. Never earlier than occurred_at, enforced. A '
    'historical read predicates on THIS, not on occurred_at, or a replay sees '
    'events before they were knowable.';

COMMENT ON COLUMN uw_scan.research_events.superseded_by IS
    'An amendment supersedes its original rather than replacing it. The '
    'predecessor stays readable, which is the whole point of a ledger.';

CREATE INDEX IF NOT EXISTS ix_research_events_ticker
    ON uw_scan.research_events (ticker, first_known_at DESC);

CREATE INDEX IF NOT EXISTS ix_research_events_class
    ON uw_scan.research_events (event_class, first_known_at DESC);

CREATE TABLE IF NOT EXISTS uw_scan.research_risk_facts (
    risk_id        bigserial PRIMARY KEY,
    ticker         text NOT NULL,
    risk_kind      text NOT NULL,
    observed_value numeric,
    threshold      numeric,
    breached       boolean NOT NULL,
    severity       text NOT NULL,
    statement      text NOT NULL,
    invalidates    text,
    source_kind    text NOT NULL,
    detail_jsonb   jsonb NOT NULL DEFAULT '{}'::jsonb,
    as_of          date NOT NULL,
    computed_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_risk_facts_severity_check
        CHECK (severity IN ('info', 'watch', 'material')),
    CONSTRAINT research_risk_facts_uq UNIQUE (ticker, risk_kind, as_of)
);

COMMENT ON TABLE uw_scan.research_risk_facts IS
    'Deterministic risk facts: an observed value against a threshold, plus the '
    'computation the breach would invalidate. A risk expressed only as prose '
    'cannot be checked, replayed, or shown to have improved.';

COMMENT ON COLUMN uw_scan.research_risk_facts.invalidates IS
    'Which computation this breach makes untrustworthy, named so a reader can '
    'go and look. NULL means the fact is descriptive and invalidates nothing.';

CREATE INDEX IF NOT EXISTS ix_research_risk_facts_ticker
    ON uw_scan.research_risk_facts (ticker, as_of DESC);

CREATE INDEX IF NOT EXISTS ix_research_risk_facts_breached
    ON uw_scan.research_risk_facts (breached, severity) WHERE breached;
