"""Trade Insights snapshot and AI-analysis queue persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def _trade_insight_candidate_params(
    *,
    snapshot_id: int,
    run_id: int,
    ticker: str,
    candidates: list[dict[str, Any]],
) -> list[tuple[Any, ...]]:
    normalized_ticker = ticker.upper()
    return [
        (
            snapshot_id,
            c["idea_id"],
            normalized_ticker,
            run_id,
            c["structure"],
            c.get("expression_type"),
            c["rank"],
            c["status"],
            c.get("net_credit_debit"),
            c.get("max_profit"),
            c.get("max_loss"),
            c.get("edge_source"),
            list(c.get("risk_flags") or []),
            Jsonb(c.get("legs") or []),
            Jsonb(c),
        )
        for c in candidates
    ]


class _TradeInsightsAiMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_trade_insight_snapshot(
        self,
        *,
        run_id: int,
        ticker: str,
        as_of: datetime | None,
        assembler_version: str,
        input_hash: str,
        payload: dict[str, Any],
    ) -> int:
        header = payload.get("header") or {}
        source_reconciliation = payload.get("source_reconciliation") or {}
        sql = (
            f"INSERT INTO {self._schema}.trade_insight_snapshots "
            "(run_id, ticker, as_of, assembler_version, input_hash, "
            "source_reconciliation_status, confidence_label, data_quality_label, "
            "preferred_idea_id, payload_jsonb) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, assembler_version, input_hash) "
            "DO UPDATE SET payload_jsonb=EXCLUDED.payload_jsonb, "
            "source_reconciliation_status=EXCLUDED.source_reconciliation_status, "
            "confidence_label=EXCLUDED.confidence_label, "
            "data_quality_label=EXCLUDED.data_quality_label, "
            "preferred_idea_id=EXCLUDED.preferred_idea_id "
            "RETURNING snapshot_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    ticker.upper(),
                    as_of,
                    assembler_version,
                    input_hash,
                    source_reconciliation.get("status"),
                    header.get("confidence_label"),
                    header.get("data_quality_label"),
                    header.get("preferred_idea_id"),
                    Jsonb(payload),
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def replace_trade_insight_candidates(
        self,
        *,
        snapshot_id: int,
        run_id: int,
        ticker: str,
        candidates: list[dict[str, Any]],
    ) -> int:
        delete_sql = (
            f"DELETE FROM {self._schema}.trade_insight_candidates "
            "WHERE snapshot_id = %s"
        )
        insert_sql = (
            f"INSERT INTO {self._schema}.trade_insight_candidates "
            "(snapshot_id, idea_id, ticker, run_id, structure, expression_type, rank, "
            "status, net_credit_debit, max_profit, max_loss, edge_source, risk_flags, "
            "legs_jsonb, candidate_jsonb) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        params = _trade_insight_candidate_params(
            snapshot_id=snapshot_id,
            run_id=run_id,
            ticker=ticker,
            candidates=candidates,
        )
        with self._conn.cursor() as cur:
            cur.execute(delete_sql, (snapshot_id,))
            cur.executemany(insert_sql, params)
        return len(candidates)

    def fetch_trade_insight_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_snapshots "
            "WHERE snapshot_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (snapshot_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_latest_trade_insight_snapshot_for_hash(
        self,
        *,
        ticker: str,
        input_hash: str,
        assembler_version: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_snapshots "
            "WHERE ticker = %s AND input_hash = %s AND assembler_version = %s "
            "ORDER BY created_at DESC, snapshot_id DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), input_hash, assembler_version))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_completed_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
        analysis_input_hash: str,
        prompt_version: str,
        model: str,
        provider: str = "codex",
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s "
            "AND analysis_input_hash = %s "
            "AND prompt_version = %s "
            "AND model = %s "
            "AND provider = %s "
            "AND status = 'succeeded' "
            "ORDER BY finished_at DESC NULLS LAST, requested_at DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ticker.upper(),
                    analysis_input_hash,
                    prompt_version,
                    model,
                    provider,
                ),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_reusable_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
        analysis_input_hash: str,
        prompt_version: str,
        model: str,
        provider: str = "codex",
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s "
            "AND analysis_input_hash = %s "
            "AND prompt_version = %s "
            "AND model = %s "
            "AND provider = %s "
            "AND status IN ('queued', 'running', 'succeeded') "
            "ORDER BY "
            "  CASE status WHEN 'succeeded' THEN 0 WHEN 'running' THEN 1 ELSE 2 END, "
            "  finished_at DESC NULLS LAST, "
            "  started_at DESC NULLS LAST, "
            "  requested_at DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ticker.upper(),
                    analysis_input_hash,
                    prompt_version,
                    model,
                    provider,
                ),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_latest_succeeded_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s AND status = 'succeeded' "
            "ORDER BY finished_at DESC NULLS LAST, requested_at DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_latest_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
        prompt_version: str,
        model: str,
        provider: str = "codex",
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s "
            "AND prompt_version = %s "
            "AND model = %s "
            "AND provider = %s "
            "AND status IN ('queued', 'running', 'succeeded') "
            "ORDER BY "
            "  CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, "
            "  started_at DESC NULLS LAST, "
            "  requested_at DESC, "
            "  finished_at DESC NULLS LAST "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), prompt_version, model, provider))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_latest_trade_insight_ai_analyses_per_provider(
        self,
        *,
        ticker: str,
        prompt_version: str,
    ) -> dict[str, dict[str, Any] | None]:
        """Latest terminal-state row per known provider as a keyed dict.

        Output shape: {"codex": row|None, "claude": row|None,
        "deepseek": row|None}. Returns the most recent succeeded OR failed row
        per provider; succeeded wins when both exist at the same finished_at
        (defensive on the rare tie). Failed rows are surfaced so the UI can
        render the error_message instead of the misleading "No analysis yet"
        empty state. Model is NOT in the key — a model alias rollover does
        not hide the most recent result.
        """
        sql = (
            f"SELECT DISTINCT ON (provider) * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s AND prompt_version = %s "
            "AND status IN ('succeeded', 'failed') "
            "ORDER BY provider, finished_at DESC NULLS LAST, "
            "  CASE status WHEN 'succeeded' THEN 0 ELSE 1 END, "
            "  requested_at DESC"
        )
        out: dict[str, dict[str, Any] | None] = {
            "codex": None,
            "claude": None,
            "deepseek": None,
        }
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), prompt_version))
            rows = cur.fetchall()
            cols = [d.name for d in cur.description or []]
            for row in rows:
                rd = dict(zip(cols, row, strict=False))
                provider = rd.get("provider")
                if provider in out:
                    out[provider] = rd
        return out

    def enqueue_trade_insight_ai_analysis(
        self,
        *,
        snapshot_id: int,
        ticker: str,
        run_id: int,
        trade_insights_input_hash: str,
        analysis_input_hash: str,
        analysis_input: dict[str, Any],
        prompt_version: str,
        model: str,
        provider: str = "codex",
    ) -> str:
        sql = (
            f"INSERT INTO {self._schema}.trade_insight_ai_analyses "
            "(snapshot_id, ticker, run_id, trade_insights_input_hash, "
            "analysis_input_hash, analysis_input_jsonb, prompt_version, model, provider, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued') "
            "ON CONFLICT (ticker, analysis_input_hash, prompt_version, model, provider) "
            "WHERE status IN ('queued', 'running') "
            "DO NOTHING "
            "RETURNING analysis_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    snapshot_id,
                    ticker.upper(),
                    run_id,
                    trade_insights_input_hash,
                    analysis_input_hash,
                    Jsonb(analysis_input),
                    prompt_version,
                    model,
                    provider,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    f"SELECT analysis_id FROM {self._schema}.trade_insight_ai_analyses "
                    "WHERE ticker = %s "
                    "AND analysis_input_hash = %s "
                    "AND prompt_version = %s "
                    "AND model = %s "
                    "AND provider = %s "
                    "AND status IN ('queued', 'running') "
                    "ORDER BY started_at DESC NULLS LAST, requested_at DESC "
                    "LIMIT 1",
                    (
                        ticker.upper(),
                        analysis_input_hash,
                        prompt_version,
                        model,
                        provider,
                    ),
                )
                row = cur.fetchone()
        assert row is not None
        return str(row[0])

    def claim_next_trade_insight_ai_analysis(
        self,
        *,
        stale_running_before: datetime | None = None,
        provider: str | None = None,
    ) -> dict[str, Any] | None:
        provider_clause = " AND provider = %s" if provider is not None else ""
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            "SET status = 'running', started_at = now(), finished_at = NULL, error_message = NULL "
            "WHERE analysis_id = ("
            f"  SELECT analysis_id FROM {self._schema}.trade_insight_ai_analyses "
            "  WHERE (status = 'queued' "
            "     OR ("
            "       status = 'running' "
            "       AND %s::timestamptz IS NOT NULL "
            "       AND (started_at IS NULL OR started_at < %s::timestamptz)"
            "     ))"
            f"     {provider_clause} "
            "  ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, requested_at "
            "  FOR UPDATE SKIP LOCKED "
            "  LIMIT 1"
            ") "
            "RETURNING *"
        )
        params: list[Any] = [stale_running_before, stale_running_before]
        if provider is not None:
            params.append(provider)
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def prepare_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        *,
        prompt_text: str,
        prompt_payload: dict[str, Any],
        output_schema: dict[str, Any],
        produced_at: datetime,
    ) -> None:
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            "SET prompt_text = %s, "
            "prompt_payload_jsonb = %s, "
            "output_schema_jsonb = %s, "
            "produced_at = %s "
            "WHERE analysis_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    prompt_text,
                    Jsonb(prompt_payload),
                    Jsonb(output_schema),
                    produced_at,
                    analysis_id,
                ),
            )

    def complete_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        *,
        outcome: dict[str, Any],
        markdown: str,
        resolved_model: str | None = None,
        provider_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark a row as succeeded; optionally overwrite `model` with the
        provider's post-hoc canonical model id (e.g. 'opus' alias resolves to
        'claude-opus-4-7'). Resolved_model keeps the cache key correct on
        subsequent reuse lookups.

        `provider_metadata` carries provider-specific runtime fields
        (DeepSeek: reasoning_content + output_channel + byte sizes; Codex /
        Claude: typically None). Schemaless by design — readers must guard.
        """
        sets = [
            "status = 'succeeded'",
            "outcome_jsonb = %s",
            "markdown = %s",
            "error_message = NULL",
            "finished_at = now()",
        ]
        params: list[Any] = [Jsonb(outcome), markdown]
        if resolved_model is not None:
            sets.append("model = %s")
            params.append(resolved_model)
        if provider_metadata is not None:
            sets.append("provider_metadata_jsonb = %s")
            params.append(Jsonb(provider_metadata))
        params.append(analysis_id)
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            f"SET {', '.join(sets)} "
            "WHERE analysis_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))

    def fail_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        error_message: str,
        *,
        raw_outcome: dict[str, Any] | None = None,
        provider_metadata: dict[str, Any] | None = None,
    ) -> None:
        # Persist the runner's raw output when validation rejected it; NULL
        # otherwise (subprocess crash, timeout, non-JSON, pre-runner error).
        # Lets us diagnose validator rejections without re-running. The
        # provider_metadata mirrors raw_outcome — on a validation failure we
        # want the reasoning trace too so we can see how the model arrived at
        # the rejected output.
        sets = [
            "status = 'failed'",
            "error_message = %s",
            "finished_at = now()",
        ]
        params: list[Any] = [error_message[:4000]]
        if raw_outcome is not None:
            sets.append("raw_outcome_jsonb = %s")
            params.append(Jsonb(raw_outcome))
        if provider_metadata is not None:
            sets.append("provider_metadata_jsonb = %s")
            params.append(Jsonb(provider_metadata))
        params.append(analysis_id)
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            f"SET {', '.join(sets)} "
            "WHERE analysis_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))

    def get_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        ticker: str | None = None,
    ) -> dict[str, Any] | None:
        sql = f"SELECT * FROM {self._schema}.trade_insight_ai_analyses WHERE analysis_id = %s"
        params: tuple[Any, ...]
        if ticker is not None:
            sql += " AND ticker = %s"
            params = (analysis_id, ticker.upper())
        else:
            params = (analysis_id,)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def count_queued_trade_insight_ai_analyses_by_provider(
        self,
        provider: str,
    ) -> int:
        """Pending depth (queued + running) for a single provider's queue.

        Used by /api/health to render the per-provider health block.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM {self._schema}.trade_insight_ai_analyses "
                "WHERE provider = %s AND status IN ('queued', 'running')",
                (provider,),
            )
            return int(cur.fetchone()[0])
