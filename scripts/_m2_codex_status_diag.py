"""Diagnostic for M2: capture what Codex writes for `status_observed` when
given the NOK candidate_set that has tripped the no-whitewashing validator
four times in the past ~10 hours.

This script runs the Codex CLI through the same runner the worker uses,
against the exact analysis_input the worker would build, and prints the
raw best_expressions[*].{idea_id, status_observed, structure} so we can
see what Codex is actually drifting to.

Not committed-to-prod code — kept under scripts/ as a one-off.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.trade_insights_ai import (
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
    trade_insights_ai_output_schema,
)
from uw_scan.worker.jobs.trade_insights_codex_runner import CodexRunner


def main() -> int:
    settings = Settings.from_env()
    target_id = (
        sys.argv[1] if len(sys.argv) > 1 else "0e456571-e896-4967-a85e-63e7d4ef3b2c"
    )
    dsn = settings.db_dsn() if callable(settings.db_dsn) else settings.db_dsn
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT analysis_input_jsonb, ticker FROM uw_scan.trade_insight_ai_analyses "
                "WHERE analysis_id = %s",
                (target_id,),
            )
            row = cur.fetchone()
    if row is None:
        print(f"analysis_id {target_id} not found", file=sys.stderr)
        return 1
    analysis_input = dict(row[0])
    ticker = row[1]
    produced_at = datetime.now(timezone.utc)
    payload = build_trade_insights_ai_prompt_payload(
        analysis_input,
        produced_at=produced_at,
    )
    prompt_text = build_trade_insights_ai_prompt(payload)
    schema = trade_insights_ai_output_schema(strict=True)

    print(f"=== running Codex on {ticker} analysis_id={target_id} ===", file=sys.stderr)
    print(f"prompt length: {len(prompt_text)} chars", file=sys.stderr)

    runner = CodexRunner()
    result = runner.run(
        prompt_text,
        schema,
        model=settings.trade_insights_ai_model.strip(),
        timeout_seconds=settings.trade_insights_ai_timeout_seconds,
        max_output_bytes=settings.trade_insights_ai_max_output_bytes,
    )
    outcome = result.outcome
    print(f"=== resolved_model: {result.resolved_model} ===", file=sys.stderr)

    candidates = analysis_input.get("candidate_structures", [])
    cand_status_by_id = {c.get("idea_id"): c.get("status") for c in candidates}

    print("=== candidate_set status (from input) ===")
    for c in candidates:
        print(f"  {c.get('idea_id')}: {c.get('status')!r}")

    print("=== best_expressions status_observed (from Codex output) ===")
    for be in outcome.get("best_expressions", []):
        iid = be.get("idea_id")
        print(
            f"  {iid}: status_observed={be.get('status_observed')!r} "
            f"(candidate.status={cand_status_by_id.get(iid)!r}) "
            f"structure={be.get('structure')!r}"
        )

    print("=== preferred_expression ===")
    pe = outcome.get("preferred_expression")
    if pe:
        print(
            f"  {pe.get('idea_id')}: status_observed={pe.get('status_observed')!r} "
            f"(candidate.status={cand_status_by_id.get(pe.get('idea_id'))!r}) "
            f"structure={pe.get('structure')!r}"
        )

    print("=== full outcome dumped to /tmp/m2_codex_diag.json ===")
    with open("/tmp/m2_codex_diag.json", "w") as f:
        json.dump(outcome, f, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
