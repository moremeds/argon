"""The fundamentals industry desk read layer (Task 13, spec §2/§3/§4).

Six endpoints over the warm store, zero vendor calls. The tests below split
into two kinds and BOTH are load-bearing:

1. Positive-path wiring over frozen real data — does the join actually reach
   the right rows, in the right order, with absence rendered as absence.
2. ANTI-REQUIREMENT tests. The desk LISTS; it must never RANK. Measured
   basis: the cross-sectional composite is a disguised growth screen
   (correlates 0.89 with its own growth input) and cross-sectional VALUE
   measured INVERTED in this universe (`book_to_price` IC -0.0365, t -2.32),
   while own-history value is the one thing that works (`sales_to_ev`
   within-ticker IC +0.0744, t 5.77). A `sort` parameter, an edge/arrow field
   on the profit pool, or a chain-level aggregate over own-history
   percentiles would each ship a refuted claim under a validated one's name,
   and nothing about the response SHAPE would show it. These tests are the
   shape.

FIXTURE PROVENANCE — every figure below is real and frozen; none is invented
--------------------------------------------------------------------------
Upcoming prints, verified live via Unusual Whales `get_upcoming_earnings`
on 2026-08-28 (`report_date` / `report_time`):

    AVGO 2026-09-02 postmarket   -> session 'afterhours'
    JPM  2026-10-13 unknown      -> session NULL (the ~2% UW never classifies)
    LITE 2026-11-03 unknown      -> session NULL
    COHR 2026-11-04 unknown      -> session NULL
    NVDA 2026-11-18 unknown      -> session NULL
    MRVL 2026-08-27 postmarket   -> already PAST; seeded to prove the floor

Earnings reactions — the same two real NVDA prints Task 6's fixture froze,
with the mini warm store's own `daily_ohlc` closes:

    NVDA 2026-05-20  223.4700 -> 219.5100
    NVDA 2026-02-25  195.5600 -> 184.8900

(Both reproduce UW's own `last_1d_reactions` for NVDA to 6dp: -0.0177205,
-0.0545613 — a cross-check, not a second source.)

Implied move — the same real AVGO 2026-08-26 `option_surface_grid_daily`
rows Task 7's fixture froze: spot 358.3500, covering expiry 2026-09-04,
nearest strike 357.5, call_iv 0.736661443735852, put_iv 0.706997006724508.

Statement figures — real `raw_jsonb` values from `uw_scan.fundamental_
statement_obs` on `option_wizard_local`, queried 2026-08-28:

    ticker  period_end   total_revenue   gross_profit   prior-year revenue
    NVDA    2026-04-30   81615000000     61157000000    44062000000
    AVGO    2026-04-30   22187000000     14919000000    15004000000
    MRVL    2026-04-30    2417800000      1260800000     1895300000
    LITE    2026-06-30    1006300000       477300000      480700000
    COHR    2026-06-30    2045500000      (none filed)   1529436000

COHR's June quarter genuinely carries NO `gross_profit` — that is why it is
here: it is the honest-absence case, and it must reach the caller as a named
missing ticker rather than as a zero.

Valuation anchors and scores — real rows from `option_wizard_local` under
engine `fundamentals-v2:77aea364`:

    COHR as_of 2026-04-14 spot 313.42 percentile 0.05 (ebitda_to_ev)
    MRVL as_of 2026-05-15 spot 176.89 percentile 0.75 (ebitda_to_ev)
    AVGO/NVDA/LITE/JPM   band REFUSED — every level and the percentile null

    scores: AVGO/MRVL/NVDA at as_of 2026-06-25 (knowledge_date 2026-06-14,
    filing_date_known FALSE — the period_end + FALLBACK_LAG_DAYS estimate);
    COHR/LITE at as_of 2026-08-21 (knowledge_date 2026-08-14 / 2026-08-17,
    filing_date_known TRUE). That real split is what makes the
    Optical-Communication chain straddle two cross-section buckets and what
    gives the rollup both polarities of `knowledge_date_known`.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.fundamentals.features import FALLBACK_LAG_DAYS, FEATURES
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.earnings_reactions import EarningsReactionsRepository
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.fundamentals_desk import FundamentalsDeskRepository
from uw_scan.storage.implied_move import ImpliedMoveRepository
from uw_scan.storage.research_events import ResearchEventsRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository

ENGINE = "fundamentals-v2:77aea364"
TAXONOMY = "argon-research-v1"
APPROVER = "argon-research"

OPTICAL = "Optical-Communication"
GPU = "Computer/GPU"
BANKS = "Banks"

# ---------------------------------------------------------------- taxonomy

#: (domain, chain, layer, layer_rank, members). Mirrors the shape the
#: production seed writes — Optical-Communication's real layer ladder plus one
#: `ai_infrastructure` chain and one `unclassified` chain that must NOT reach
#: the ai-semi desk.
CHAINS: list[tuple[str, str, str, int, list[str]]] = [
    ("optical_communication", OPTICAL, "Upstream-Components", 10, ["COHR", "LITE"]),
    ("optical_communication", OPTICAL, "Semi-DSP-Switch", 20, ["AVGO", "MRVL"]),
    # COHR and LITE again, one layer down: `chain_membership` is
    # (chain, layer, ticker)-grained, so each is TWO rows and must count once.
    ("optical_communication", OPTICAL, "Module-Transceiver", 30, ["COHR", "LITE"]),
    ("ai_infrastructure", GPU, "Compute-Silicon", 40, ["NVDA"]),
    ("unclassified", BANKS, "L3", 0, ["JPM"]),
]

# ---------------------------------------------------------------- calendar

#: (ticker, report_date, session) — real, UW-verified 2026-08-28.
PRINTS = [
    ("MRVL", date(2026, 8, 27), "afterhours"),  # already past
    ("AVGO", date(2026, 9, 2), "afterhours"),
    ("JPM", date(2026, 10, 13), None),
    ("LITE", date(2026, 11, 3), None),
    ("COHR", date(2026, 11, 4), None),
    ("NVDA", date(2026, 11, 18), None),
]

#: (report_date, close_before_date, close_before, close_after_date, close_after)
NVDA_REACTIONS = [
    (date(2026, 5, 20), date(2026, 5, 20), 223.4700, date(2026, 5, 21), 219.5100),
    (date(2026, 2, 25), date(2026, 2, 25), 195.5600, date(2026, 2, 26), 184.8900),
]

# ------------------------------------------------------------ implied move

AVGO_SPOT = 358.3500
AVGO_STRIKE = 357.5
AVGO_CALL_IV = 0.736661443735852
AVGO_PUT_IV = 0.706997006724508
AVGO_MARKET_DATE = date(2026, 8, 26)
AVGO_EXPIRY = date(2026, 9, 4)
#: Brenner-Subrahmanyam ATM-straddle approximation, the same constant
#: `worker/jobs/implied_move_snapshot.py` applies. Written out here rather
#: than imported so the fixture states its own arithmetic.
AVGO_ATM_IV = (AVGO_CALL_IV + AVGO_PUT_IV) / 2
AVGO_MOVE_PCT = (
    0.7978845608028654
    * AVGO_ATM_IV
    * math.sqrt((AVGO_EXPIRY - AVGO_MARKET_DATE).days / 365.0)
)

# ----------------------------------------------------------------- rollup

_M = 1  # figures below are already whole units


@dataclass(frozen=True)
class _Rollup:
    ticker: str
    period_end: date
    revenue: float
    gross_profit: float | None
    prior_revenue: float
    knowledge_date: date
    knowledge_date_known: bool

    @property
    def gross_margin(self) -> float | None:
        if self.gross_profit is None:
            return None
        return self.gross_profit / self.revenue

    @property
    def rev_yoy(self) -> float:
        return self.revenue / self.prior_revenue - 1


ROLLUPS = [
    _Rollup(
        "NVDA",
        date(2026, 4, 30),
        81615000000,
        61157000000,
        44062000000,
        date(2026, 4, 30) + timedelta(days=FALLBACK_LAG_DAYS),
        False,
    ),
    _Rollup(
        "AVGO",
        date(2026, 4, 30),
        22187000000,
        14919000000,
        15004000000,
        date(2026, 4, 30) + timedelta(days=FALLBACK_LAG_DAYS),
        False,
    ),
    _Rollup(
        "MRVL",
        date(2026, 4, 30),
        2417800000,
        1260800000,
        1895300000,
        date(2026, 4, 30) + timedelta(days=FALLBACK_LAG_DAYS),
        False,
    ),
    _Rollup(
        "LITE",
        date(2026, 6, 30),
        1006300000,
        477300000,
        480700000,
        date(2026, 8, 17),
        True,
    ),
    _Rollup(
        "COHR", date(2026, 6, 30), 2045500000, None, 1529436000, date(2026, 8, 14), True
    ),
]
ROLLUP_BY_TICKER = {r.ticker: r for r in ROLLUPS}

# ---------------------------------------------------------------- anchors

#: ticker, as_of, company_type, method, buy_below, spot, spot_percentile
ANCHORS = [
    (
        "COHR",
        date(2026, 4, 14),
        "power_infra",
        "ebitda_to_ev",
        68.6331336427784,
        313.42,
        0.05,
    ),
    (
        "MRVL",
        date(2026, 5, 15),
        "power_infra",
        "ebitda_to_ev",
        143.224276335416,
        176.89,
        0.75,
    ),
    # REFUSED bands — real rows, every level and the percentile null.
    ("AVGO", date(2026, 4, 14), "chips_cyclical", "sales_to_ev", None, 380.78, None),
    ("NVDA", date(2026, 4, 14), "platform_scale", "fcf_yield", None, 196.51, None),
    ("LITE", date(2026, 5, 15), "power_infra", "ebitda_to_ev", None, 970.70, None),
    ("JPM", date(2026, 5, 15), "financials", None, None, 297.81, None),
]

# ----------------------------------------------------------------- scores

#: ticker, as_of (the cross-section id), period_end, knowledge_date,
#: filing_date_known, composite
SCORES = [
    (
        "AVGO",
        date(2026, 6, 25),
        date(2026, 4, 30),
        date(2026, 6, 14),
        False,
        0.0288025593265898,
    ),
    (
        "MRVL",
        date(2026, 6, 25),
        date(2026, 4, 30),
        date(2026, 6, 14),
        False,
        -0.0268221516488244,
    ),
    (
        "NVDA",
        date(2026, 6, 25),
        date(2026, 4, 30),
        date(2026, 6, 14),
        False,
        0.308186497649842,
    ),
    (
        "COHR",
        date(2026, 8, 21),
        date(2026, 6, 30),
        date(2026, 8, 14),
        True,
        -0.100199982150607,
    ),
    (
        "LITE",
        date(2026, 8, 21),
        date(2026, 6, 30),
        date(2026, 8, 17),
        True,
        -0.159059040666847,
    ),
]


# =========================================================== seed helpers


def _tax(seeded) -> ResearchTaxonomyRepository:
    return ResearchTaxonomyRepository(seeded.conn, schema=seeded._schema)


def _seed_taxonomy(seeded) -> None:
    tax = _tax(seeded)
    tax.publish_version(TAXONOMY, note="test", activate=True)
    tax.define_chains(
        TAXONOMY,
        [
            {"domain": dom, "chain": chain, "layer": layer, "layer_rank": rank}
            for dom, chain, layer, rank, _ in CHAINS
        ],
    )
    for _dom, chain, layer, _rank, members in CHAINS:
        for ticker in members:
            tax.add_membership(
                TAXONOMY,
                chain=chain,
                layer=layer,
                ticker=ticker,
                evidence_class="analyst",
                approved_by=APPROVER,
            )


def _seed_engine(seeded) -> None:
    scores = FundamentalScoresRepository(seeded.conn, schema=seeded._schema)
    scores.register_version(
        engine_version=ENGINE,
        code_version="fundamentals-v2",
        param_hash="77aea364",
        params=dict.fromkeys(FEATURES, 1.0),
        note="test",
    )
    scores.activate(ENGINE)
    scores.insert_scores(
        [
            {
                "ticker": t,
                "as_of": as_of,
                "engine_version": ENGINE,
                "inputs_hash": f"{t}-{as_of}",
                "period_end": period_end,
                "knowledge_date": knowledge_date,
                "filing_date_known": known,
                "composite": composite,
                "features_present": 4,
                "source_obs_ids": [],
                "as_of_cutoff": None,
            }
            for t, as_of, period_end, knowledge_date, known, composite in SCORES
        ]
    )


def _seed_anchors(seeded) -> None:
    FundamentalAnchorsRepository(seeded.conn, schema=seeded._schema).insert_anchors(
        [
            {
                "ticker": t,
                "as_of": as_of,
                "engine_version": ENGINE,
                "inputs_hash": f"{t}-{as_of}",
                "company_type": ctype,
                "method": method,
                "buy_below": buy_below,
                "observe_low": None,
                "observe_mid": None,
                "observe_high": None,
                "risk_above": None,
                "spot": spot,
                "spot_percentile": pct,
                "history_quarters": 20 if pct is not None else 0,
                "confidence": "high" if pct is not None else "none",
                "confidence_reasons_jsonb": [],
                "inputs_jsonb": {},
                "source_obs_ids": [],
            }
            for t, as_of, ctype, method, buy_below, spot, pct in ANCHORS
        ]
    )


def _seed_calendar(seeded) -> None:
    EarningsCalendarRepository(seeded.conn, schema=seeded._schema).upsert_rows(
        [
            {
                "ticker": t,
                "report_date": d,
                "session": s,
                "source": "uw_calendar" if s else "statement_obs",
            }
            for t, d, s in PRINTS
        ]
    )


def _seed_reactions(seeded) -> None:
    EarningsReactionsRepository(seeded.conn, schema=seeded._schema).upsert_rows(
        [
            {
                "ticker": "NVDA",
                "report_date": report_date,
                "session": "afterhours",
                "close_before_date": before_date,
                "close_before": Decimal(str(before)),
                "close_after_date": after_date,
                "close_after": Decimal(str(after)),
                "pct_move": Decimal(str(after)) / Decimal(str(before)) - 1,
            }
            for report_date, before_date, before, after_date, after in NVDA_REACTIONS
        ]
    )


def _seed_implied_move(seeded) -> None:
    ImpliedMoveRepository(seeded.conn, schema=seeded._schema).upsert_rows(
        [
            {
                "ticker": "AVGO",
                "market_date": AVGO_MARKET_DATE,
                "report_date": date(2026, 9, 2),
                "expiry": AVGO_EXPIRY,
                "strike": AVGO_STRIKE,
                "atm_iv": AVGO_ATM_IV,
                "iv_basis": "both",
                "spot": AVGO_SPOT,
                "implied_move_pct": AVGO_MOVE_PCT,
                "implied_move_usd": AVGO_MOVE_PCT * AVGO_SPOT,
            }
        ]
    )


def _seed_rollup(seeded) -> None:
    FundamentalsDeskRepository(seeded.conn, schema=seeded._schema).upsert_rows(
        [
            {
                "ticker": r.ticker,
                "period_end": r.period_end,
                "rev_yoy": r.rev_yoy,
                "gross_margin": r.gross_margin,
                "gross_profit": r.gross_profit,
                "knowledge_date": r.knowledge_date,
                "knowledge_date_known": r.knowledge_date_known,
            }
            for r in ROLLUPS
        ]
    )


def _seed_events(seeded) -> None:
    """One filing that fired BOTH `statement_published` and `sec_filing` on
    the same (ticker, occurred_at) — the dedupe case — plus a band entry on a
    different name and one event on the out-of-section `Banks` member."""
    repo = ResearchEventsRepository(seeded.conn, schema=seeded._schema)
    repo.register_classes(
        [
            {"event_class": c, "status": "live", "rationale": "test"}
            for c in (
                "statement_published",
                "sec_filing",
                "band_entry",
                "band_exit",
                "implied_move_shift",
                "coverage_change",
                "bucket_flip",
            )
        ]
    )
    repo.record_events(
        [
            {
                "event_class": "statement_published",
                "ticker": "COHR",
                "occurred_at": date(2026, 8, 14),
                "first_known_at": date(2026, 8, 21),
                "title": "COHR 2026-06-30 statements published",
                "detail": {"period_end": "2026-06-30"},
                "source_kind": "uw",
                "source_ref": "COHR:2026-06-30",
            },
            {
                "event_class": "sec_filing",
                "ticker": "COHR",
                "occurred_at": date(2026, 8, 14),
                "first_known_at": date(2026, 8, 21),
                "title": "COHR 10-Q filed",
                "detail": {"form": "10-Q"},
                "source_kind": "sec",
                "source_ref": "COHR:10-Q:2026-08-14",
            },
            {
                "event_class": "band_entry",
                "ticker": "MRVL",
                "occurred_at": date(2026, 5, 15),
                "first_known_at": date(2026, 5, 16),
                "title": "MRVL entered its own buy zone",
                "detail": {"spot": "176.89"},
                "source_kind": "valuation_anchors",
                "source_ref": "MRVL:2026-05-15",
            },
            {
                "event_class": "statement_published",
                "ticker": "JPM",
                "occurred_at": date(2026, 7, 14),
                "first_known_at": date(2026, 7, 20),
                "title": "JPM 2026-06-30 statements published",
                "detail": {},
                "source_kind": "uw",
                "source_ref": "JPM:2026-06-30",
            },
        ]
    )


def _seed_nvda_statements(seeded) -> None:
    """The same frozen ten-quarter real NVDA panel `test_feature_details.py`
    built for `build_features` — reused rather than copied so the underwriting
    endpoint is exercised over figures another test already owns."""
    from tests.unit.fundamentals.test_feature_details import _BS, _CF, _INC

    rows = []
    for period in _INC:
        for statement, raw in (
            ("income", _INC[period]),
            ("balance", _BS[period]),
            ("cash_flow", _CF[period]),
        ):
            payload = normalize(
                {
                    **raw,
                    "ticker": "NVDA",
                    "fiscal_date_ending": period,
                    "report_type": "quarterly",
                }
            )
            rows.append(
                {
                    "source": "uw",
                    "ticker": "NVDA",
                    "period_end": date.fromisoformat(period),
                    "period_type": "quarterly",
                    "statement": statement,
                    "content_hash": content_hash(payload),
                    "provider_record_id": None,
                    "filing_accession": None,
                    # NVDA's real 2026-04-30 10-Q filing date; the rest
                    # deliberately carry none.
                    "filing_published_at": (
                        date(2026, 5, 20) if period == "2026-04-30" else None
                    ),
                    "raw_jsonb": payload,
                    "field_map_version": FIELD_MAP_VERSION,
                }
            )
    FundamentalObsRepository(seeded.conn, schema=seeded._schema).record_statements(rows)


@dataclass(frozen=True)
class _Desk:
    chain: str
    tickers: list[str]


@pytest.fixture
def seeded_desk(seeded_db_empty_cards):
    _seed_taxonomy(seeded_db_empty_cards)
    _seed_engine(seeded_db_empty_cards)
    _seed_anchors(seeded_db_empty_cards)
    _seed_calendar(seeded_db_empty_cards)
    _seed_reactions(seeded_db_empty_cards)
    _seed_implied_move(seeded_db_empty_cards)
    _seed_rollup(seeded_db_empty_cards)
    _seed_events(seeded_db_empty_cards)
    _seed_nvda_statements(seeded_db_empty_cards)
    return seeded_db_empty_cards


@pytest.fixture
def desk_client(client, seeded_desk):
    return client


@pytest.fixture
def seeded_two_buckets(seeded_desk) -> _Desk:
    """Optical-Communication's members straddle two real cross-section
    buckets: AVGO/MRVL scored at as_of 2026-06-25, COHR/LITE at 2026-08-21."""
    return _Desk(chain=OPTICAL, tickers=["AVGO", "MRVL", "COHR", "LITE"])


@pytest.fixture
def seeded_dual_layer(seeded_desk) -> _Desk:
    """COHR and LITE each sit in TWO layers of Optical-Communication —
    four DISTINCT tickers across six membership rows."""
    return _Desk(chain=OPTICAL, tickers=["COHR", "LITE", "AVGO", "MRVL"])


def _cell(body: dict, chain: str, metric: str) -> dict:
    return next(
        c for c in body["cells"] if c["chain"] == chain and c["metric"] == metric
    )


# ============================================== anti-requirement guardrails


def test_matrix_response_carries_no_ranking_surface():
    """Spec §3 anti-requirement: no cross-sectional ranking or composite."""
    from uw_scan.models.fundamentals_desk import (
        ChainMetricCell,
        DeskMatrixResponse,
        MemberDot,
    )

    banned = {"rank", "score", "composite", "percentile_rank", "sort"}
    for model in (DeskMatrixResponse, ChainMetricCell, MemberDot):
        assert not banned & set(model.model_fields), model.__name__


def test_calendar_endpoint_rejects_sort_param(desk_client):
    r = desk_client.get(
        "/api/fundamentals/ai-semi/calendar", params={"sort": "implied_move_pct"}
    )
    assert r.status_code == 422  # no sort parameter exists, by design


def test_every_desk_endpoint_rejects_an_undeclared_param(desk_client):
    """The 422 is STRUCTURAL, not a per-endpoint courtesy. FastAPI ignores
    unknown query params by default, so without the router-level guard a
    `?sort=` would 200 and silently do nothing — which reads to a caller as
    "the sort was applied"."""
    for path, params in (
        ("/api/fundamentals/ai-semi/calendar", {"sort": "x"}),
        ("/api/fundamentals/ai-semi/delta", {"order_by": "x"}),
        ("/api/fundamentals/ai-semi/matrix", {"sort": "median"}),
        ("/api/fundamentals/ai-semi/profit-pool", {"rank": "1"}),
        ("/api/fundamentals/ai-semi/limits", {"sort": "x"}),
        (
            "/api/fundamentals/ai-semi/node/underwriting",
            {"chain": OPTICAL, "sort": "dio"},
        ),
    ):
        assert desk_client.get(path, params=params).status_code == 422, path


def test_profit_pool_model_has_no_edge_field():
    from uw_scan.models.fundamentals_desk import ProfitPoolLayer

    banned = {"leads", "lags", "arrow", "edges", "propagation", "read_through"}
    assert not banned & set(ProfitPoolLayer.model_fields)


def test_valuation_percentile_cell_has_no_median(desk_client, seeded_desk):
    """A chain aggregate over own-history percentiles is the banned
    'chain percentile distribution' — dots only (spec §3)."""
    r = desk_client.get("/api/fundamentals/ai-semi/matrix")
    cells = [c for c in r.json()["cells"] if c["metric"] == "valuation_percentile"]
    assert cells, "no valuation_percentile cells at all — the test is vacuous"
    for cell in cells:
        assert cell["median"] is None
        assert cell["dots"]  # the name facts still render


def test_median_is_unweighted_median_of_dots(desk_client, seeded_desk):
    """For metrics that keep a median: it equals the plain median of the
    non-null dot values — never weighted by anything."""
    r = desk_client.get("/api/fundamentals/ai-semi/matrix")
    cell = next(
        c
        for c in r.json()["cells"]
        if c["metric"] == "gross_margin" and c["median"] is not None
    )
    values = [d["value"] for d in cell["dots"] if d["value"] is not None]
    assert len(values) >= 2, "a one-value median cannot distinguish weighting"
    assert cell["median"] == pytest.approx(statistics.median(values))


def test_membership_counts_dedupe_by_ticker(desk_client, seeded_dual_layer):
    """chain_membership is (chain, layer, ticker)-grained — a name in two
    layers is two rows and must count ONCE."""
    r = desk_client.get("/api/fundamentals/ai-semi/matrix")
    cell = _cell(r.json(), seeded_dual_layer.chain, "gross_margin")
    tickers = [d["ticker"] for d in cell["dots"]]
    assert len(tickers) == len(set(tickers))
    assert cell["members_total"] == len(set(seeded_dual_layer.tickers))


def test_rows_only_chain_reaches_both_endpoints(desk_client, seeded_desk):
    """Spec §2 extension contract, made testable: a NEW chain stood up as
    research_chains + chain_membership rows ONLY — no ChainSpec constant, no
    SECTIONS edit, no assembler or router change — must appear on the desk."""
    tax = _tax(seeded_desk)
    tax.define_chains(
        TAXONOMY,
        [
            {
                "domain": "dc_buildout",
                "chain": "Substation/Transformers",
                "layer": "Equipment",
                "layer_rank": 15,
            }
        ],
    )
    for ticker in ("ETN", "PWR"):
        tax.add_membership(
            TAXONOMY,
            chain="Substation/Transformers",
            layer="Equipment",
            ticker=ticker,
            evidence_class="analyst",
            approved_by=APPROVER,
        )

    r = desk_client.get("/api/fundamentals/ai-semi/matrix")
    assert "Substation/Transformers" in r.json()["chains"]
    # `chain` is a QUERY param, never a path segment — a %2F-encoded slash in
    # a FastAPI path param 404s, and most real chain names contain a slash.
    r2 = desk_client.get(
        "/api/fundamentals/ai-semi/node/underwriting",
        params={"chain": "Substation/Transformers"},
    )
    assert r2.status_code == 200


def test_a_slashed_chain_name_round_trips_as_a_query_param(desk_client, seeded_desk):
    """`Optical-Communication` has no slash; `Computer/GPU` does. The node
    endpoint must reach the latter — the reason `chain` is not a path
    segment."""
    r = desk_client.get(
        "/api/fundamentals/ai-semi/node/underwriting", params={"chain": GPU}
    )
    assert r.status_code == 200
    assert {row["ticker"] for row in r.json()} == {"NVDA"}


# ============================================================ section filter


def test_an_unclassified_chain_never_reaches_the_ai_semi_desk(desk_client, seeded_desk):
    """JPM is a member of `Banks`, domain `unclassified`. Before Task 19
    every chain carried `ai_infrastructure` and this filter selected all 38,
    putting Banks on the AI/semi desk."""
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    assert BANKS not in body["chains"]
    assert "JPM" not in {d["ticker"] for c in body["cells"] for d in c["dots"]}

    cal = desk_client.get("/api/fundamentals/ai-semi/calendar").json()
    assert "JPM" not in {row["ticker"] for row in cal["rows"]}

    delta = desk_client.get("/api/fundamentals/ai-semi/delta").json()
    assert "JPM" not in {e["ticker"] for e in delta["events"]}


def test_an_unknown_section_is_404_not_an_empty_desk(desk_client):
    """An empty desk for a section that does not exist is a lie shaped like
    data."""
    assert desk_client.get("/api/fundamentals/biotech/matrix").status_code == 404


# ================================================================= calendar


def _future_prints() -> list[tuple[str, date, str | None]]:
    today = date.today()
    return [p for p in PRINTS if p[1] >= today and p[0] != "JPM"]


def test_calendar_lists_section_prints_in_read_through_order(desk_client, seeded_desk):
    body = desk_client.get("/api/fundamentals/ai-semi/calendar").json()
    expected = _future_prints()
    if not expected:
        pytest.fail(
            "every seeded real print has passed — re-freeze PRINTS from "
            "`get_upcoming_earnings`; this test is otherwise vacuous",
            pytrace=False,
        )
    assert body["section"] == "ai-semi"
    assert body["as_of"] == date.today().isoformat()
    assert {r["ticker"] for r in body["rows"]} == {t for t, _, _ in expected}
    # report_date ASC, then layer_rank ASC — chain order is read-through order.
    keys = [(r["report_date"], r["layer_rank"]) for r in body["rows"]]
    assert keys == sorted(keys)
    # MRVL's real print is in the past and must not appear.
    assert "MRVL" not in {r["ticker"] for r in body["rows"]}


def test_calendar_renders_an_unknown_session_as_null_never_as_a_guess(
    desk_client, seeded_desk
):
    body = desk_client.get("/api/fundamentals/ai-semi/calendar").json()
    by_ticker = {r["ticker"]: r for r in body["rows"]}
    if "COHR" not in by_ticker:
        pytest.skip("COHR's real 2026-11-04 print has passed; re-freeze PRINTS")
    assert by_ticker["COHR"]["session"] is None


def test_calendar_carries_implied_move_and_names_its_absence(desk_client, seeded_desk):
    body = desk_client.get("/api/fundamentals/ai-semi/calendar").json()
    by_ticker = {r["ticker"]: r for r in body["rows"]}
    if "AVGO" in by_ticker:
        assert by_ticker["AVGO"]["implied_move_pct"] == pytest.approx(AVGO_MOVE_PCT)
        assert by_ticker["AVGO"]["implied_move_asof"] == AVGO_MARKET_DATE.isoformat()
    if "COHR" in by_ticker:
        # No implied-move row for COHR: not covered, and null is the answer.
        assert by_ticker["COHR"]["implied_move_pct"] is None
        assert by_ticker["COHR"]["implied_move_asof"] is None


def test_calendar_reactions_are_newest_first_and_capped_at_four(
    desk_client, seeded_desk
):
    body = desk_client.get("/api/fundamentals/ai-semi/calendar").json()
    by_ticker = {r["ticker"]: r for r in body["rows"]}
    if "NVDA" not in by_ticker:
        pytest.skip("NVDA's real 2026-11-18 print has passed; re-freeze PRINTS")
    got = by_ticker["NVDA"]["reactions"]
    assert got == pytest.approx([219.51 / 223.47 - 1, 184.89 / 195.56 - 1])
    assert len(got) <= 4
    # A name with no reaction history gets an empty list, never a zero.
    if "COHR" in by_ticker:
        assert by_ticker["COHR"]["reactions"] == []


def test_calendar_percentile_state_distinguishes_refusal_from_absence(
    desk_client, seeded_desk
):
    body = desk_client.get("/api/fundamentals/ai-semi/calendar").json()
    by_ticker = {r["ticker"]: r for r in body["rows"]}
    if "COHR" in by_ticker:
        assert by_ticker["COHR"]["spot_percentile"] == pytest.approx(0.05)
        assert by_ticker["COHR"]["percentile_state"] == "ok"
    for refused in ("AVGO", "LITE", "NVDA"):
        if refused in by_ticker:
            assert by_ticker[refused]["spot_percentile"] is None
            assert by_ticker[refused]["percentile_state"] != "ok"


def test_calendar_chain_filter_scopes_to_that_chains_members(desk_client, seeded_desk):
    body = desk_client.get(
        "/api/fundamentals/ai-semi/calendar", params={"chain": GPU}
    ).json()
    assert {r["chain"] for r in body["rows"]} <= {GPU}
    assert {r["ticker"] for r in body["rows"]} <= {"NVDA"}


# ================================================================ delta rail


def test_delta_rail_collapses_one_filing_to_one_entry(desk_client, seeded_desk):
    """`sec_filing` and `statement_published` both fire for the same print.
    Keep the richer fact and record the suppressed class rather than showing
    the operator the same filing twice."""
    body = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-01-01"}
    ).json()
    cohr = [e for e in body["events"] if e["ticker"] == "COHR"]
    assert len(cohr) == 1
    assert cohr[0]["event_class"] == "statement_published"
    assert cohr[0]["detail"]["also"] == ["sec_filing"]


def test_delta_rail_orders_by_the_desks_knowledge_clock(desk_client, seeded_desk):
    body = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-01-01"}
    ).json()
    known = [e["first_known_at"] for e in body["events"]]
    assert known == sorted(known, reverse=True)
    assert body["since"] == "2026-01-01"


def test_delta_rail_since_predicates_on_first_known_at_not_occurred_at(
    desk_client, seeded_desk
):
    """MRVL's band entry OCCURRED 2026-05-15 and became knowable 2026-05-16.
    A `since` of 2026-05-16 must still include it; a reader that predicated
    on `occurred_at` would drop it."""
    body = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-05-16"}
    ).json()
    assert "MRVL" in {e["ticker"] for e in body["events"]}
    later = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-05-17"}
    ).json()
    assert "MRVL" not in {e["ticker"] for e in later["events"]}


# ==================================================================== matrix


def test_matrix_chains_are_ordered_by_layer_rank_never_by_a_metric(
    desk_client, seeded_desk
):
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    assert body["section"] == "ai-semi"
    # Optical-Communication's lowest layer_rank is 10; Computer/GPU's is 40.
    assert body["chains"] == [OPTICAL, GPU]
    # Alphabetical is the wrong order here and DISAGREES with the right one —
    # without this the assertion above could not tell a rank sort from a name
    # sort (verified by mutation: `sorted(chains)` must fail this line).
    assert body["chains"] != sorted(body["chains"])
    # Nor is it ordered by any metric. Computer/GPU's only member, NVDA,
    # carries the highest gross margin in the section (0.749 against
    # Optical-Communication's 0.521 median), so a metric-descending order
    # would put it first.
    medians = {
        c["chain"]: c["median"] for c in body["cells"] if c["metric"] == "gross_margin"
    }
    by_metric = sorted(medians, key=lambda c: -(medians[c] or 0.0))
    assert body["chains"] != by_metric


def test_matrix_dots_carry_the_real_rollup_values(desk_client, seeded_desk):
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, OPTICAL, "gross_margin")
    got = {d["ticker"]: d["value"] for d in cell["dots"]}
    for ticker in ("AVGO", "MRVL", "LITE"):
        assert got[ticker] == pytest.approx(ROLLUP_BY_TICKER[ticker].gross_margin)
    assert got["COHR"] is None


def test_matrix_names_the_missing_tickers_never_a_bare_count(desk_client, seeded_desk):
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, OPTICAL, "gross_margin")
    assert cell["coverage_missing"] == ["COHR"]
    assert cell["members_total"] == 4
    assert all(isinstance(t, str) for t in cell["coverage_missing"])


def test_matrix_splits_cohorts_and_names_missing(desk_client, seeded_two_buckets):
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, seeded_two_buckets.chain, "rev_yoy")
    assert len(cell["cohorts"]) == 2  # reported / awaiting, never merged
    assert isinstance(cell["coverage_missing"], list)
    assert all(isinstance(t, str) for t in cell["coverage_missing"])
    by_label = {c["label"]: c for c in cell["cohorts"]}
    assert by_label["reported"]["as_of"] == "2026-08-21"
    assert sorted(by_label["reported"]["tickers"]) == ["COHR", "LITE"]
    assert by_label["awaiting"]["as_of"] == "2026-06-25"
    assert sorted(by_label["awaiting"]["tickers"]) == ["AVGO", "MRVL"]


def test_a_single_bucket_chain_renders_one_cohort_not_a_fake_straddle(
    desk_client, seeded_desk
):
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, GPU, "rev_yoy")
    assert len(cell["cohorts"]) == 1
    assert cell["cohorts"][0]["tickers"] == ["NVDA"]


def test_matrix_dots_say_whether_the_knowledge_date_was_estimated(
    desk_client, seeded_desk
):
    """`fundamentals_desk_rollup.knowledge_date_known` reaches the caller.
    The fallback (`period_end + FALLBACK_LAG_DAYS`) errs EARLY for late
    filers and therefore manufactures look-ahead — measured composite IC
    0.059 with it against 0.039 without. A surface that renders an estimated
    knowledge date identically to a filed one presents an estimate as a fact.

    BOTH polarities are pinned here, deliberately: the API field inverts the
    stored column's sense, so a test that only checked one side could not
    tell a correct inversion from a constant.
    """
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, OPTICAL, "rev_yoy")
    estimated = {d["ticker"]: d["knowledge_date_estimated"] for d in cell["dots"]}
    # AVGO/MRVL's rollup rows carry the fallback estimate...
    assert estimated["AVGO"] is True
    assert estimated["MRVL"] is True
    # ...COHR/LITE's carry a real filing date.
    assert estimated["COHR"] is False
    assert estimated["LITE"] is False


def test_the_matrix_never_filters_estimated_knowledge_dates_out(
    desk_client, seeded_desk
):
    """Carrying the flag is a DISPLAY duty; filtering on it is a research
    concern. AVGO and MRVL are estimated and must still be dots."""
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, OPTICAL, "rev_yoy")
    assert {"AVGO", "MRVL"} <= {d["ticker"] for d in cell["dots"]}
    assert all(
        d["value"] is not None for d in cell["dots"] if d["ticker"] in {"AVGO", "MRVL"}
    )


def test_a_valuation_percentile_dot_has_no_knowledge_date_claim(
    desk_client, seeded_desk
):
    """A percentile does not come from the rollup, so it has no knowledge
    date to be honest or dishonest about — null, never False."""
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, OPTICAL, "valuation_percentile")
    assert all(d["knowledge_date_estimated"] is None for d in cell["dots"])
    got = {d["ticker"]: d["value"] for d in cell["dots"]}
    assert got["COHR"] == pytest.approx(0.05)
    assert got["MRVL"] == pytest.approx(0.75)
    assert got["AVGO"] is None  # refused band


# =============================================================== profit pool


def test_profit_pool_is_layer_ordered_and_median_based(desk_client, seeded_desk):
    layers = desk_client.get("/api/fundamentals/ai-semi/profit-pool").json()
    assert [layer["chain"] for layer in layers] == [OPTICAL, GPU]
    assert [layer["layer_rank"] for layer in layers] == sorted(
        layer["layer_rank"] for layer in layers
    )
    optical = layers[0]
    margins = [ROLLUP_BY_TICKER[t].gross_margin for t in ("AVGO", "MRVL", "LITE")]
    assert optical["median_gross_margin"] == pytest.approx(statistics.median(margins))
    assert {d["ticker"] for d in optical["dots"]} == {"AVGO", "MRVL", "COHR", "LITE"}


# ==================================================================== limits


def test_limits_reports_ni_basis_as_descriptive_never_as_a_failure(
    desk_client, seeded_desk
):
    body = desk_client.get("/api/fundamentals/ai-semi/limits").json()
    assert set(body) >= {
        "ni_basis_agree",
        "ni_basis_differ",
        "ni_largest_basis_differences",
        "ni_sign_flip_violations",
        "withheld_composite",
        "membership_evidence",
        "exposure_coverage",
    }
    assert isinstance(body["ni_basis_agree"], int)
    assert isinstance(body["ni_basis_differ"], int)
    # Task 10's premise was DISPROVED: a basis difference is usually correct
    # accounting on both sides. The old pass/fail/offender names must not
    # come back.
    assert not {
        "ni_reconciliation_pass",
        "ni_reconciliation_fail",
        "ni_worst_offenders",
    } & set(body)


def test_limits_membership_evidence_is_computed_not_prose(desk_client, seeded_desk):
    body = desk_client.get("/api/fundamentals/ai-semi/limits").json()
    counts = {
        e["evidence_class"]: e["memberships"] for e in body["membership_evidence"]
    }
    # Seven section memberships: 6 in Optical-Communication + 1 in Computer/GPU.
    # `Banks`' JPM row is out of section and must not be counted.
    assert counts == {"analyst": 7}
    coverage = {c["chain"]: c for c in body["exposure_coverage"]}
    assert set(coverage) == {OPTICAL, GPU}
    assert coverage[OPTICAL]["members"] == 4  # DISTINCT tickers
    assert coverage[OPTICAL]["with_magnitude"] == 0


def test_limits_states_the_withheld_composite_rather_than_hiding_it(
    desk_client, seeded_desk
):
    body = desk_client.get("/api/fundamentals/ai-semi/limits").json()
    assert "0.89" in body["withheld_composite"]
    assert body["withheld_composite"].strip()


# ============================================================== underwriting


def test_underwriting_carries_the_filed_line_item_with_the_figure(
    desk_client, seeded_desk
):
    """Spec §4 trust requirement #1: the raw values and the filing date
    travel WITH the figure, not behind another request."""
    from tests.unit.fundamentals.test_feature_details import _BS, _CF, _INC

    rows = desk_client.get(
        "/api/fundamentals/ai-semi/node/underwriting", params={"chain": GPU}
    ).json()
    assert len(rows) == 1
    row = rows[0]
    newest = max(_INC)
    assert row["ticker"] == "NVDA"
    assert row["period_end"] == newest
    assert row["filing_published_at"] == "2026-05-20"
    assert row["cost_of_revenue_raw"] == _INC[newest]["cost_of_revenue"]
    # The frozen NVDA panel carries no inventory or SBC line, so those raw
    # strings are absent — and absence is the statement, not a zero.
    assert row["inventory_raw"] is None or isinstance(row["inventory_raw"], str)
    assert row["sbc_raw"] is None or isinstance(row["sbc_raw"], str)
    assert _BS and _CF  # the panel really was seeded from all three statements


def test_underwriting_never_says_diluted(desk_client, seeded_desk):
    """Argon has no diluted share count. `shares_outstanding_yoy` is BASIC
    period-end shares; naming it diluted would claim a measure that does not
    exist in the store."""
    from uw_scan.models.fundamentals_desk import NodeUnderwritingRow

    assert "shares_outstanding_yoy" in NodeUnderwritingRow.model_fields
    assert not any("dilut" in f.lower() for f in NodeUnderwritingRow.model_fields)
    rows = desk_client.get(
        "/api/fundamentals/ai-semi/node/underwriting", params={"chain": GPU}
    ).json()
    assert not any("dilut" in k.lower() for k in rows[0])


def test_underwriting_on_a_chain_with_no_statements_is_empty_not_an_error(
    desk_client, seeded_desk
):
    rows = desk_client.get(
        "/api/fundamentals/ai-semi/node/underwriting", params={"chain": OPTICAL}
    ).json()
    assert rows == []
