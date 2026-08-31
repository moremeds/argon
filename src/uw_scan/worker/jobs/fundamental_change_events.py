"""Change-event classes for the delta rail (spec §5-iv, Task 8).

Five new proposals through the discovery gate (`register_discovery_gate` in
`worker/jobs/research_events_derive.py`): `band_entry`, `band_exit`,
`implied_move_shift`, `coverage_change`, `bucket_flip`. All five read tables
Argon already ingests — valuation_anchors, implied_move_daily,
fundamental_statement_obs x chain_membership, fundamental_scores — so they
pass the gate's "no fabrication" bar by construction; see that module's
docstring for the deliberate deviation (no separate "filing-landed" class,
since `statement_published`/`sec_filing` already carry that fact) and the
measured registration counts.

TWO CLOCKS, PER CLASS
----------------------
`research_events` carries `occurred_at` (when the fact happened) and
`first_known_at` (when Argon learned it), with a database CHECK forbidding
`first_known_at < occurred_at`:

- `band_entry` / `band_exit`: occurred_at = the anchor row's OWN `as_of` (the
  spot date the band was computed against); first_known_at = this job's
  `as_of` (the night the derive ran), which is always >= the anchor's as_of
  because `fundamental_refresh` runs before this job.
- `implied_move_shift`: occurred_at = first_known_at = tonight's
  `market_date` — the shift happened and was learned in the same nightly
  snapshot.
- `coverage_change` ("gained_coverage"): occurred_at = the statement's own
  publication date (`filing_published_at`, falling back to
  `first_observed_at`'s date when the provider gave none); first_known_at =
  when Argon observed it (`first_observed_at`'s date). `first_observed_at`
  is always >= `filing_published_at` — we observe a filing after it
  publishes — so the CHECK holds structurally.
- `coverage_change` ("went_stale"): occurred_at = the newest compatible
  result's OWN `as_of` (when it was last computed); first_known_at = this
  job's `as_of` (the night the desk noticed the age crossed `STALE_DAYS`).
  Anchored to the result's as_of, not "today" — see idempotency note below.
- `bucket_flip`: THE ONE CLASS WHERE THE CLOCKS DELIBERATELY DIFFER.
  occurred_at = the score's OWN `as_of` (the bucket id —
  `fundamental_scores.as_of` is a knowledge-quarter CROSS-SECTION identifier,
  never a freshness timestamp, see storage/fundamental_scores.py);
  first_known_at = this job's `as_of` (the night the desk learned a name had
  moved to a newer bucket than any it had occupied before). The bucket can
  be dated well in the past (a backfilled score) while the desk only learns
  of the flip tonight.

IDEMPOTENCY IS A PROPERTY OF THE source_ref SHAPE, NOT AN ASSUMPTION
----------------------------------------------------------------------
`record_events`' `ON CONFLICT (event_class, ticker, occurred_at, source_ref)
DO NOTHING` means a class re-fires forever unless its `source_ref` is
anchored to something that stops varying once the underlying fact stops
changing. `coverage_change`'s "went_stale" direction is the sharp case:
`source_ref` is keyed on the STALE result's own `as_of`, not on "today" — a
ticker that stays stale for 200 consecutive nightly runs writes the event
exactly once, on the night it crossed, and every later run is a true no-op
for it. Anchoring it to "today" instead would double- (indeed N-) write
forever. `bucket_flip` is anchored the same way, on the newest `as_of` alone
— a rerun against an unchanged newest bucket is a no-op; a genuinely newer
bucket arriving later produces a new, distinct `source_ref`.

`as_of` MEANS SOMETHING DIFFERENT TO EACH CLASS (fix round 1, I4)
--------------------------------------------------------------------
`as_of` is NOT a uniform "replay this date" parameter across the five
classes, and calling this job with anything other than the real, current
run date is hazardous in two DIFFERENT ways:

- `_implied_move_shift_events` SELECTS by `as_of` (`WHERE market_date =
  as_of`) — it can only ever see the single most recent night once a later
  one lands, so a past `as_of` silently yields 0 the moment tonight's row
  exists, not an error.
- The other four classes do NOT select by `as_of` at all — they always read
  the LATEST live state (`in_buy_zone`'s newest snapshot, the newest
  `fundamental_dimensions`/`fundamental_scores` row) regardless of what
  `as_of` is. A past `as_of` therefore derives TODAY's facts and stamps them
  with a BACKDATED `first_known_at` — exactly the lie the two-clock design
  above exists to prevent.

There is no single fix that makes `as_of` mean the same thing everywhere
without a much larger rewrite (four classes would need point-in-time
selection queries they do not have). The mitigation lives in the committed
runner (`scripts/backfill/fundamental_change_events_run.py`): it refuses
`--execute` on a non-today `--as-of` unless `--allow-backdate` is passed,
so backdating requires an explicit, named opt-in rather than an unnoticed
default.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.implied_move import ImpliedMoveRepository
from uw_scan.storage.research_events import ResearchEventsRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.research_events_derive import (
    STALE_DAYS,
    register_discovery_gate,
)

log = logging.getLogger(__name__)

#: One percentage point. Chosen at the spec's stated threshold, not tuned —
#: this is the delta rail's first cut, not a validated signal.
IMPLIED_MOVE_SHIFT_PP = 0.01

# Decimal mirror of the constant above, used for the actual comparison.
# `implied_move_pct` round-trips as Decimal (NUMERIC column); comparing a
# float threshold against it would force a lossy float cast on the data side
# instead — see `_implied_move_shift_events`'s comment on why that is unsafe
# at exactly this boundary.
_SHIFT_THRESHOLD = Decimal(str(IMPLIED_MOVE_SHIFT_PP))


def _num(value: Any) -> float | None:
    """Decimal -> float for a jsonb detail payload. `Jsonb` serializes via
    `json.dumps`, which does not know `Decimal`."""
    return None if value is None else float(value)


def _band_entry_events(
    conn: psycopg.Connection,
    *,
    schema: str,
    engine_version: str,
    as_of: date,
) -> list[dict[str, Any]]:
    """Rows from `in_buy_zone` with `entered is True`. Rows with `entered is
    None` (no prior band in the 30-day lookback) emit NOTHING — null is not
    NEW. `entered is False` (already in zone) is not an entry either. Only an
    explicit `is True` may fire; anything else — including a bug that lets
    `None` slip through — must be excluded."""
    anchors = FundamentalAnchorsRepository(conn, schema=schema)
    rows: list[dict[str, Any]] = []
    for r in anchors.in_buy_zone(engine_version):
        if r["entered"] is not True:
            continue
        occurred = r["as_of"]
        rows.append(
            {
                "event_class": "band_entry",
                "ticker": r["ticker"],
                "occurred_at": occurred,
                "first_known_at": max(occurred, as_of),
                "title": f"{r['ticker']} entered its own-history buy zone",
                "detail": {
                    "method": r["method"],
                    "buy_below": _num(r["buy_below"]),
                    "spot": _num(r["spot"]),
                    "engine_version": engine_version,
                },
                "source_kind": "valuation_anchors",
                "source_ref": f"{r['ticker']}:{occurred}:{engine_version}",
            }
        )
    return rows


def _band_exit_events(
    conn: psycopg.Connection,
    *,
    schema: str,
    engine_version: str,
    as_of: date,
) -> list[dict[str, Any]]:
    """Tickers in-zone at the previous `as_of` for this engine and not
    in-zone (or refused — no usable band) at the newest `as_of`.

    Mirrors `FundamentalAnchorsRepository.in_buy_zone`'s window-function
    shape exactly (same lookback, same NULL-safe in-zone predicate) but is
    not delegated to it — `in_buy_zone` returns only rows CURRENTLY in zone,
    and an exit is, by definition, a row that just left.
    """
    in_zone = "(spot IS NOT NULL AND buy_below IS NOT NULL AND spot <= buy_below)"
    lookback = FundamentalAnchorsRepository.IN_ZONE_LOOKBACK_DAYS
    sql = f"""
        WITH latest AS (
            SELECT max(as_of) AS d FROM {schema}.valuation_anchors
             WHERE engine_version = %(engine)s
        ),
        recent AS (
            SELECT DISTINCT ON (a.ticker, a.as_of)
                   a.ticker, a.as_of, a.method, a.buy_below, a.spot
              FROM {schema}.valuation_anchors a, latest
             WHERE a.engine_version = %(engine)s
               AND a.as_of > latest.d - %(lookback)s
             ORDER BY a.ticker, a.as_of DESC, a.result_id DESC
        ),
        flagged AS (
            SELECT ticker, as_of, method, buy_below, spot,
                   {in_zone} AS in_zone,
                   LAG({in_zone}) OVER w AS prev_in_zone,
                   LAG(as_of) OVER w AS prev_as_of
              FROM recent
            WINDOW w AS (PARTITION BY ticker ORDER BY as_of)
        )
        SELECT ticker, as_of, method, buy_below, spot
          FROM flagged, latest
         WHERE as_of = latest.d
           AND prev_as_of IS NOT NULL
           AND prev_in_zone
           AND NOT in_zone
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"engine": engine_version, "lookback": lookback})
        cols = [d.name for d in cur.description]
        results = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    rows: list[dict[str, Any]] = []
    for r in results:
        occurred = r["as_of"]
        rows.append(
            {
                "event_class": "band_exit",
                "ticker": r["ticker"],
                "occurred_at": occurred,
                "first_known_at": max(occurred, as_of),
                "title": f"{r['ticker']} left its own-history buy zone",
                "detail": {
                    "method": r["method"],
                    "buy_below": _num(r["buy_below"]),
                    "spot": _num(r["spot"]),
                    "engine_version": engine_version,
                },
                "source_kind": "valuation_anchors",
                "source_ref": f"{r['ticker']}:{occurred}:{engine_version}",
            }
        )
    return rows


def _implied_move_shift_events(
    conn: psycopg.Connection, *, schema: str, as_of: date
) -> list[dict[str, Any]]:
    """For every `(ticker, report_date)` that received a snapshot tonight,
    compare tonight's `implied_move_pct` against the immediately preceding
    night's for the SAME upcoming print. `history()` is oldest-first, so the
    last two rows are the ones that matter."""
    repo = ImpliedMoveRepository(conn, schema=schema)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT ticker, report_date
                  FROM {schema}.implied_move_daily
                 WHERE market_date = %s""",
            (as_of,),
        )
        pairs = cur.fetchall()

    rows: list[dict[str, Any]] = []
    for ticker, report_date in pairs:
        history = repo.history(ticker, report_date)
        if len(history) < 2:
            continue
        today_row, prev_row = history[-1], history[-2]
        if today_row["market_date"] != as_of:
            # Defensive: the row that put this pair in `pairs` should be the
            # newest in its own history.
            continue
        # Decimal, not float, for the comparison — see CLAUDE.md's "Decimal
        # over float for prices, IV, RV, Greeks, scoring". A float cast here
        # is not cosmetic: `abs(0.11 - 0.10) < 0.01` is TRUE in binary
        # float (0.009999999999999995), which would silently swallow an
        # exact-boundary shift. `implied_move_pct` round-trips as Decimal
        # from the NUMERIC column; comparing in that type avoids the trap.
        today_pct = Decimal(today_row["implied_move_pct"])
        prev_pct = Decimal(prev_row["implied_move_pct"])
        shift = abs(today_pct - prev_pct)
        if shift < _SHIFT_THRESHOLD:
            continue
        rows.append(
            {
                "event_class": "implied_move_shift",
                "ticker": ticker,
                "occurred_at": as_of,
                "first_known_at": as_of,
                "title": (
                    f"{ticker} implied move shifted {float(shift) * 100:.1f}pp "
                    f"for the {report_date.isoformat()} print"
                ),
                "detail": {
                    "report_date": report_date.isoformat(),
                    "prev_market_date": prev_row["market_date"].isoformat(),
                    "prev_pct": _num(prev_pct),
                    "today_pct": _num(today_pct),
                    "shift_pp": _num(shift),
                    # branch-fix-p2, I3: `implied_move_pct` depends on the
                    # COVERING EXPIRY, which is re-picked every night
                    # (`implied_move_snapshot.py`) — a new weekly listing, or
                    # a late `session` fill-in shifting the reaction day, can
                    # move `expiry` without any IV actually moving. Carrying
                    # both nights' expiry/atm_iv/iv_basis lets a reader of the
                    # event ledger tell a genuine vol repricing (expiry
                    # unchanged, atm_iv moved) apart from a bookkeeping
                    # artefact (expiry changed) after the fact, instead of
                    # trusting the title's "implied move shifted" framing on
                    # faith.
                    "expiry": today_row["expiry"].isoformat(),
                    "prev_expiry": prev_row["expiry"].isoformat(),
                    "atm_iv": _num(today_row["atm_iv"]),
                    "prev_atm_iv": _num(prev_row["atm_iv"]),
                    "iv_basis": today_row["iv_basis"],
                    "prev_iv_basis": prev_row["iv_basis"],
                },
                "source_kind": "implied_move_daily",
                "source_ref": f"{ticker}:{report_date}:{as_of}",
            }
        )
    return rows


def _chain_member_tickers(conn: psycopg.Connection, *, schema: str) -> list[str]:
    """Distinct, currently-open chain members under the ACTIVE taxonomy
    version. `chain_membership` is grained `(chain, layer, ticker)` — a name
    in two layers is two rows, so this dedupes to distinct tickers, never a
    row count (the exact trap the module docstring in
    `storage/research_taxonomy.py` warns about)."""
    taxonomy = ResearchTaxonomyRepository(conn, schema=schema)
    version = taxonomy.active_version()
    if version is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT ticker FROM {schema}.chain_membership
                 WHERE taxonomy_version = %s AND valid_to IS NULL""",
            (version,),
        )
        return [r[0] for r in cur.fetchall()]


def _gained_coverage_events(
    conn: psycopg.Connection, *, schema: str, members: list[str]
) -> list[dict[str, Any]]:
    """Chain-member tickers whose ONLY `fundamental_statement_obs` row is
    their first.

    `source_ref` still carries `occurred` for readability, but a ticker is
    excluded from candidacy the moment it has EVER emitted a `gained_
    coverage` event (fix round 1, M1) — not merely by conflicting on an
    unchanged `source_ref`. `occurred` is `coalesce(filing_published_at,
    first_observed_at::date)`, and CLAUDE.md documents that
    `record_statements` fills a NULL `filing_published_at` via `COALESCE`
    on conflict when UW publishes the date LATER: while the ticker still
    has exactly one statement, that back-fill would change both
    `occurred_at` and `source_ref` on the very next run, and a `source_ref`
    that no longer matches the first run's row does not collide on
    `ON CONFLICT` — it inserts a second, duplicate event. Checking
    `research_events` directly (keyed only on ticker + direction, both
    immutable) closes that gap regardless of what `occurred_at` recomputes
    to."""
    if not members:
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT ticker FROM {schema}.research_events
                 WHERE event_class = 'coverage_change'
                   AND detail_jsonb->>'direction' = 'gained_coverage'
                   AND ticker = ANY(%s)""",
            (members,),
        )
        already_emitted = {r[0] for r in cur.fetchall()}
    candidates = [m for m in members if m not in already_emitted]
    if not candidates:
        return []

    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT ticker,
                       min(coalesce(filing_published_at, first_observed_at::date))
                           AS occurred,
                       min(first_observed_at::date) AS known
                  FROM {schema}.fundamental_statement_obs
                 WHERE ticker = ANY(%s)
                 GROUP BY ticker
                HAVING count(*) = 1""",
            (candidates,),
        )
        results = cur.fetchall()

    rows: list[dict[str, Any]] = []
    for ticker, occurred, known in results:
        first_known = max(occurred, known)
        rows.append(
            {
                "event_class": "coverage_change",
                "ticker": ticker,
                "occurred_at": occurred,
                "first_known_at": first_known,
                "title": f"{ticker} gained its first ingested statement",
                "detail": {"direction": "gained_coverage"},
                "source_kind": "fundamental_statement_obs",
                "source_ref": f"{ticker}:{occurred}:gained_coverage",
            }
        )
    return rows


def _went_stale_events(
    conn: psycopg.Connection, *, schema: str, as_of: date, members: list[str]
) -> list[dict[str, Any]]:
    """Chain-member tickers whose newest `fundamental_dimensions` result
    (under the active method version, same STALE_DAYS Radar uses) is older
    than `STALE_DAYS`. `source_ref` is keyed on that result's own `as_of`,
    not on `as_of` (today) — see the module docstring's idempotency note:
    without that, a ticker stuck stale would re-fire every single night."""
    if not members:
        return []
    engine = FundamentalScoresRepository(conn, schema=schema).active_version()
    if engine is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT ticker, max(as_of)
                  FROM {schema}.fundamental_dimensions
                 WHERE engine_version = %s AND ticker = ANY(%s)
                 GROUP BY ticker""",
            (engine, members),
        )
        results = cur.fetchall()

    rows: list[dict[str, Any]] = []
    for ticker, newest_as_of in results:
        age = (as_of - newest_as_of).days
        if age <= STALE_DAYS:
            continue
        rows.append(
            {
                "event_class": "coverage_change",
                "ticker": ticker,
                "occurred_at": newest_as_of,
                "first_known_at": as_of,
                "title": (f"{ticker}'s newest compatible result is {age} days old"),
                "detail": {
                    "direction": "went_stale",
                    "age_days": age,
                    "threshold_days": STALE_DAYS,
                },
                "source_kind": "fundamental_dimensions",
                "source_ref": f"{ticker}:{newest_as_of}:went_stale",
            }
        )
    return rows


def _coverage_change_events(
    conn: psycopg.Connection, *, schema: str, as_of: date
) -> list[dict[str, Any]]:
    # Computed once (fix round 1, M5) and shared — the taxonomy lookup +
    # membership query otherwise ran twice, once per direction.
    members = _chain_member_tickers(conn, schema=schema)
    return [
        *_gained_coverage_events(conn, schema=schema, members=members),
        *_went_stale_events(conn, schema=schema, as_of=as_of, members=members),
    ]


def _bucket_flip_events(
    conn: psycopg.Connection, *, schema: str, engine_version: str, as_of: date
) -> list[dict[str, Any]]:
    """A ticker's newest `fundamental_scores.as_of` bucket, under the ACTIVE
    engine version, moved to one newer than any it had occupied before.
    `as_of` here is a knowledge-quarter CROSS-SECTION identifier (see
    storage/fundamental_scores.py), never a freshness timestamp — a name's
    first-ever bucket is not a flip (there is nothing to have moved FROM),
    and a bucket older than one already occupied is not a flip either,
    however recently it was written.

    Scoped to `engine_version` (fix round 1, I2): querying across every
    engine_version let two rows for the SAME ticker under DIFFERENT method
    versions — one retired, one active — collide on an identical
    `(event_class, ticker, occurred_at, source_ref)` tuple whenever both
    happened to share the same newest `as_of` (measured: 378 tickers on
    `option_wizard_local` shared `max(as_of)` across `fundamentals-v1` and
    `fundamentals-v2`). `ON CONFLICT DO NOTHING` then silently discarded one
    of the two, and which engine's `detail_jsonb.engine_version` survived was
    whatever order the cursor returned. Scoping to one engine_version removes
    the collision at the source, matching `band_entry`/`band_exit`."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ticker, as_of, rn
              FROM (
                  SELECT ticker, as_of,
                         row_number() OVER (
                             PARTITION BY ticker ORDER BY as_of DESC
                         ) AS rn
                    FROM (SELECT DISTINCT ticker, as_of
                            FROM {schema}.fundamental_scores
                           WHERE engine_version = %s) d
              ) ranked
             WHERE rn <= 2
            """,
            (engine_version,),
        )
        by_ticker: dict[str, dict[int, date]] = {}
        for ticker, bucket_as_of, rn in cur.fetchall():
            by_ticker.setdefault(ticker, {})[rn] = bucket_as_of

    rows: list[dict[str, Any]] = []
    for ticker, buckets in by_ticker.items():
        newest_as_of = buckets.get(1)
        prior_as_of = buckets.get(2)
        if newest_as_of is None or prior_as_of is None:
            # No prior bucket to have flipped from.
            continue
        # Unreachable by construction, kept as the executable statement of
        # this class's semantics (fix round 1, reviewer-ruled KEEP): the
        # inner query is `SELECT DISTINCT ticker, as_of`, so within one
        # ticker every `as_of` is distinct and NOT NULL, and `ORDER BY as_of
        # DESC` therefore makes rn=1's date strictly greater than rn=2's
        # whenever both exist. This guard only fires if that DISTINCT or
        # ORDER BY is ever weakened — treat a hit here as a query-shape bug,
        # not a legitimate "older bucket" case.
        if newest_as_of <= prior_as_of:
            continue
        rows.append(
            {
                "event_class": "bucket_flip",
                "ticker": ticker,
                "occurred_at": newest_as_of,
                # max()'d against the run date (fix round 1, I1): without
                # this guard, a run whose `as_of` precedes the bucket's own
                # date — the committed runner's `--as-of <past>`, or a
                # future-dated `fundamental_scores.as_of` like the 371 rows
                # migration 129 records landing on prod — raises
                # `CheckViolation: research_events_known_after_occurred`
                # instead of writing. `band_entry`/`band_exit`/
                # `gained_coverage` already carry this guard; `bucket_flip`
                # was the one class that didn't.
                "first_known_at": max(newest_as_of, as_of),
                "title": (
                    f"{ticker} moved to a newer scoring bucket "
                    f"({newest_as_of.isoformat()})"
                ),
                "detail": {
                    "engine_version": engine_version,
                    "prior_as_of": prior_as_of.isoformat(),
                    "new_as_of": newest_as_of.isoformat(),
                },
                "source_kind": "fundamental_scores",
                # engine_version in the ref (fix round 1, I2) so a future
                # multi-engine deployment can never collide two engines'
                # flips for the same ticker/date onto one identity key.
                "source_ref": f"{ticker}:{newest_as_of}:{engine_version}",
            }
        )
    return rows


def derive_change_events(
    conn: psycopg.Connection, *, as_of: date, schema: str = "uw_scan"
) -> dict[str, int]:
    """Turn tonight's ingested state into typed delta-rail events. Idempotent
    on each class's identity key — see the module docstring."""
    # SEED THE REGISTRY FIRST, because in production it was EMPTY.
    #
    # Measured 2026-08-28 on the mini: `research_event_classes` held 0 rows, so
    # every class was unregistered and `record_events` refused every write —
    # the typed ledger was inert and this job would raise
    # `event classes not live: [...]` the moment any class produced a row.
    # `register_discovery_gate` is the only thing that populates the table and
    # it had NO caller anywhere: it was referenced in two docstrings, including
    # this module's, and never invoked. The unit tests all passed because their
    # fixtures registered the classes production does not.
    #
    # The failure was silent by construction. With no class registered, the
    # desk's delta rail renders "Argon learned nothing new about this section",
    # which reads as a quiet week rather than a dead pipeline.
    #
    # Registering here rather than in a deploy step: `register_classes` is an
    # upsert over a FIXED list whose statuses live in code, so running it is a
    # seed and never a bypass of the discovery gate — a killed class is
    # re-registered as killed, and keeps refusing writes.
    register_discovery_gate(conn, schema=schema)

    repo = ResearchEventsRepository(conn, schema=schema)
    engine_version = FundamentalScoresRepository(conn, schema=schema).active_version()

    counters: dict[str, int] = {
        "band_entry": 0,
        "band_exit": 0,
        "implied_move_shift": 0,
        "coverage_change": 0,
        "bucket_flip": 0,
    }

    if engine_version is not None:
        counters["band_entry"] = repo.record_events(
            _band_entry_events(
                conn, schema=schema, engine_version=engine_version, as_of=as_of
            )
        )
        counters["band_exit"] = repo.record_events(
            _band_exit_events(
                conn, schema=schema, engine_version=engine_version, as_of=as_of
            )
        )
        counters["bucket_flip"] = repo.record_events(
            _bucket_flip_events(
                conn, schema=schema, engine_version=engine_version, as_of=as_of
            )
        )

    counters["implied_move_shift"] = repo.record_events(
        _implied_move_shift_events(conn, schema=schema, as_of=as_of)
    )
    counters["coverage_change"] = repo.record_events(
        _coverage_change_events(conn, schema=schema, as_of=as_of)
    )

    log.info("derive_change_events as_of=%s: %s", as_of, counters)
    return counters
