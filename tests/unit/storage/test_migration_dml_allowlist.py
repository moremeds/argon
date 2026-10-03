"""Migrations may not rewrite or delete data unless the file is reviewed below.

The API self-migrates on every boot (``migrate_runner`` re-runs EVERY file, there
is no tracking table), so an ``UPDATE`` / ``DELETE`` / ``ON CONFLICT DO UPDATE`` in
a migration is not a one-off backfill: it re-executes on every deploy, against
data that operators and jobs wrote after the migration first ran. That is how the
watchlist seed migrations kept undoing operator edits (see 006_seed_watchlist.sql).

Data DML in a migration must be insert-only (``ON CONFLICT DO NOTHING``). A file
that genuinely needs an UPDATE/DELETE must be listed here with the reason replay
is harmless. Both dicts are ratchets: a listed file that no longer contains DML
fails the test, so the lists only shrink.

Pure file parsing — no DB. Statement splitting reuses ``split_sql_statements`` so
detection sees exactly the statements the runner executes.
"""

from __future__ import annotations

import re

from uw_scan.storage.migrate_runner import (
    MIGRATIONS_DIR,
    discover_migrations,
    split_sql_statements,
)

# Replay audited 2026-10-03: re-running cannot override operator or runtime data.
REPLAY_HARMLESS: dict[str, str] = {
    "018_trade_insights_ai_active_reuse.sql": (
        "dedupes active rows before a partial UNIQUE index; the index keeps the "
        "predicate empty forever after"
    ),
    "024_rescan_queue_dedupe.sql": (
        "dedupes active jobs before a partial UNIQUE index; the index keeps the "
        "predicate empty forever after"
    ),
    "025_jobs_claim_token.sql": (
        "fills a NULL claim_token on running jobs; the claim path always sets one "
        "and requeue moves the row to queued, so nothing matches at runtime"
    ),
    "030_matrix_state_vrp_sign_flip.sql": (
        "NULL -> 'insufficient_history'/0 fill equals the read path's own default "
        "for NULL (storage/matrix_state.py _vrp_sign_flip_status_from_db)"
    ),
    "050_cri_composite_version_backfill.sql": (
        "stamps composite_version only where missing; every CRI writer (run and "
        "run_live via cri_scoring) always stamps it"
    ),
    "052_rates_tables.sql": (
        "dedupes on (series_id, obs_date, source) before that PK is enforced; the "
        "PK keeps the predicate empty forever after"
    ),
    "059_regime_backtest_research_scope.sql": (
        "NULL-only fills derived from the same row's summary JSON; the writer "
        "always sets run_scope/composite_method"
    ),
    "067_trade_insight_analysis_kind.sql": (
        "re-derives analysis_kind='blast' from prompt_version LIKE 'trade-blast%', "
        "the same mapping the writer uses"
    ),
    "076_skew_verdict_drop_regime.sql": (
        "DELETE runs inside a DO block guarded by the existence of the column it "
        "drops; after the first run the guard is false"
    ),
    "129_fundamental_scores_drop_future_as_of.sql": (
        "evicts fully-derived score rows dated in the future; re-deleting one is the "
        "correct action (see the file's own header)"
    ),
}

# Replay CAN clobber data written after the migration ran. Not fixed here (tracked
# follow-up); listed so the test stays green without hiding them.
KNOWN_HARMFUL_UNFIXED: dict[str, str] = {
    "021_trade_insights_ai_v2_prompt_rows.sql": (
        "fails every queued/running AI analysis whose prompt_version <> "
        "'trade-insights-ai-v2'; the live PROMPT_VERSION is v5.3, so each boot "
        "kills all in-flight analyses"
    ),
    "023_backfill_flow_alerts_daily_rollup.sql": (
        "recomputes every flow_alerts_daily_rollup row from all flow_events and "
        "DO UPDATEs over the runtime writer's values (hardcoded 100 limit vs "
        "alert_limit, per-event vs per-run trade_date)"
    ),
    "047_gold_posture_row_status.sql": (
        "invalidates active posture rows dated after the latest GLD_CLOSE and "
        "earlier same-day rows lacking GLD history; changes point-in-time reads"
    ),
    "048_gold_cb_flow_replay_invalidation.sql": (
        "invalidates earlier same-day active posture rows lacking CB fields; "
        "fetch_gold_posture_as_of picks the earliest active row, so PIT reads change"
    ),
}

_DML = re.compile(r"\b(UPDATE|DELETE\s+FROM|TRUNCATE)\b", re.IGNORECASE)
# Definitions (bodies not executed at migration time) and privilege grants.
_DEFINITION = re.compile(
    r"^\s*CREATE\s+(OR\s+REPLACE\s+)?(FUNCTION|PROCEDURE|TRIGGER|RULE)\b"
    r"|^\s*(GRANT|REVOKE)\b",
    re.IGNORECASE,
)
# Trigger timing / FK actions that contain the word UPDATE but are not DML.
_NOT_DML = re.compile(
    r"\b(BEFORE|AFTER|INSTEAD\s+OF|ON|FOR|OR)\s+UPDATE\b", re.IGNORECASE
)


def _strip_comments_and_strings(sql: str) -> str:
    """Drop ``--``/``/* */`` comments and blank single-quoted literals.

    Dollar-quoted bodies are kept: a ``DO $$ ... $$`` block executes at migration
    time, so DML inside it counts.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
            continue
        if sql[i] == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append("''")
            i = j + 1
            continue
        out.append(sql[i])
        i += 1
    return "".join(out)


def _dml_statements(sql: str) -> list[str]:
    hits: list[str] = []
    for stmt in split_sql_statements(sql):
        text = _strip_comments_and_strings(stmt)
        if _DEFINITION.match(text):
            continue
        if _DML.search(_NOT_DML.sub(" ", text)):
            hits.append(" ".join(text.split())[:120])
    return hits


def _files_with_dml() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in discover_migrations():
        hits = _dml_statements(path.read_text())
        if hits:
            found[path.name] = hits
    return found


def test_no_unreviewed_update_or_delete_in_migrations():
    reviewed = REPLAY_HARMLESS.keys() | KNOWN_HARMFUL_UNFIXED.keys()
    unreviewed = {k: v for k, v in _files_with_dml().items() if k not in reviewed}
    assert not unreviewed, (
        "Migration(s) contain UPDATE / DELETE / TRUNCATE / ON CONFLICT DO UPDATE. "
        "Every migration re-runs on every API boot, so this DML re-applies over "
        "data written later. Make it insert-only (ON CONFLICT DO NOTHING), or — "
        "only if replay provably cannot override operator/runtime data — add the "
        f"file to REPLAY_HARMLESS with the reason: {unreviewed}"
    )


def test_allowlists_are_ratchets():
    with_dml = _files_with_dml().keys()
    stale = (REPLAY_HARMLESS.keys() | KNOWN_HARMFUL_UNFIXED.keys()) - with_dml
    assert not stale, (
        f"Listed file(s) no longer contain DML (or were removed); delete the entry: {sorted(stale)}"
    )
    overlap = REPLAY_HARMLESS.keys() & KNOWN_HARMFUL_UNFIXED.keys()
    assert not overlap, (
        f"File(s) listed as both harmless and harmful: {sorted(overlap)}"
    )


def test_detector_sees_the_bug_shapes():
    """Guard the detector itself against the exact shapes that caused the bug."""
    assert _dml_statements(
        "INSERT INTO w (t) VALUES ('X') ON CONFLICT (t) DO UPDATE SET removed_at = NULL;"
    )
    assert _dml_statements("UPDATE w SET removed_at = NOW() WHERE t = 'DIS';")
    assert _dml_statements("DO $$ BEGIN DELETE FROM w; END $$;")
    assert not _dml_statements(
        "INSERT INTO w (t) VALUES ('X') ON CONFLICT (t) DO NOTHING;"
    )
    assert not _dml_statements(
        "-- UPDATE w SET x = 1\nCREATE TABLE IF NOT EXISTS w (t TEXT);"
    )
    assert not _dml_statements("COMMENT ON TABLE w IS 'do not UPDATE this';")
    assert not _dml_statements(
        "CREATE OR REPLACE FUNCTION f() RETURNS trigger AS $$ BEGIN "
        "UPDATE w SET x = 1; RETURN NEW; END $$ LANGUAGE plpgsql;"
    )
    assert not _dml_statements(
        "CREATE TRIGGER t BEFORE UPDATE OR DELETE ON w FOR EACH ROW EXECUTE FUNCTION f();"
    )
    assert not _dml_statements(
        "CREATE TABLE c (t TEXT REFERENCES w(t) ON DELETE CASCADE ON UPDATE CASCADE);"
    )
    assert not _dml_statements("GRANT SELECT, INSERT, UPDATE ON w TO argon_app;")


def test_migrations_dir_is_populated():
    assert len(discover_migrations(MIGRATIONS_DIR)) > 100
