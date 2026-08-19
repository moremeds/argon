"""Company-type routing and stage-3 anchor bands (migration 118).

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

    # ---------------- cross-name membership ----------------
    #
    # A LIST of names each in its own buy zone. Not a cross-sectional RANK, and
    # the difference is the reason this method is allowed to exist at all.
    #
    # `latest_for_ticker` above answers "is THIS name cheap against its own
    # past" — the claim that measured (`sales_to_ev` market-neutral 2q IC
    # +0.0744, t 5.77, within-ticker). Ranking names against each other on value
    # measured INVERTED in this universe (`book_to_price` IC -0.0365, t -2.32),
    # so an ordering by `spot_percentile` would point at the half of the panel
    # that then underperforms.
    #
    # `in_buy_zone` returns N independent single-name verdicts side by side. Each
    # row still says only "this name is cheap versus its OWN history"; putting
    # them in one response does not compare them, and the ordering deliberately
    # carries no valuation information (see ORDER BY below).

    IN_ZONE_LOOKBACK_DAYS = 30

    def in_buy_zone(self, engine_version: str) -> list[dict[str, Any]]:
        """Names whose stored spot sits at or below their own `buy_below`.

        Read at the newest `as_of` present for this method version. Rows carry
        `entered`: True when the name was OUT of its zone at the previous
        `as_of` and is in it now, False when it was already in, and None when no
        prior row exists inside the lookback — three states rather than two
        because "no comparison available" is not "not new", and a renderer that
        collapsed them would badge a name NEW on the strength of missing data.

        `as_of` is the SPOT date the band was computed against, not the date the
        job ran.
        """
        cols = [
            "ticker",
            "as_of",
            "company_type",
            "method",
            "buy_below",
            "observe_mid",
            "risk_above",
            "spot",
            "spot_percentile",
            "history_quarters",
            "confidence",
            "confidence_reasons_jsonb",
        ]
        out = [*cols, "entered"]
        # NULL-safe: a row missing either side is not in the zone, and IS NOT
        # DISTINCT FROM would make `spot IS NULL` compare equal to nothing.
        in_zone = "(spot IS NOT NULL AND buy_below IS NOT NULL AND spot <= buy_below)"
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                WITH latest AS (
                    SELECT max(as_of) AS d
                      FROM {self._schema}.valuation_anchors
                     WHERE engine_version = %(engine)s
                ),
                -- One row per (ticker, as_of): a single day can hold several
                -- inputs_hash rows, and the newest is the one the card shows.
                recent AS (
                    SELECT DISTINCT ON (a.ticker, a.as_of) {", ".join(f"a.{c}" for c in cols)}
                      FROM {self._schema}.valuation_anchors a, latest
                     WHERE a.engine_version = %(engine)s
                       AND a.as_of > latest.d - %(lookback)s
                     ORDER BY a.ticker, a.as_of DESC, a.result_id DESC
                ),
                flagged AS (
                    SELECT {", ".join(cols)},
                           {in_zone} AS in_zone,
                           LAG({in_zone}) OVER w AS prev_in_zone,
                           LAG(as_of)     OVER w AS prev_as_of
                      FROM recent
                    WINDOW w AS (PARTITION BY ticker ORDER BY as_of)
                )
                SELECT {", ".join(cols)},
                       CASE WHEN prev_as_of IS NULL THEN NULL
                            ELSE NOT prev_in_zone END AS entered
                  FROM flagged, latest
                 WHERE as_of = latest.d AND in_zone
                 -- Two groups only: newly-entered first, because entry is a
                 -- dated EVENT about one name, then everything else
                 -- alphabetically. `entered = false` and `entered = null` share
                 -- the tail deliberately — sorting unknown ABOVE known-not-new
                 -- would have put 29 of 98 names at the top on 2026-08-17,
                 -- every one of them there because the panel widened from 256
                 -- to 414 names rather than because a price moved.
                 --
                 -- Never by `spot_percentile`: that ordering is the inverted
                 -- cross-sectional claim wearing the validated one's clothes.
                 ORDER BY (prev_as_of IS NOT NULL AND NOT prev_in_zone) DESC,
                          ticker
                """,
                {"engine": engine_version, "lookback": self.IN_ZONE_LOOKBACK_DAYS},
            )
            rows = cur.fetchall()
        return [dict(zip(out, r)) for r in rows]

    def band_coverage(self, engine_version: str) -> tuple[Any, int]:
        """`(newest as_of, names carrying a usable band on it)`.

        The denominator for `in_buy_zone`: without it a list of 100 says nothing,
        because 100-of-342 and 100-of-110 are different facts about the universe.
        A band is "usable" when `buy_below` is present — a REFUSED band is a row
        with every level null, and counting it would inflate coverage with names
        the method declined to price.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                WITH latest AS (
                    SELECT max(as_of) AS d
                      FROM {self._schema}.valuation_anchors
                     WHERE engine_version = %s
                )
                SELECT latest.d,
                       count(DISTINCT a.ticker) FILTER (WHERE a.buy_below IS NOT NULL)
                  FROM latest
                  LEFT JOIN {self._schema}.valuation_anchors a
                         ON a.engine_version = %s AND a.as_of = latest.d
                 GROUP BY latest.d
                """,
                (engine_version, engine_version),
            )
            row = cur.fetchone()
        return (row[0], row[1]) if row else (None, 0)
