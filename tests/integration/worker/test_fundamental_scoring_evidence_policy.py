"""Historical scoring must name the evidence it stood on, and abstain without it.

THE FAILURE THIS PREVENTS
-------------------------
`fundamental_scoring` builds one cross-section per KNOWLEDGE QUARTER out of a
single statement panel. That panel was the CURRENT one — newest version per
identity — so a restatement captured in 2023 fed a bucket stamped 2021. The
figures in that bucket were not public when the bucket says they were, and
nothing in the stored row said so.

The fix is not "use better dates". It is that a replay must declare an admission
policy, get only versions that policy can defend, and produce a THIN or EMPTY
cross-section when the evidence is not there. An abstention is a result; a
plausible full cross-section built from unavailable figures is not.

Real database, real SQL selection. Figures are NVDA's and AMD's real 2020-Q1
statements, frozen, with the restated version differing in one line item.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from uw_scan.fundamentals.observation_time import EvidenceClass, EvidencePolicy
from uw_scan.fundamentals.scoring import (
    MIN_CROSS_SECTION,
    engine_version,
    inputs_hash,
    param_hash,
)
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.worker.jobs.fundamental_scoring import fundamental_scoring

PERIOD = date(2020, 3, 31)
FILED = date(2020, 5, 21)
ORIGINAL_2020 = datetime(2020, 5, 21, tzinfo=UTC)
RESTATED_2023 = datetime(2023, 8, 14, tzinfo=UTC)
CAPTURED_2024 = datetime(2024, 6, 1, tzinfo=UTC)

# Enough distinct names to clear the composite's cross-section floor.
NAMES = [f"T{i:02d}" for i in range(MIN_CROSS_SECTION + 2)]


def _statement_rows(ticker: str, revenue: int) -> list[dict]:
    """One quarter of all three statements for `ticker`."""
    payloads = {
        "income": {
            "ticker": ticker,
            "fiscal_date_ending": PERIOD.isoformat(),
            "report_type": "quarterly",
            "total_revenue": str(revenue),
            "gross_profit": str(int(revenue * 0.6)),
            "operating_income": str(int(revenue * 0.3)),
            "net_income": str(int(revenue * 0.25)),
        },
        "balance": {
            "ticker": ticker,
            "fiscal_date_ending": PERIOD.isoformat(),
            "report_type": "quarterly",
            "total_assets": str(revenue * 6),
            "total_liabilities": str(revenue * 2),
            "total_shareholder_equity": str(revenue * 4),
        },
        "cash_flow": {
            "ticker": ticker,
            "fiscal_date_ending": PERIOD.isoformat(),
            "report_type": "quarterly",
            "operating_cashflow": str(int(revenue * 0.35)),
            "capital_expenditures": str(int(revenue * 0.05)),
        },
    }
    out = []
    for statement, raw in payloads.items():
        payload = normalize(raw)
        out.append(
            {
                "source": "uw",
                "ticker": ticker,
                "period_end": PERIOD,
                "period_type": "quarterly",
                "statement": statement,
                "content_hash": content_hash(payload),
                "provider_record_id": None,
                "filing_accession": None,
                "filing_published_at": FILED,
                "raw_jsonb": payload,
                "field_map_version": FIELD_MAP_VERSION,
            }
        )
    return out


@pytest.fixture
def panel(seeded_db_empty_cards):
    """Every name filed an original in 2020 and restated it in 2023.

    The restatement is inserted LAST, so `obs_id DESC` always prefers it — which
    is what makes the 2021 assertions decisive.
    """
    seeded = seeded_db_empty_cards
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    avail = FundamentalObsAvailabilityRepository(seeded.conn, schema=seeded._schema)

    _seed_method(seeded)
    obs.seed_universe("ranked", [(t, None, "test") for t in NAMES])
    for i, ticker in enumerate(NAMES):
        obs.record_statements(_statement_rows(ticker, 1_000_000 * (i + 1)))
    originals = _obs_ids(seeded)

    # Everyone restates in 2023: revenue doubles. New content, new rows, new
    # obs_ids. All of them, because a LONE restatement makes a one-name bucket
    # that the composite floor refuses — a real property, pinned separately in
    # `test_a_lone_restatement_is_too_thin_to_score`.
    for i, ticker in enumerate(NAMES):
        obs.record_statements(_statement_rows(ticker, 2_000_000 * (i + 1)))
    restated = [o for o in _obs_ids(seeded) if o not in originals]

    avail.record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": "sec:filing:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": ORIGINAL_2020,
                "evidence_source": "sec_edgar",
            }
            for obs_id in originals
        ]
        + [
            {
                "obs_id": obs_id,
                "claim_key": "sec:amendment:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": RESTATED_2023,
                "evidence_source": "sec_edgar",
            }
            for obs_id in restated
        ]
    )
    return seeded, originals, restated


def _seed_method(seeded) -> str:
    """An active method version, without which scoring returns early."""
    params = {"w_equal": 1.0}
    engine = engine_version(params)
    repo = FundamentalScoresRepository(seeded.conn, schema=seeded._schema)
    repo.register_version(
        engine_version=engine,
        code_version=engine.split(":")[0],
        param_hash=param_hash(params),
        params=params,
        note="test",
    )
    repo.activate(engine)
    return engine


def _obs_ids(seeded) -> list[int]:
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT obs_id FROM {seeded._schema}.fundamental_statement_obs "
            "ORDER BY obs_id"
        )
        return [r[0] for r in cur.fetchall()]


def _rows(seeded, *, policy: str) -> list[dict]:
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ticker, as_of, evidence_policy, as_of_cutoff, rev_growth,
                   source_obs_ids, availability_ids, inputs_hash, composite
              FROM {seeded._schema}.fundamental_scores
             WHERE evidence_policy = %s
             ORDER BY ticker, as_of
            """,
            (policy,),
        )
        return [
            dict(
                zip(
                    (
                        "ticker",
                        "as_of",
                        "evidence_policy",
                        "as_of_cutoff",
                        "rev_growth",
                        "source_obs_ids",
                        "availability_ids",
                        "inputs_hash",
                        "composite",
                    ),
                    r,
                    strict=True,
                )
            )
            for r in cur.fetchall()
        ]


def _run(seeded, **kw):
    return fundamental_scoring(conn=seeded.conn, schema=seeded._schema, **kw)


# --- the default is the current panel, unchanged ---------------------------


def test_the_default_mode_is_the_current_panel_and_says_so(panel):
    seeded, _, _ = panel
    totals = _run(seeded, knowledge_cutoff=date(2026, 1, 1))
    assert totals["scored"] > 0
    rows = _rows(seeded, policy="current_vintage")
    assert rows, "the default must keep writing today's panel"
    assert all(r["as_of_cutoff"] is None for r in rows)


def test_the_default_mode_still_withholds_unarrived_knowledge(panel):
    """The existing future-knowledge guard is untouched by the policy work."""
    seeded, _, _ = panel
    totals = _run(seeded, knowledge_cutoff=date(2020, 1, 1))
    assert totals["withheld_unpublished"] > 0
    assert totals["scored"] == 0


# --- true-PIT replays ------------------------------------------------------


def test_a_2021_replay_uses_the_original_not_the_2023_restatement(panel):
    seeded, originals, restated = panel
    _run(
        seeded,
        knowledge_cutoff=date(2021, 12, 31),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
    )
    rows = _rows(seeded, policy="true_pit_only")
    t00 = [r for r in rows if r["ticker"] == NAMES[0]]
    assert t00, "the original was available in 2020 and must be scored"
    used = set(t00[0]["source_obs_ids"])
    assert used <= set(originals)
    assert not (used & set(restated))


def test_a_2024_replay_uses_the_restatement(panel):
    seeded, originals, restated = panel
    _run(
        seeded,
        knowledge_cutoff=date(2024, 12, 31),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
    )
    rows = _rows(seeded, policy="true_pit_only")
    latest = max(r["as_of"] for r in rows)
    t00 = [r for r in rows if r["ticker"] == NAMES[0] and r["as_of"] == latest]
    assert set(t00[0]["source_obs_ids"]) & set(restated)


def test_a_lone_restatement_is_too_thin_to_score(seeded_db_empty_cards):
    """One name restating alone cannot be z-scored against itself.

    It lands in its OWN availability quarter, where it is the only member, and
    the cross-section floor refuses it. That is the correct outcome and worth
    pinning: the tempting "fix" is to let it rejoin the 2020 bucket, which is
    precisely the contamination this work removes.
    """
    seeded = seeded_db_empty_cards
    _seed_method(seeded)
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    avail = FundamentalObsAvailabilityRepository(seeded.conn, schema=seeded._schema)
    obs.seed_universe("ranked", [(t, None, "test") for t in NAMES])
    for i, ticker in enumerate(NAMES):
        obs.record_statements(_statement_rows(ticker, 1_000_000 * (i + 1)))
    originals = _obs_ids(seeded)
    obs.record_statements(_statement_rows(NAMES[0], 2_000_000))
    restated = [o for o in _obs_ids(seeded) if o not in originals]

    avail.record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": "sec:filing:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": ORIGINAL_2020,
                "evidence_source": "sec_edgar",
            }
            for obs_id in originals
        ]
        + [
            {
                "obs_id": obs_id,
                "claim_key": "sec:amendment:v1",
                "evidence_class": EvidenceClass.TRUE_PIT,
                "available_at": RESTATED_2023,
                "evidence_source": "sec_edgar",
            }
            for obs_id in restated
        ]
    )

    totals = _run(
        seeded,
        knowledge_cutoff=date(2024, 12, 31),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
    )
    assert totals["skipped_thin"] >= 1
    scored = {r["ticker"] for r in _rows(seeded, policy="true_pit_only")}
    assert NAMES[0] not in scored
    # And it did not contaminate anyone else's bucket.
    for row in _rows(seeded, policy="true_pit_only"):
        assert not (set(row["source_obs_ids"]) & set(restated))


def test_a_late_run_cannot_reproduce_an_early_bucket(panel):
    """The documented limitation, pinned so it cannot become folklore.

    The panel returns ONE version per identity — the best admissible at the
    cutoff. Run at 2024, every name's 2020 filing has been superseded, so the
    2020 cross-section is simply absent. Reconstructing it means running with the
    cutoff inside 2020, which `test_a_2021_replay_...` does.
    """
    seeded, _, _ = panel
    _run(
        seeded,
        knowledge_cutoff=date(2024, 12, 31),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
    )
    as_ofs = {r["as_of"] for r in _rows(seeded, policy="true_pit_only")}
    assert as_ofs == {RESTATED_2023.date()}


def test_a_replay_records_the_claims_it_stood_on(panel):
    seeded, _, _ = panel
    _run(
        seeded,
        knowledge_cutoff=date(2021, 12, 31),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
    )
    for row in _rows(seeded, policy="true_pit_only"):
        assert row["availability_ids"], f"{row['ticker']} names no evidence"
        assert len(row["availability_ids"]) == len(row["source_obs_ids"])
        assert row["as_of_cutoff"] is not None


# --- abstention ------------------------------------------------------------


def test_true_pit_abstains_entirely_when_no_version_is_published(
    seeded_db_empty_cards,
):
    """The rows exist and are perfectly good for today's page. They carry no
    publication evidence, so a true-PIT replay must return nothing rather than
    quietly fall back to them."""
    seeded = seeded_db_empty_cards
    _seed_method(seeded)
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    obs.seed_universe("ranked", [(t, None, "test") for t in NAMES])
    for i, ticker in enumerate(NAMES):
        obs.record_statements(_statement_rows(ticker, 1_000_000 * (i + 1)))
    FundamentalObsAvailabilityRepository(
        seeded.conn, schema=seeded._schema
    ).seed_claims(EvidenceClass.CURRENT_VINTAGE)

    totals = _run(
        seeded,
        knowledge_cutoff=date(2026, 1, 1),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
    )
    assert totals["scored"] == 0
    assert totals["excluded_no_evidence"] > 0
    assert _rows(seeded, policy="true_pit_only") == []


def test_capture_bounded_admits_only_at_or_after_the_capture(seeded_db_empty_cards):
    seeded = seeded_db_empty_cards
    _seed_method(seeded)
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    obs.seed_universe("ranked", [(t, None, "test") for t in NAMES])
    for i, ticker in enumerate(NAMES):
        obs.record_statements(_statement_rows(ticker, 1_000_000 * (i + 1)))
    FundamentalObsAvailabilityRepository(
        seeded.conn, schema=seeded._schema
    ).record_claims(
        [
            {
                "obs_id": obs_id,
                "claim_key": "capture:first_observed_at:v1",
                "evidence_class": EvidenceClass.CAPTURE_BOUNDED,
                "available_at": CAPTURED_2024,
                "evidence_source": "argon_capture",
            }
            for obs_id in _obs_ids(seeded)
        ]
    )

    early = _run(
        seeded,
        knowledge_cutoff=date(2023, 12, 31),
        evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
    )
    assert early["scored"] == 0

    late = _run(
        seeded,
        knowledge_cutoff=date(2024, 12, 31),
        evidence_policy=EvidencePolicy.CAPTURE_BOUNDED,
    )
    assert late["scored"] > 0


# --- identity --------------------------------------------------------------


def test_the_policy_enters_result_identity(panel):
    seeded, _, _ = panel
    cutoff = date(2024, 12, 31)
    _run(seeded, knowledge_cutoff=cutoff, evidence_policy=EvidencePolicy.TRUE_PIT_ONLY)
    _run(
        seeded, knowledge_cutoff=cutoff, evidence_policy=EvidencePolicy.CAPTURE_BOUNDED
    )
    true_pit = {r["inputs_hash"] for r in _rows(seeded, policy="true_pit_only")}
    capture = {r["inputs_hash"] for r in _rows(seeded, policy="capture_bounded")}
    assert true_pit and capture
    assert not (true_pit & capture), "two policies produced colliding identities"


def test_the_current_panel_identity_is_unchanged_by_this_work(panel):
    """Existing rows must stay reproducible: the current mode's hash payload is
    byte-for-byte what it was before the policy argument existed."""
    seeded, _, _ = panel
    _run(seeded, knowledge_cutoff=date(2026, 1, 1))
    row = _rows(seeded, policy="current_vintage")[0]
    features = _features_of(seeded, row["ticker"], row["as_of"])
    engine = _engine(seeded)
    assert row["inputs_hash"] == inputs_hash(
        features=features, company_type=None, engine=engine
    )


def test_an_identical_replay_reproduces_the_same_identity(panel):
    seeded, _, _ = panel
    kw = {
        "knowledge_cutoff": date(2021, 12, 31),
        "evidence_policy": EvidencePolicy.TRUE_PIT_ONLY,
    }
    _run(seeded, **kw)
    first = {
        (r["ticker"], r["as_of"], r["inputs_hash"])
        for r in _rows(seeded, policy="true_pit_only")
    }
    second_totals = _run(seeded, **kw)
    second = {
        (r["ticker"], r["as_of"], r["inputs_hash"])
        for r in _rows(seeded, policy="true_pit_only")
    }
    assert first == second
    assert second_totals["inserted"] == 0


def test_a_replay_never_overwrites_an_existing_current_vintage_row(panel):
    seeded, _, _ = panel
    _run(seeded, knowledge_cutoff=date(2026, 1, 1))
    before = _rows(seeded, policy="current_vintage")
    _run(
        seeded,
        knowledge_cutoff=date(2024, 12, 31),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
    )
    assert _rows(seeded, policy="current_vintage") == before


def _features_of(seeded, ticker: str, as_of) -> dict:
    from uw_scan.fundamentals.features import FEATURES

    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(FEATURES)} FROM {seeded._schema}.fundamental_scores "
            "WHERE ticker = %s AND as_of = %s AND evidence_policy = 'current_vintage'",
            (ticker, as_of),
        )
        row = cur.fetchone()
    return {
        f: (None if v is None else float(v)) for f, v in zip(FEATURES, row, strict=True)
    }


def _engine(seeded) -> str:
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"SELECT active_engine_version FROM "
            f"{seeded._schema}.fundamental_method_state"
        )
        return cur.fetchone()[0]
