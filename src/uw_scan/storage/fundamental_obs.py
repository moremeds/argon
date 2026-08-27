"""Tier-1 fundamental observations and the two-tier universe (migration 114).

Standalone repository, never a `Repository` mixin — new persistence domains get
their own module from method one (storage split rule, CLAUDE.md).

**Every writer here commits.** The known failure in this area is a
research-layer refresh that ran, logged success and never committed a row, so
the caller-commits convention is not used in this module.

The write path is insert-or-touch on `content_hash`: an unchanged refetch bumps
`last_seen_at` and writes no fact; a restatement hashes differently and lands as
a new immutable row beside the old one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from uw_scan.fundamentals.statements import Violation
from uw_scan.storage.fundamental_observation_panels import current_statement_panel

# One statement row is ~1 KB of JSONB; 2,000 keeps a chunk comfortably under the
# parameter ceiling while still amortising round-trips over a 60k-row ingest.
CHUNK = 2000


class FundamentalObsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- universe ----------------

    def list_universe(self, tier: str) -> list[str]:
        """Active tickers in a tier, stable order.

        Returns [] for an unknown or fully-removed tier rather than raising: the
        ingest job gates on this being non-empty, so an unseeded tier must read
        as "nothing to do" and spend zero UW calls, not as a crash.
        """
        sql = f"""
            SELECT ticker FROM {self._schema}.fundamental_universe
             WHERE tier = %s AND removed_at IS NULL
             ORDER BY ticker
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (tier,))
            return [r[0] for r in cur.fetchall()]

    def seed_universe(
        self, tier: str, rows: Sequence[tuple[str, str | None, str | None]]
    ) -> int:
        """Upsert (ticker, layer, reason) members of a tier. Idempotent.

        Re-seeding un-removes a name deliberately: the seed list is the intended
        membership, so a ticker present in it should be active regardless of a
        prior removal.
        """
        sql = f"""
            INSERT INTO {self._schema}.fundamental_universe
                        (tier, ticker, layer, reason)
                 VALUES (%s, %s, %s, %s)
            ON CONFLICT (tier, ticker) DO UPDATE
                    SET layer = EXCLUDED.layer,
                        reason = EXCLUDED.reason,
                        removed_at = NULL
        """
        with self.conn.cursor() as cur:
            cur.executemany(
                sql, [(tier, t, layer, reason) for t, layer, reason in rows]
            )
        self.conn.commit()
        return len(rows)

    # ---------------- observations ----------------

    def record_statements(self, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """Insert-or-touch a batch of observations. Returns (inserted, touched).

        Counted by table cardinality either side rather than by `rowcount`,
        because `ON CONFLICT DO UPDATE` reports conflicts and inserts alike and
        would make an all-duplicate rerun look like a full ingest.

        `filing_published_at` fills but never revises. UW publishes a statement before
        it publishes the filing date, and `content_hash` excludes the date by design, so
        the later re-pull that carries it collides here — a plain touch discarded it
        permanently. COALESCE keeps the existing value when there is one: the column is
        a fact about an immutable observation, and letting a re-pull rewrite it would
        make it mean "whatever the provider last said", which no point-in-time consumer
        can use. A provider that changes a date it already gave is therefore ignored,
        deliberately and silently — no such case has been observed.
        """
        batch = list(rows)
        if not batch:
            return (0, 0)

        sql = f"""
            INSERT INTO {self._schema}.fundamental_statement_obs
                        (source, ticker, period_end, period_type, statement,
                         content_hash, provider_record_id, filing_accession,
                         filing_published_at, raw_jsonb, field_map_version)
                 VALUES (%(source)s, %(ticker)s, %(period_end)s, %(period_type)s,
                         %(statement)s, %(content_hash)s, %(provider_record_id)s,
                         %(filing_accession)s, %(filing_published_at)s,
                         %(raw_jsonb)s, %(field_map_version)s)
            ON CONFLICT (source, ticker, period_end, period_type, statement, content_hash)
            DO UPDATE SET
                last_seen_at = now(),
                filing_published_at = COALESCE(
                    {self._schema}.fundamental_statement_obs.filing_published_at,
                    EXCLUDED.filing_published_at
                )
        """
        before = self._count()
        with self.conn.cursor() as cur:
            for i in range(0, len(batch), CHUNK):
                cur.executemany(
                    sql,
                    [
                        {**row, "raw_jsonb": Jsonb(row["raw_jsonb"])}
                        for row in batch[i : i + CHUNK]
                    ],
                )
        self.conn.commit()
        inserted = self._count() - before
        return (inserted, len(batch) - inserted)

    def _count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM {self._schema}.fundamental_statement_obs"
            )
            return int(cur.fetchone()[0])

    def obs_id(
        self,
        *,
        source: str,
        ticker: str,
        period_end: date,
        period_type: str,
        statement: str,
        content_hash: str,
    ) -> int | None:
        """Resolve an observation's surrogate id from its content identity."""
        sql = f"""
            SELECT obs_id FROM {self._schema}.fundamental_statement_obs
             WHERE source = %s AND ticker = %s AND period_end = %s
               AND period_type = %s AND statement = %s AND content_hash = %s
        """
        with self.conn.cursor() as cur:
            cur.execute(
                sql, (source, ticker, period_end, period_type, statement, content_hash)
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def record_violations(self, obs_id: int, violations: Sequence[Violation]) -> int:
        """Attach integrity failures to one observation. Idempotent per check.

        `DO NOTHING` rather than `DO UPDATE`: a violation is a verdict about an
        immutable payload, so re-running the same check over the same row cannot
        legitimately produce a different answer, and the original `detected_at`
        is the more useful fact to keep.
        """
        if not violations:
            return 0
        # RETURNING + one multi-row INSERT, so the count is what was actually
        # written. Returning len(violations) would overstate on every replay,
        # since ON CONFLICT DO NOTHING inserts nothing — and a counter that
        # overstates is worse than none: a backfill would report healthy progress
        # while writing zero rows.
        values = ", ".join(["(%s, %s, %s, %s, %s)"] * len(violations))
        params: list[Any] = []
        for v in violations:
            params += [
                obs_id,
                v.check_name,
                v.field,
                v.observed_value,
                Jsonb(v.detail) if v.detail else None,
            ]
        sql = f"""
            INSERT INTO {self._schema}.fundamental_obs_violations
                        (obs_id, check_name, field, observed_value, detail_jsonb)
                 VALUES {values}
            ON CONFLICT (obs_id, check_name) DO NOTHING
              RETURNING violation_id
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            written = len(cur.fetchall())
        self.conn.commit()
        return written

    # ---------------- reads ----------------

    def violated_fields(self, obs_ids: Sequence[int]) -> dict[str, list[str]]:
        """field -> check names, for the observations a result was computed from.

        This is how a rendering surface refuses to show a figure we do not
        believe. The alternative — nulling the value in `features.py` — would
        change the validated math and break the reproducibility of every
        published result, so the raw feature stays as computed and the DISPLAY
        layer suppresses it. Research reproducibility and an honest card are both
        preserved; only one of them would survive editing the feature.
        """
        if not obs_ids:
            return {}
        sql = f"""
            SELECT field, check_name
              FROM {self._schema}.fundamental_obs_violations
             WHERE obs_id = ANY(%s) AND field IS NOT NULL
        """
        out: dict[str, list[str]] = {}
        with self.conn.cursor() as cur:
            cur.execute(sql, (list(obs_ids),))
            for field, check in cur.fetchall():
                out.setdefault(field, []).append(check)
        return out

    def violations_by_obs(
        self, obs_ids: Sequence[int]
    ) -> dict[int, dict[str, list[str]]]:
        """obs_id -> {field -> check names}, for a whole series in one query.

        `violated_fields` aggregates across observations, which is right for a
        single point in time and wrong for a chart: a series can be believable in
        most quarters and not in others, and collapsing them would blank an
        entire line because one 2019 row was bad.
        """
        if not obs_ids:
            return {}
        sql = f"""
            SELECT obs_id, field, check_name
              FROM {self._schema}.fundamental_obs_violations
             WHERE obs_id = ANY(%s) AND field IS NOT NULL
        """
        out: dict[int, dict[str, list[str]]] = {}
        with self.conn.cursor() as cur:
            cur.execute(sql, (list(obs_ids),))
            for obs_id, field, check in cur.fetchall():
                out.setdefault(obs_id, {}).setdefault(field, []).append(check)
        return out

    def recheck_violations(self, batch: int = 5000) -> tuple[int, int]:
        """Re-run the integrity checks over every stored payload. (scanned, new).

        Needed because checks are added AFTER rows land — the payloads are
        immutable, so a new check must be applied retroactively or it only ever
        sees future ingests. Idempotent: `(obs_id, check_name)` already handles
        re-recording.
        """
        from uw_scan.fundamentals.statements import check_violations

        scanned = new = 0
        offset = 0
        while True:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""SELECT obs_id, statement, raw_jsonb
                          FROM {self._schema}.fundamental_statement_obs
                         ORDER BY obs_id LIMIT %s OFFSET %s""",
                    (batch, offset),
                )
                rows = cur.fetchall()
            if not rows:
                return (scanned, new)
            for obs_id, statement, payload in rows:
                scanned += 1
                violations = check_violations(statement, payload)
                if violations:
                    new += self.record_violations(obs_id, violations)
            offset += batch

    def worst_ni_offenders(self, limit: int = 10) -> list[dict[str, Any]]:
        """Tickers with the most net-income cross-statement violations, worst first.

        Feeds the desk limits block (P3) by NAME — a ticker whose income and
        cash-flow statements disagree on net income is named specifically
        rather than folded into an aggregate "N violations" count nobody can
        act on.
        """
        sql = f"""
            SELECT o.ticker, count(*) AS violation_count
              FROM {self._schema}.fundamental_obs_violations v
              JOIN {self._schema}.fundamental_statement_obs o USING (obs_id)
             WHERE v.check_name = 'net_income_disagrees_across_statements'
             GROUP BY o.ticker
             ORDER BY violation_count DESC, o.ticker
             LIMIT %s
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [
                {"ticker": r[0], "violation_count": int(r[1])} for r in cur.fetchall()
            ]

    def statement_panel(
        self, tickers: Sequence[str] | None = None, period_type: str = "quarterly"
    ) -> dict[str, dict[str, Any]]:
        """Compatibility alias for `current_statement_panel` — TODAY's view.

        The implementation moved to `storage/fundamental_observation_panels.py`
        when the historical reader was added, because this name does not say
        WHICH question it answers and callers had begun using it for both. It
        answers "what does Argon believe now": newest accepted version per
        identity, selected by `obs_id DESC`.

        That is the wrong answer to "what was knowable at time T", because it
        applies no cutoff: it returns today's panel whatever T is. (The `obs_id`
        sort is not itself the defect — it is monotonic with capture time by
        construction. The absence of a cutoff is.) Historical callers must use
        `statement_panel_as_of` with an explicit evidence policy.

        Kept rather than removed so this PR does not rewrite every current-page
        caller; new code should call `current_statement_panel` directly.
        """
        return current_statement_panel(
            self.conn, tickers, period_type, schema=self._schema
        )

    def coverage(self, tier: str) -> list[dict[str, Any]]:
        """Per-ticker ingest coverage for the tier — what actually landed.

        The point of reporting this per ticker rather than as a total is that a
        total hides the shape that matters: 245 names at 80 quarters and 200
        names at 98 quarters give the same row count and very different panels.
        """
        sql = f"""
            SELECT u.ticker,
                   count(o.obs_id)                    AS rows,
                   count(DISTINCT o.period_end)       AS periods,
                   min(o.period_end)                  AS first_period,
                   max(o.period_end)                  AS last_period,
                   count(*) FILTER (WHERE o.filing_published_at IS NOT NULL) AS with_filing_date
              FROM {self._schema}.fundamental_universe u
              LEFT JOIN {self._schema}.fundamental_statement_obs o
                     ON o.ticker = u.ticker
             WHERE u.tier = %s AND u.removed_at IS NULL
             GROUP BY u.ticker
             ORDER BY u.ticker
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (tier,))
            return [
                {
                    "ticker": r[0],
                    "rows": r[1],
                    "periods": r[2],
                    "first_period": r[3],
                    "last_period": r[4],
                    "with_filing_date": r[5],
                }
                for r in cur.fetchall()
            ]

    def statement_identities(
        self,
        tickers: Sequence[str],
        *,
        exclude_claim_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """One row per statement IDENTITY, with how many content versions it has.

        An identity is `(source, ticker, period_end, period_type, statement)` —
        migration 114's unique key minus `content_hash`. `version_count` is the
        number of distinct hashes stored for it, and it is the first thing the
        publication rule checks: with two or more, Argon cannot tell which
        version a filing published, so no publication date may be attached to
        any of them.

        `exclude_claim_key` skips identities whose every observation already
        carries that claim, which is what makes a backfill resumable without
        re-deciding settled rows. It is deliberately ALL rather than ANY: a
        partially-claimed identity still has work left.
        """
        if not tickers:
            return []
        having = ""
        params: list[Any] = [[t.upper() for t in tickers]]
        if exclude_claim_key:
            having = """
             HAVING bool_or(NOT EXISTS (
                        SELECT 1 FROM {schema}.fundamental_obs_availability a
                         WHERE a.obs_id = o.obs_id AND a.claim_key = %s))
            """.format(schema=self._schema)
            params.append(exclude_claim_key)
        sql = f"""
            SELECT o.ticker,
                   o.period_end,
                   o.period_type,
                   o.statement,
                   o.source,
                   count(DISTINCT o.content_hash) AS version_count,
                   array_agg(o.obs_id ORDER BY o.obs_id) AS obs_ids
              FROM {self._schema}.fundamental_statement_obs o
             WHERE o.ticker = ANY(%s)
             GROUP BY o.ticker, o.period_end, o.period_type, o.statement, o.source
             {having}
             ORDER BY o.ticker, o.period_end, o.statement
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                {
                    "ticker": r[0],
                    "period_end": r[1],
                    "period_type": r[2],
                    "statement": r[3],
                    "source": r[4],
                    "version_count": int(r[5]),
                    "obs_ids": list(r[6]),
                }
                for r in cur.fetchall()
            ]
