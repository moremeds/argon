"""Company-type routing and stage-3 anchor bands (migration 116).

Standalone repository. **Every writer commits** — same reason as its two
siblings: the known failure in this area is a refresh that ran, logged success
and persisted nothing.

Anchor rows are IMMUTABLE on `(ticker, as_of, engine_version, inputs_hash)`, so
the write is `DO NOTHING`. Company-type rows are the deliberate exception: that
table is a routing decision a human edits, and an edit has to land.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import psycopg

from uw_scan.fundamentals.valuation import LEVEL_ORDER


class FundamentalAnchorsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- company_type routing ----------------

    def company_types(self) -> dict[str, str]:
        """Every assignment, ticker -> company_type."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT ticker, company_type FROM {self._schema}.fundamental_company_type"
            )
            return dict(cur.fetchall())

    def company_type(self, ticker: str) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT company_type FROM {self._schema}.fundamental_company_type
                     WHERE ticker = %s""",
                (ticker.upper(),),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def assign(
        self,
        ticker: str,
        company_type: str,
        *,
        source: str = "seeded",
        note: str | None = None,
        overwrite_manual: bool = False,
    ) -> bool:
        """Route one ticker. Returns True if the row changed.

        A `manual` assignment survives a reseed unless `overwrite_manual` is set.
        Without that guard a nightly seeding pass would silently undo every hand
        correction, and the correction is exactly the thing worth keeping — the
        seeding heuristic is sector+chain, which is a starting point, not a
        verdict.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self._schema}.fundamental_company_type
                           (ticker, company_type, source, note)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ticker) DO UPDATE
                       SET company_type = EXCLUDED.company_type,
                           source       = EXCLUDED.source,
                           note         = EXCLUDED.note,
                           updated_at   = now()
                     WHERE {self._schema}.fundamental_company_type.company_type
                             IS DISTINCT FROM EXCLUDED.company_type
                       AND (%s OR {self._schema}.fundamental_company_type.source
                                    <> 'manual')
                    RETURNING ticker""",
                (ticker.upper(), company_type, source, note, overwrite_manual),
            )
            changed = cur.fetchone() is not None
        self.conn.commit()
        return changed

    # ---------------- anchor results ----------------

    def insert_anchors(self, rows: Sequence[dict[str, Any]]) -> int:
        """Append anchor bands. Returns rows actually written.

        `DO NOTHING` on the identity key: a re-run over unchanged inputs is the
        same result, and re-writing it would churn `computed_at` on a row nothing
        about the world changed.
        """
        if not rows:
            return 0
        cols = [
            "ticker",
            "as_of",
            "engine_version",
            "inputs_hash",
            "company_type",
            "method",
            *LEVEL_ORDER,
            "spot",
            "spot_percentile",
            "history_quarters",
            "confidence",
            "confidence_reasons_jsonb",
            "inputs_jsonb",
            "source_obs_ids",
        ]
        placeholders = ", ".join(["%s"] * len(cols))
        written = 0
        with self.conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    f"""INSERT INTO {self._schema}.valuation_anchors
                               ({", ".join(cols)})
                        VALUES ({placeholders})
                        ON CONFLICT (ticker, as_of, engine_version, inputs_hash)
                        DO NOTHING
                        RETURNING result_id""",
                    [
                        json.dumps(r[c])
                        if c in ("confidence_reasons_jsonb", "inputs_jsonb")
                        else r.get(c)
                        for c in cols
                    ],
                )
                written += cur.fetchone() is not None
        self.conn.commit()
        return written

    def latest_for_ticker(
        self, ticker: str, engine_version: str
    ) -> dict[str, Any] | None:
        """Newest band for this ticker under one method version.

        Scoped to `engine_version` on purpose: returning the newest row across
        versions would let a band computed under a retired method render beside
        subscores computed under the live one, with nothing on screen to say so.
        """
        cols = [
            "ticker",
            "as_of",
            "engine_version",
            "inputs_hash",
            "company_type",
            "method",
            *LEVEL_ORDER,
            "spot",
            "spot_percentile",
            "history_quarters",
            "confidence",
            "confidence_reasons_jsonb",
            "inputs_jsonb",
            "source_obs_ids",
        ]
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT {", ".join(cols)}
                      FROM {self._schema}.valuation_anchors
                     WHERE ticker = %s AND engine_version = %s
                     ORDER BY as_of DESC, result_id DESC
                     LIMIT 1""",
                (ticker.upper(), engine_version),
            )
            row = cur.fetchone()
        return dict(zip(cols, row)) if row else None
