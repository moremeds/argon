"""Trade Insights snapshot and AI-analysis queue persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


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
        with self._conn.cursor() as cur:
            cur.execute(delete_sql, (snapshot_id,))
            for c in candidates:
                cur.execute(
                    insert_sql,
                    (
                        snapshot_id,
                        c["idea_id"],
                        ticker.upper(),
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
                    ),
                )
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
        """Latest succeeded row per known provider as a keyed dict.

        Output shape: {"codex": row|None, "claude": row|None}. Model is NOT in
        the key — the latest succeeded row for each provider wins regardless of
        which model produced it (so a model alias rollover doesn't hide the
        most recent result).
        """
        sql = (
            f"SELECT DISTINCT ON (provider) * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s AND prompt_version = %s AND status = 'succeeded' "
            "ORDER BY provider, finished_at DESC NULLS LAST, requested_at DESC"
        )
        out: dict[str, dict[str, Any] | None] = {"codex": None, "claude": None}
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
    ) -> None:
        """Mark a row as succeeded; optionally overwrite `model` with the
        provider's post-hoc canonical model id (e.g. 'opus' alias resolves to
        'claude-opus-4-7'). Resolved_model keeps the cache key correct on
        subsequent reuse lookups."""
        if resolved_model is None:
            sql = (
                f"UPDATE {self._schema}.trade_insight_ai_analyses "
                "SET status = 'succeeded', "
                "outcome_jsonb = %s, "
                "markdown = %s, "
                "error_message = NULL, "
                "finished_at = now() "
                "WHERE analysis_id = %s"
            )
            params: tuple[Any, ...] = (Jsonb(outcome), markdown, analysis_id)
        else:
            sql = (
                f"UPDATE {self._schema}.trade_insight_ai_analyses "
                "SET status = 'succeeded', "
                "outcome_jsonb = %s, "
                "markdown = %s, "
                "model = %s, "
                "error_message = NULL, "
                "finished_at = now() "
                "WHERE analysis_id = %s"
            )
            params = (Jsonb(outcome), markdown, resolved_model, analysis_id)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def fail_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        error_message: str,
    ) -> None:
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            "SET status = 'failed', "
            "error_message = %s, "
            "finished_at = now() "
            "WHERE analysis_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (error_message[:4000], analysis_id))

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
