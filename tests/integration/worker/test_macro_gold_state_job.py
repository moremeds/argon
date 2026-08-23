"""The gold lane end to end: ingest -> evidence store -> state -> dependency edges.

Every value is real and frozen.  The gold closes and ETF tonnage come from
``tests/fixtures/macro/usd_gold_golden.json``, fetched from the live publishers before
any of this code existed; the stub providers replay those bytes so the REAL job runs its
real ordering -- artifact write, commit, parse, upsert -- without a network.

The point of driving the job rather than the helpers: this lane's whole design is that
the artifact is committed BEFORE the parse, and that gold's state abstains rather than
inventing evidence.  Neither is observable from a function that returns a dataclass.
"""

from __future__ import annotations

import itertools
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.macro.gold_ingest import GOLD_FLOW_SERIES, GOLD_PRICE_SERIES
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_gold_ingest import macro_gold_ingest_job
from uw_scan.worker.jobs.macro_state_jobs import macro_gold_state_job

GOLDEN = json.loads(
    (
        Path(__file__).parents[1].parent / "fixtures" / "macro" / "usd_gold_golden.json"
    ).read_text(encoding="utf-8")
)


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _rows(scenario_id: str, series_id: str) -> list[dict[str, Any]]:
    scenario = next(s for s in GOLDEN["scenarios"] if s["id"] == scenario_id)
    return [r for r in scenario["inputs"] if r["series_id"] == series_id]


class _Bar:
    def __init__(self, bar_date: date, close: Decimal) -> None:
        self.date = bar_date
        self.close = close


class _HoldingRow:
    def __init__(self, obs_date: date, holdings_oz: Decimal) -> None:
        self.obs_date = obs_date
        self.holdings_oz = holdings_oz


#: Incremented per fetch so the stub reproduces the ONE behaviour that broke idempotency
#: in production: massive stamps a fresh ``request_id`` on every response. A stub that
#: returns byte-identical payloads makes the re-read test pass no matter what the code
#: hashes, which is exactly why the original test was green while the real job wrote 275
#: duplicate rows per run.
_PRICE_FETCH_COUNT = itertools.count()


class _PriceProvider:
    """Replays the frozen GLD closes as the massive payload they came from."""

    def __enter__(self) -> "_PriceProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def fetch_daily_payload(
        self, ticker: str, start: date, end: date
    ) -> tuple[bytes, str, list[_Bar]]:
        rows = _rows("gold_and_real_yields_decoupled_post_2022", GOLD_PRICE_SERIES)
        bars = [
            _Bar(date.fromisoformat(r["period_end"]), Decimal(r["value"])) for r in rows
        ]
        payload = json.dumps(
            {
                "ticker": ticker,
                "results": [{"t": 0, "c": str(b.close)} for b in bars],
                # Same shape and same LENGTH every call, different value -- which is what
                # made ``content_length`` match while the hash moved.
                "request_id": f"{next(_PRICE_FETCH_COUNT):032x}",
            }
        ).encode()
        return payload, "https://api.massive.com/v2/aggs/ticker/GLD/range/1/day", bars


class _FlowProvider:
    """Replays the frozen SPDR tonnage prints as the CSV they came from."""

    def __enter__(self) -> "_FlowProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def fetch_gld_payload(
        self, *, start: date | None = None
    ) -> tuple[bytes, str, str, list[_HoldingRow]]:
        rows = _rows("strong_official_flows_against_adverse_cyclical", GOLD_FLOW_SERIES)
        parsed = [
            _HoldingRow(date.fromisoformat(r["period_end"]), Decimal(r["value"]))
            for r in rows
        ]
        csv = "date,ounces\n" + "\n".join(
            f"{r.obs_date.isoformat()},{r.holdings_oz}" for r in parsed
        )
        return (
            csv.encode(),
            "text/csv",
            "https://www.spdrgoldshares.com/archive",
            parsed,
        )


def _ingest(settings: Settings) -> Any:
    return macro_gold_ingest_job(
        dsn=settings.db_dsn(),
        massive_api_key="unused-by-the-stub",
        price_provider_factory=_PriceProvider,
        flow_provider_factory=_FlowProvider,
    )


def _repo(conn: psycopg.Connection) -> Repository:
    return Repository(conn, schema="uw_scan")


def test_ingest_lands_both_gold_series_as_citable_evidence(seeded_db_empty_cards):
    """The blocker deviation 7 named, closed: gold rows now carry an ``obs_id``."""
    settings = _settings()
    result = _ingest(settings)

    assert result.feeds_succeeded == 2, result.errors
    assert result.artifacts_seen == 2
    assert result.observations_created > 0

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT series_id, count(*), count(obs_id)
            FROM uw_scan.macro_observations
            WHERE domain = 'gold'
            GROUP BY series_id ORDER BY series_id
            """
        )
        found = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    assert set(found) == {GOLD_PRICE_SERIES, GOLD_FLOW_SERIES}
    for series, (total, with_id) in found.items():
        assert total == with_id > 0, f"{series} has rows without an obs_id"


def test_ingest_is_idempotent_on_a_second_run(seeded_db_empty_cards):
    """An unchanged re-read must not mint a phantom revision.

    The price stub deliberately varies its ``request_id`` between calls, so this asserts
    the property that actually matters -- unchanged DATA deduplicates -- rather than the
    weaker one a fixed payload can prove.
    """
    settings = _settings()
    first = _ingest(settings)
    second = _ingest(settings)

    assert second.observations_created == 0
    assert second.observations_unchanged == first.observations_created


def test_a_fresh_request_id_alone_does_not_mint_a_new_artifact(seeded_db_empty_cards):
    """Identity is the DATA, not the envelope massive wrapped it in.

    Measured in production on 2026-08-23 before the fix: a second run over an unchanged
    400-day window created 275 duplicate ``GLD_CLOSE`` rows under a second artifact,
    because ``request_id`` is a fresh 32-hex UUID per call. Row counts are asserted
    directly rather than through the job's own tallies -- the tallies are what reported
    ``created=275`` while claiming success.
    """
    settings = _settings()
    _ingest(settings)
    _ingest(settings)

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*), count(DISTINCT period_end), count(DISTINCT artifact_id)
            FROM uw_scan.macro_observations
            WHERE series_id = %s
            """,
            (GOLD_PRICE_SERIES,),
        )
        rows, periods, artifacts = cur.fetchone()

    assert rows == periods, f"{rows - periods} duplicate rows for {GOLD_PRICE_SERIES}"
    assert artifacts == 1, f"{artifacts} artifacts for one unchanged payload"


def test_state_abstains_before_the_ingest_runs(seeded_db_empty_cards):
    """No anchor, no row -- and that is a correct outcome, not a failure."""
    settings = _settings()
    with psycopg.connect(settings.db_dsn()) as conn:
        result = macro_gold_state_job(_repo(conn), as_of=datetime.now(UTC))

    assert result.status == "abstained"
    assert result.state_id is None


def test_state_persists_with_evidence_after_the_ingest(seeded_db_empty_cards):
    """The whole lane: ingest, then a state that cites what it stood on."""
    settings = _settings()
    _ingest(settings)

    # ``now()``, and NOT the fixture's 2026-01-08. These rows were RETRIEVED just now,
    # so under R1 that is when they became knowable -- asking for January is asking what
    # we knew before we fetched, and the store's own guard rejects a state that cites it.
    # The first draft of this test did exactly that and was refused, which is the guard
    # doing its job on the code that was supposed to respect it.
    as_of = datetime.now(UTC)
    with psycopg.connect(settings.db_dsn()) as conn:
        result = macro_gold_state_job(_repo(conn), as_of=as_of)

    assert result.status == "ok", result.error_message
    assert result.state_id is not None
    assert result.evidence_count > 0

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT domain, state FROM uw_scan.macro_domain_states WHERE state_id = %s",
            (result.state_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "gold"
        # No stored gauge in this fixture, so the gate must read UNKNOWN. Any other
        # answer would mean it defaulted -- which is the one thing spec 3.1 forbids.
        assert row[1] == "UNKNOWN"

        cur.execute(
            """
            SELECT count(*) FROM uw_scan.macro_domain_state_evidence
            WHERE state_id = %s
            """,
            (result.state_id,),
        )
        assert cur.fetchone()[0] > 0

        # Confidence is deliberately NOT asserted low here. ``freshness_for`` measures
        # when we LEARNED a value, and we learned all of this a moment ago, so a high
        # confidence is correct. What must not be invisible is that the newest print is
        # months old -- and that is what this term exists to say.
        cur.execute(
            """
            SELECT confidence_reasons_jsonb FROM uw_scan.macro_domain_states
            WHERE state_id = %s
            """,
            (result.state_id,),
        )
        reasons = cur.fetchone()[0]
        age = next(r for r in reasons if r["term"] == "anchor_period_age_days")
        assert Decimal(str(age["value"])) > 30, (
            "the fixture's newest gold print is 2025-12-31; a small period age here "
            "would mean the term is reading the retrieval clock too"
        )


def test_state_records_dependency_edges_on_its_upstreams(seeded_db_empty_cards):
    """Gold is the terminal node: its edges are what make the chain traversable."""
    settings = _settings()
    _ingest(settings)
    as_of = datetime.now(UTC)

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = _repo(conn)
        upstream_id = _seed_upstream_state(repo, conn, "policy_rates", as_of)
        result = macro_gold_state_job(repo, as_of=as_of)

    assert result.status == "ok", result.error_message

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT upstream_state_id, causal_role
            FROM uw_scan.macro_domain_state_dependencies
            WHERE downstream_state_id = %s
            """,
            (result.state_id,),
        )
        edges = cur.fetchall()

    assert (upstream_id, "decomposition_component") in edges


def _seed_upstream_state(
    repo: Repository, conn: psycopg.Connection, domain: str, as_of: datetime
) -> int:
    """One real upstream answer, written through the same store the jobs use."""
    from uw_scan.macro.contracts import (
        ConfidenceTerm,
        EvidenceRef,
        MacroDomainState,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT obs_id, series_id, period_end, available_at
            FROM uw_scan.macro_observations
            WHERE domain = 'gold' LIMIT 1
            """
        )
        obs = cur.fetchone()
    assert obs is not None, "ingest must have run first"

    state = MacroDomainState(
        domain=domain,
        state="ON_HOLD",
        direction="FLAT",
        velocity=(),
        confidence=Decimal("1"),
        confidence_reasons=(
            ConfidenceTerm(term="seeded", value=Decimal(1), detail="test upstream"),
        ),
        contradictions=(),
        factors=(),
        evidence_refs=(
            EvidenceRef(
                series_id=obs[1],
                period_end=obs[2],
                # macro_observations carries no causal_role: the role is a property of
                # the CONTRACT that read the row, not of the row, which is what lets
                # gold and rates cite the same observation in different roles.
                causal_role="decomposition_component",
                available_at=obs[3],
                obs_id=obs[0],
            ),
        ),
        engine_version="test/1",
        inputs_hash="d" * 64,
        # The SAME instant, not an earlier one. The evidence guard admits equality
        # (``available_at <= as_of``) and these observations were retrieved moments ago,
        # so backdating the upstream by even a minute makes it cite evidence from its
        # own future -- which the store refuses, correctly.
        as_of=as_of,
    )
    state_id = repo.insert_macro_domain_state(state, computed_at=as_of)
    conn.commit()
    return int(state_id)
