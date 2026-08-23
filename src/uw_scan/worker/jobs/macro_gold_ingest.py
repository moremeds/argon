"""Ingest gold's own two series into the point-in-time evidence store.

Same structural choice as ``macro_market_layer_ingest``, for the same reason: **the
artifact is written and COMMITTED before anything is parsed out of it**.  A publisher
schema change then costs this run and leaves the payload that caused it queryable, rather
than throwing away the bytes that would explain the failure.

What this does NOT ingest is the interesting part.  Lens 2 reads the 10-year real yield
and the broad dollar, and both stay owned by ``RATES_EVIDENCE`` / ``USD_EVIDENCE``.  Gold
points at the same stored rows.  Ingesting them here would put one publisher payload
under two owners, and the copies diverge on the first parser change.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import psycopg

from uw_scan.macro.gold_ingest import (
    flow_observations,
    gold_flow_artifact,
    gold_price_artifact,
    observation_row,
    price_observations,
)
from uw_scan.sources.etf_holdings import EtfHoldingsProvider
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

#: The GLD ticker massive serves bars for.
GOLD_SPOT_TICKER = "GLD"

#: How much history each run asks for.  Generous on purpose: these publishers are cheap,
#: the writer is idempotent on unchanged values, and a short window means a run that fails
#: for a week leaves a hole the engine's 63-day window would silently read across.
DEFAULT_LOOKBACK_DAYS = 400


@dataclass
class MacroGoldIngestResult:
    feeds_attempted: int = 0
    feeds_succeeded: int = 0
    artifacts_seen: int = 0
    observations_created: int = 0
    observations_unchanged: int = 0
    errors: list[str] = field(default_factory=list)


def macro_gold_ingest_job(
    *,
    dsn: str,
    massive_api_key: str,
    schema: str = "uw_scan",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    price_provider_factory: Callable[[], object] | None = None,
    flow_provider_factory: Callable[[], object] | None = None,
) -> MacroGoldIngestResult:
    """Fetch, store and parse both gold-owned feeds. One failing feed does not stop the other.

    The provider factories exist so a test can drive the REAL job -- artifact write,
    commit, parse, upsert -- against frozen payloads instead of the network. A test that
    called the parsing helpers directly would prove the parsers work and nothing about
    the ordering this module is built around.
    """
    result = MacroGoldIngestResult()
    retrieved_at = datetime.now(UTC)
    end = retrieved_at.date()
    start = end - timedelta(days=lookback_days)

    with psycopg.connect(dsn) as conn:
        repo = Repository(conn, schema=schema)
        _run_feed(
            "gold_price",
            lambda: _price_feed(
                repo,
                conn,
                api_key=massive_api_key,
                start=start,
                end=end,
                retrieved_at=retrieved_at,
                provider_factory=price_provider_factory,
            ),
            result,
        )
        _run_feed(
            "gold_flow",
            lambda: _flow_feed(
                repo,
                conn,
                start=start,
                retrieved_at=retrieved_at,
                provider_factory=flow_provider_factory,
            ),
            result,
        )
    return result


def _run_feed(name, call, result: MacroGoldIngestResult) -> None:
    result.feeds_attempted += 1
    try:
        artifacts, created, unchanged = call()
    except Exception as exc:
        # Logged and recorded, never raised: a dead vendor must not stop the other feed,
        # and the state job's own abstention already reports the consequence honestly.
        logger.warning("macro gold ingest feed %s failed: %s", name, repr(exc))
        result.errors.append(f"{name}: {repr(exc)[:400]}")
        return
    result.feeds_succeeded += 1
    result.artifacts_seen += artifacts
    result.observations_created += created
    result.observations_unchanged += unchanged


def _price_feed(
    repo: Repository,
    conn: psycopg.Connection,
    *,
    api_key: str,
    start: date,
    end: date,
    retrieved_at: datetime,
    provider_factory: Callable[[], object] | None = None,
) -> tuple[int, int, int]:
    factory = provider_factory or (
        lambda: MassiveOhlcProvider(api_key=api_key, timeout=60.0)
    )
    with factory() as provider:
        raw_bytes, source_url, bars = provider.fetch_daily_payload(
            GOLD_SPOT_TICKER, start, end
        )
    artifact = gold_price_artifact(
        raw_bytes, source_url=source_url, retrieved_at=retrieved_at
    )
    return _store(
        repo,
        conn,
        artifact,
        lambda: price_observations(bars, retrieved_at=retrieved_at),
        retrieved_at,
    )


def _flow_feed(
    repo: Repository,
    conn: psycopg.Connection,
    *,
    start: date,
    retrieved_at: datetime,
    provider_factory: Callable[[], object] | None = None,
) -> tuple[int, int, int]:
    factory = provider_factory or EtfHoldingsProvider
    with factory() as provider:
        raw_bytes, media_type, source_url, rows = provider.fetch_gld_payload(
            start=start
        )
    artifact = gold_flow_artifact(
        raw_bytes,
        source_url=source_url,
        media_type=media_type,
        retrieved_at=retrieved_at,
    )
    return _store(
        repo,
        conn,
        artifact,
        lambda: flow_observations(rows, retrieved_at=retrieved_at),
        retrieved_at,
    )


def _store(
    repo: Repository,
    conn: psycopg.Connection,
    artifact,
    parse,
    seen_at: datetime,
) -> tuple[int, int, int]:
    artifact_id = repo.insert_macro_artifact(
        source=artifact.source,
        source_kind=artifact.source_kind,
        source_record_id=artifact.source_record_id,
        source_url=artifact.source_url,
        published_at=artifact.published_at,
        available_at=artifact.available_at,
        retrieved_at=artifact.retrieved_at,
        content_hash=artifact.content_hash,
        parser_version=artifact.parser_version,
        quality_status=artifact.quality_status,
        cost_class=artifact.cost_class,
        media_type=artifact.media_type,
        content_length=artifact.content_length,
        vintage_bearing=artifact.vintage_bearing,
        # Forward whichever representation the artifact chose rather than assuming bytes.
        # The two feeds differ deliberately: the price payload is stored as parsed JSON so
        # massive's per-request ``request_id`` can be dropped from its identity, while the
        # SPDR archive stays raw because it arrives as CSV or XLSX and has no such stamp.
        raw_json=artifact.raw_json,
        raw_text=artifact.raw_text,
        raw_bytes=artifact.raw_bytes,
    )
    conn.commit()

    # The STORED artifact's retrieval clock, not this run's.
    #
    # ``insert_macro_artifact`` dedupes on content hash, so a re-read of unchanged bytes
    # returns the ORIGINAL row with its original ``retrieved_at``. Stamping the
    # observations with this run's wall clock then makes every one of them postdate the
    # payload that carries it, and the store refuses the batch -- so the second run of an
    # idempotent job fails outright. Reading the instant back makes "when did we learn
    # this" a property of the payload rather than of whichever run happened to look.
    stored = repo.fetch_macro_artifact(artifact_id)
    available_at = stored["retrieved_at"] if stored else artifact.retrieved_at

    # Only now. The bytes are safe, so a parse failure from here on costs this run and
    # leaves the payload that caused it queryable.
    outcome = repo.upsert_macro_series_observations(
        [
            observation_row(
                observation,
                artifact_id=artifact_id,
                artifact=artifact,
                available_at=available_at,
            )
            for observation in parse()
        ],
        seen_at=seen_at,
    )
    conn.commit()
    return 1, outcome.created, outcome.unchanged
