"""Run the fundamental engine under the ledger — the control plane (M2.4).

`fundamental_refresh` chains routing -> scoring -> anchors and returns counters
to a log line. That is fine for a nightly cron and useless to every product that
has to say WHICH computation an answer came from. This wraps the same chain in a
run row: the scope asked for, the as-of, the evidence policy, the engine version,
per-stage state, and the counters — persisted, addressable, and diffable.

M7's report product reads a `run_id` and nothing else. That only works if the run
recorded its own question, which is why this exists before the report does rather
than being retrofitted onto results that never carried scope.

REUSE IS EXACT OR IT IS NOT REUSE
--------------------------------
`mode='reuse'` matches on `request_hash` — scope, as-of, policy, engine — and
nothing softer. A "close enough" match would answer the operator's question with
someone else's, silently, which is worse than recomputing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.fundamentals.observation_time import EvidencePolicy
from uw_scan.storage.fundamental_runs import (
    MODE_COMPUTE,
    MODE_REUSE,
    STAGE_ANCHORS,
    STAGE_PANEL,
    STAGE_SCORING,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    FundamentalRunsRepository,
)
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.worker.jobs.fundamental_anchors import (
    fundamental_anchors,
    seed_company_types,
)
from uw_scan.worker.jobs.fundamental_scoring import fundamental_scoring

log = logging.getLogger(__name__)

#: What the ledger stores when a caller asks for the current panel. Not an
#: `EvidencePolicy` member for the reason that enum documents: adding it would
#: hand a replay a way to request exactly the rows that must fail closed.
CURRENT_VINTAGE = "current_vintage"


def fundamental_run(
    *,
    conn: psycopg.Connection,
    settings: Settings,
    scope_kind: str = "universe",
    tickers: Sequence[str] | None = None,
    tier: str = "ranked",
    as_of: date | None = None,
    evidence_policy: EvidencePolicy | str | None = None,
    engine_version: str | None = None,
    mode: str = MODE_COMPUTE,
    skip_anchors: bool = False,
) -> dict[str, Any]:
    """Execute (or reuse) one ledgered fundamental run. Returns the run record.

    Never raises for a stage failure: the run is marked `failed` with the error
    on the stage that caused it, because a traceback that escapes here loses the
    partial state a retry needs.
    """
    schema = settings.db_schema
    runs = FundamentalRunsRepository(conn, schema=schema)
    scores = FundamentalScoresRepository(conn, schema=schema)

    engine = engine_version or scores.active_version()
    policy_name = (
        EvidencePolicy(evidence_policy).value
        if evidence_policy is not None
        else CURRENT_VINTAGE
    )
    scope = {"tier": tier} if not tickers else {"tickers": sorted(t.upper() for t in tickers)}

    if mode == MODE_REUSE:
        prior = runs.latest_succeeded(
            scope_kind=scope_kind,
            scope=scope,
            evidence_policy=policy_name,
            as_of=as_of,
            engine_version=engine,
        )
        if prior is not None:
            log.info("fundamental_run: reusing run %s", prior["run_id"])
            return prior
        # Falling through to compute is deliberate. A reuse request with no
        # prior run is not an error, it is the first time the question was asked.

    run_id, created = runs.enqueue(
        scope_kind=scope_kind,
        scope=scope,
        evidence_policy=policy_name,
        as_of=as_of,
        engine_version=engine,
        mode=mode,
    )
    if not created:
        log.info("fundamental_run: run %s already active for this request", run_id)
        return runs.get(run_id)

    runs.start(run_id)
    names = list(tickers) if tickers else None

    try:
        # --- routing: company_type must be settled before anchors read it ---
        sid = runs.stage_start(run_id, STAGE_PANEL)
        routing = seed_company_types(conn, schema=schema)
        runs.stage_finish(sid, status=STATUS_SUCCEEDED, counters=routing)
        runs.heartbeat(run_id)

        # --- scoring: panel + features + cross-section, under the policy ---
        sid = runs.stage_start(run_id, STAGE_SCORING, inputs_hash=engine)
        scoring = fundamental_scoring(
            conn=conn,
            schema=schema,
            tier=tier,
            tickers=names,
            knowledge_cutoff=as_of,
            evidence_policy=evidence_policy,
            engine_version=engine,
        )
        runs.stage_finish(sid, status=STATUS_SUCCEEDED, counters=scoring)
        runs.heartbeat(run_id)

        # --- anchors: own-history valuation bands ---
        anchors: dict[str, Any] = {}
        sid = runs.stage_start(run_id, STAGE_ANCHORS)
        if skip_anchors:
            runs.stage_finish(
                sid, status="skipped", counters={"reason": "skip_anchors requested"}
            )
        else:
            anchors = fundamental_anchors(
                conn=conn,
                lake_root=settings.lake_credit_etf_root,
                silver_root=settings.market_warehouse_lake_root
                / "silver/asset_class=equity",
                fx_root=settings.lake_fx_root,
                schema=schema,
                tickers=names,
                as_of=as_of,
            )
            runs.stage_finish(sid, status=STATUS_SUCCEEDED, counters=anchors)

        runs.finish(
            run_id,
            status=STATUS_SUCCEEDED,
            counters={"routing": routing, "scoring": scoring, "anchors": anchors},
        )
    except Exception as exc:  # noqa: BLE001 - the run row IS the error report
        log.exception("fundamental_run %s failed", run_id)
        runs.stage_finish(sid, status=STATUS_FAILED, error=repr(exc))
        runs.finish(run_id, status=STATUS_FAILED, error=repr(exc))

    return runs.get(run_id)
