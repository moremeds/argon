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

from uw_scan.api.routers.fundamentals_desk import SECTIONS
from uw_scan.fundamentals.features import FALLBACK_LAG_DAYS, FEATURES
from uw_scan.fundamentals.statements import (
    FIELD_MAP_VERSION,
    check_net_income_sign_flip,
    content_hash,
    normalize,
)
from uw_scan.reports import fundamentals_desk as desk
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
SEMICAP = "Semi-Cap/EDA"
FOUNDRY = "Foundry"
GPU = "Computer/GPU"
BANKS = "Banks"

#: The desk's clock, FROZEN. `desk_calendar` takes `today` as a parameter
#: (`reports/gamma_levels.py`'s pattern) precisely so these tests never depend
#: on the wall clock. Every calendar assertion below runs the assembler
#: directly at this instant, so the fixture's real print dates neither expire
#: nor need to be in the future — re-dating the whole fixture by years must
#: leave every calendar test passing, which is the property the earlier
#: real-future-dates version did not have.
FROZEN_TODAY = date(2026, 8, 27)

# ---------------------------------------------------------------- taxonomy

#: (domain, chain, layer, layer_rank, members). Mirrors the shape the
#: production seed writes — Optical-Communication's real layer ladder, two more
#: `ai_infrastructure` chains, and one `unclassified` chain that must NOT reach
#: the ai-semi desk.
#:
#: THREE section chains, not two, and the third is load-bearing. With only
#: Optical-Communication (rank 10) and Computer/GPU (rank 40), descending
#: alphabetical happens to equal ascending layer_rank, so NO assertion over
#: that fixture could tell a rank sort from a name sort — a `sorted(lowest,
#: reverse=True)` mutant stayed green. `Semi-Cap/EDA` at rank 20 breaks the
#: coincidence: rank-ascending, name-ascending and name-descending are now
#: three DISTINCT orderings (see the chain-order test).
CHAINS: list[tuple[str, str, str, int, list[str]]] = [
    ("optical_communication", OPTICAL, "Upstream-Components", 10, ["COHR", "LITE"]),
    ("optical_communication", OPTICAL, "Semi-DSP-Switch", 20, ["AVGO", "MRVL"]),
    # COHR and LITE again, one layer down: `chain_membership` is
    # (chain, layer, ticker)-grained, so each is TWO rows and must count once.
    ("optical_communication", OPTICAL, "Module-Transceiver", 30, ["COHR", "LITE"]),
    # Real Semi-Cap/EDA names, deliberately with NO rollup rows: the chain's
    # medians must come back null and both members must be NAMED missing.
    ("ai_infrastructure", SEMICAP, "Equipment", 20, ["AMAT", "LRCX"]),
    # Real Foundry members. UMC carries the real 2010-09-30 SIGN FLIP, so the
    # section contains one of the measured five and the limits panel's
    # agree/violation split is testable on real data.
    ("ai_infrastructure", FOUNDRY, "Fab", 30, ["UMC", "TSM"]),
    ("ai_infrastructure", GPU, "Compute-Silicon", 40, ["NVDA"]),
    ("unclassified", BANKS, "L3", 0, ["JPM"]),
]

#: Ascending `layer_rank`, the only order the matrix may use. Ties break
#: alphabetically; the four minima (10, 20, 30, 40) are distinct, and so are
#: rank-ascending, name-ascending and name-descending over this set.
CHAINS_BY_RANK = [OPTICAL, SEMICAP, FOUNDRY, GPU]

# ---------------------------------------------------------------- calendar

#: (ticker, report_date, session) — every one a REAL print.
#:
#: Dates on or after 2026-08-12 verified live via Unusual Whales
#: `get_upcoming_earnings` on 2026-08-28 (`report_date` / `report_time`);
#: LITE 2026-08-11 and COHR 2026-08-12 are the `last_earnings_date` values the
#: same response carried, and NVDA 2026-08-26 is the print Task 6's reaction
#: fixture already froze. Against `FROZEN_TODAY = 2026-08-27` the first three
#: are PAST and must not appear; the rest are the calendar.
PRINTS = [
    ("LITE", date(2026, 8, 11), None),  # past
    ("COHR", date(2026, 8, 12), None),  # past
    ("NVDA", date(2026, 8, 26), "afterhours"),  # past — yesterday
    ("MRVL", date(2026, 8, 27), "afterhours"),  # today: the inclusive boundary
    ("AVGO", date(2026, 9, 2), "afterhours"),
    ("JPM", date(2026, 10, 13), None),  # out of section
    ("LITE", date(2026, 11, 3), None),
    ("COHR", date(2026, 11, 4), None),
    ("NVDA", date(2026, 11, 18), None),
]

#: What the ai-semi calendar must contain at `FROZEN_TODAY`, in order.
#: `report_date` ASC, then `layer_rank` ASC. MRVL and AVGO sit in
#: Optical-Communication's Semi-DSP-Switch layer (rank 20); LITE and COHR are
#: each in TWO layers (10 and 30), so each contributes two rows; NVDA is in
#: Computer/GPU (rank 40). JPM is out of section.
EXPECTED_CALENDAR = [
    ("MRVL", date(2026, 8, 27), 20),
    ("AVGO", date(2026, 9, 2), 20),
    ("LITE", date(2026, 11, 3), 10),
    ("LITE", date(2026, 11, 3), 30),
    ("COHR", date(2026, 11, 4), 10),
    ("COHR", date(2026, 11, 4), 30),
    ("NVDA", date(2026, 11, 18), 40),
]

#: (report_date, close_before_date, close_before, close_after_date, close_after)
NVDA_REACTIONS = [
    (date(2026, 5, 20), date(2026, 5, 20), 223.4700, date(2026, 5, 21), 219.5100),
    (date(2026, 2, 25), date(2026, 2, 25), 195.5600, date(2026, 2, 26), 184.8900),
]

# ------------------------------------------------------------ implied move

#: Brenner-Subrahmanyam ATM-straddle approximation, the same constant
#: `worker/jobs/implied_move_snapshot.py` applies. Written out here rather than
#: imported so the fixture states its own arithmetic.
BS_CONSTANT = 0.7978845608028654
SNAPSHOT_DATE = date(2026, 8, 26)


def _move_pct(call_iv: float, put_iv: float, expiry: date) -> float:
    atm_iv = (call_iv + put_iv) / 2
    return BS_CONSTANT * atm_iv * math.sqrt((expiry - SNAPSHOT_DATE).days / 365.0)


#: ticker, report_date the snapshot was computed FOR, expiry, strike, call_iv,
#: put_iv, spot. Every grid value is a real `option_surface_grid_daily` row on
#: 2026-08-26 from the dev warm store, nearest-strike to that night's spot.
#:
#: AVGO and MRVL target the prints they are listed against — the covered case.
#: NVDA targets 2026-08-26, its REAL print that night, while the calendar lists
#: NVDA's NEXT print on 2026-11-18. That is not a contrived pairing: the
#: snapshot job only writes rows for prints inside its lookahead window, so for
#: most of a quarter a name's newest row belongs to the print that already
#: happened. Attaching it to the next print would render a three-month-old
#: number as "the market-implied move".
IMPLIED_MOVES = [
    (
        "AVGO",
        date(2026, 9, 2),
        date(2026, 9, 4),
        357.5,
        0.736661443735852,
        0.706997006724508,
        358.3500,
    ),
    (
        "MRVL",
        date(2026, 8, 27),
        date(2026, 8, 28),
        255.0,
        1.75303122694714,
        1.77244830095955,
        254.3304,
    ),
    (
        "NVDA",
        date(2026, 8, 26),
        date(2026, 8, 28),
        217.5,
        1.02669066974897,
        1.02184907857019,
        218.7123,
    ),
]
MOVE_PCT = {
    ticker: _move_pct(call_iv, put_iv, expiry)
    for ticker, _rd, expiry, _k, call_iv, put_iv, _spot in IMPLIED_MOVES
}

# ----------------------------------------------------------------- rollup


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
                "ticker": ticker,
                "market_date": SNAPSHOT_DATE,
                "report_date": report_date,
                "expiry": expiry,
                "strike": strike,
                "atm_iv": (call_iv + put_iv) / 2,
                "iv_basis": "both",
                "spot": spot,
                "implied_move_pct": MOVE_PCT[ticker],
                "implied_move_usd": MOVE_PCT[ticker] * spot,
            }
            for ticker, report_date, expiry, strike, call_iv, put_iv, spot in (
                IMPLIED_MOVES
            )
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
    different name and one event on the out-of-section `Banks` member.

    THE TWO COLLAPSING EVENTS CARRY DIFFERENT `first_known_at` VALUES, with
    the `sec_filing` LATER. That asymmetry is the real one — SEC indexing lags
    statement ingest — and it is what makes the rail's ordering testable at
    all: give both the same knowledge date and the collapse is order-neutral,
    so the dataset passes whether or not the code re-sorts. MRVL's band entry
    sits BETWEEN the two dates, so a collapse that inherits the loser's slot
    puts the rail out of order.
    """
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
                # UW carried the statements a week before EDGAR indexed them.
                "first_known_at": date(2026, 8, 16),
                "title": "COHR 2026-06-30 statements published",
                "detail": {"period_end": "2026-06-30"},
                "source_kind": "uw",
                "source_ref": "COHR:2026-06-30",
            },
            {
                "event_class": "sec_filing",
                "ticker": "COHR",
                "occurred_at": date(2026, 8, 14),
                # ...and the SEC index arrived LATER, which is the whole point.
                "first_known_at": date(2026, 8, 25),
                "title": "COHR 10-Q filed",
                "detail": {"form": "10-Q"},
                "source_kind": "sec",
                "source_ref": "COHR:10-Q:2026-08-14",
            },
            {
                # Between the two COHR dates: a rail that inherits the loser's
                # slot puts this ABOVE the older statement date it now carries.
                "event_class": "band_entry",
                "ticker": "MRVL",
                "occurred_at": date(2026, 5, 15),
                "first_known_at": date(2026, 8, 20),
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


#: NVDA's REAL 2026-04-30 cash-flow `net_income`, verified equal to the income
#: statement's own headline in `uw_scan.fundamental_statement_obs` — the same
#: agreeing pair `test_fundamental_ni_reconciliation.py` froze. Seeded so the
#: section HAS a comparable NI pair; without one, `ni_basis_agree` is 0 whether
#: or not the scan is scoped, and the scoping test cannot see its own effect.
NVDA_CASH_FLOW_NET_INCOME = "58321000000"

#: VZ's REAL 2010-09-30 pair — Verizon's own disclosed NCI split (Vodafone's
#: 45% of Verizon Wireless: 881M + 1,817M = 2,698M). Both figures correct; the
#: gap is accounting, not a defect. VZ has NO chain membership, so it is the
#: out-of-section statement-bearing name: a section-scoped limits panel must
#: never name it, and an unscoped one always will.
VZ_PERIOD = date(2010, 9, 30)
VZ_INCOME = {"net_income": "881000000", "net_income_from_continuing_operations": "0"}
VZ_CASH_FLOW = {"net_income": "2698000000"}


def _statement_row(ticker: str, period: str, statement: str, raw: dict, filed=None):
    payload = normalize(
        {
            **raw,
            "ticker": ticker,
            "fiscal_date_ending": period,
            "report_type": "quarterly",
        }
    )
    return {
        "source": "uw",
        "ticker": ticker,
        "period_end": date.fromisoformat(period),
        "period_type": "quarterly",
        "statement": statement,
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": filed,
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


#: UMC's REAL 2010-09-30 pair — one of the five sign flips measured across the
#: full 28,973-pair historical store (opposite sign, magnitude matching within
#: 1%: 8,720,447k against -8,754,593k). A genuine vendor defect, NOT an
#: accounting basis gap, and UMC is a real member of the real `Foundry` chain —
#: so the section contains a sign flip and the limits panel must not book it as
#: agreement while `ni_sign_flip_violations` books it as a violation.
UMC_PERIOD = date(2010, 9, 30)
UMC_INCOME = {
    "net_income": "8720447000",
    "net_income_from_continuing_operations": "0",
}
UMC_CASH_FLOW_SIGN_FLIPPED = {"net_income": "-8754593000"}


def _seed_out_of_section_statements(seeded) -> None:
    """VZ: real statements, real NI basis gap, NO chain membership."""
    FundamentalObsRepository(seeded.conn, schema=seeded._schema).record_statements(
        [
            _statement_row("VZ", VZ_PERIOD.isoformat(), "income", VZ_INCOME),
            _statement_row("VZ", VZ_PERIOD.isoformat(), "cash_flow", VZ_CASH_FLOW),
        ]
    )


def _seed_sign_flip(seeded) -> None:
    """UMC's real sign-flipped pair, IN section, with its violation recorded
    the way `fundamental_ingest` records it — statements alone would leave
    `violation_count` at zero and the double-booking invisible."""
    repo = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    income = _statement_row("UMC", UMC_PERIOD.isoformat(), "income", UMC_INCOME)
    cash_flow = _statement_row(
        "UMC", UMC_PERIOD.isoformat(), "cash_flow", UMC_CASH_FLOW_SIGN_FLIPPED
    )
    repo.record_statements([income, cash_flow])
    violations = check_net_income_sign_flip(income["raw_jsonb"], cash_flow["raw_jsonb"])
    assert violations, "the frozen UMC pair must still trip the sign-flip check"
    obs_id = repo.obs_id(
        source="uw",
        ticker="UMC",
        period_end=UMC_PERIOD,
        period_type="quarterly",
        statement="income",
        content_hash=income["content_hash"],
    )
    repo.record_violations(obs_id, violations)


def _seed_nvda_statements(seeded) -> None:
    """The same frozen ten-quarter real NVDA panel `test_feature_details.py`
    built for `build_features` — reused rather than copied so the underwriting
    endpoint is exercised over figures another test already owns."""
    from tests.unit.fundamentals.test_feature_details import _BS, _CF, _INC

    newest = max(_INC)
    # The two frozen sources must agree that NVDA's real 2026-04-30 net income
    # is the same on both statements; asserting it beats assuming it.
    assert _INC[newest]["net_income"] == NVDA_CASH_FLOW_NET_INCOME

    rows = []
    for period in _INC:
        cash_flow = dict(_CF[period])
        if period == newest:
            cash_flow["net_income"] = NVDA_CASH_FLOW_NET_INCOME
        for statement, raw in (
            ("income", _INC[period]),
            ("balance", _BS[period]),
            ("cash_flow", cash_flow),
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
    _seed_out_of_section_statements(seeded_db_empty_cards)
    _seed_sign_flip(seeded_db_empty_cards)
    return seeded_db_empty_cards


@pytest.fixture
def desk_client(client, seeded_desk):
    return client


def _calendar(seeded, *, chain: str | None = None, today: date = FROZEN_TODAY):
    """The calendar assembler at a FROZEN clock.

    Called directly rather than over HTTP because `today` is deliberately not
    a request parameter — the endpoint answers "what prints next" and a caller
    that could move the clock would be asking something else. The router is a
    pass-through and is covered by its own wiring test below.
    """
    return desk.desk_calendar(
        seeded.conn,
        schema=seeded._schema,
        section="ai-semi",
        domains=SECTIONS["ai-semi"],
        chain=chain,
        today=today,
    )


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


def test_the_two_invertible_facts_reach_the_generated_types(desk_client):
    """A `#:` comment documents a field for a Python reader and reaches NOBODY
    else — it is stripped before OpenAPI, so `web/lib/types.ts` gets an empty
    description. The two facts a web task is most likely to invert are that
    `spot_percentile` is a YIELD percentile (high = CHEAP) and that
    `knowledge_date_estimated`'s null is not false. Both must travel."""
    schemas = desk_client.get("/openapi.json").json()["components"]["schemas"]
    pct = schemas["DeskCalendarRow"]["properties"]["spot_percentile"]["description"]
    assert "CHEAP" in pct
    assert "not a cross-sectional rank" in pct.lower()
    estimated = schemas["MemberDot"]["properties"]["knowledge_date_estimated"][
        "description"
    ]
    assert "THREE-STATE" in estimated
    assert "null is NOT false" in estimated
    # And the one that must never be read as dilution.
    shares = schemas["NodeUnderwritingRow"]["properties"]["shares_outstanding_yoy"][
        "description"
    ]
    assert "NOT a diluted share count" in shares


def _desk_model_names() -> list[str]:
    """Every response model this module defines, found REFLECTIVELY.

    Enumerated rather than listed so a model added later is covered without
    anyone remembering to add it here — the defect this test exists for is a
    rule being broken, not a particular field being wrong.
    """
    from pydantic import BaseModel

    from uw_scan.models import _base, fundamentals_desk

    return sorted(
        name
        for name, obj in vars(fundamentals_desk).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj is not _base._UwBase
        and not name.startswith("_")
    )


def test_every_desk_field_is_required(desk_client):
    """NULLABLE IS NOT OPTIONAL, across the whole module.

    `x: float | None = None` is the natural way to declare a nullable field
    and it silently makes the field absent-allowed as well: Pydantic drops it
    from `required` and `openapi-typescript` emits `x?: number | null` — three
    states where the contract has two.

    That is load-bearing here twice over. `MemberDot.knowledge_date_estimated`
    is documented three-state with `null` explicitly NOT `false`, so a fourth
    reading is how a consumer inverts it; and `reactions?: number[]` turns
    `row.reactions.length` into a runtime crash rather than the "no reaction
    history is held" reading its own description demands.

    Asserting the RULE over every model, rather than the two fields a reviewer
    happened to name, is the point: patching named instances left twenty-nine
    other fields widened.
    """
    schemas = desk_client.get("/openapi.json").json()["components"]["schemas"]
    names = _desk_model_names()
    assert len(names) == 13, names  # the module's full model surface
    for name in names:
        schema = schemas[name]
        optional = sorted(set(schema["properties"]) - set(schema.get("required", [])))
        # A field may only be optional if its ABSENCE is a different answer
        # from its NULL. No field in this module qualifies; if one ever does,
        # allow-list it HERE with the two answers it distinguishes named.
        assert optional == [], f"{name} has absent-allowed fields: {optional}"


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

    cal = _calendar(seeded_desk)
    assert "JPM" not in {row.ticker for row in cal.rows}
    assert cal.rows, "an empty calendar makes the JPM clause vacuous"

    # EXPLICIT `since`. The default is `today - 7 days`, and the newest seeded
    # event is 2026-08-25 — so from roughly 2026-09-01 the default window is
    # empty forever and `JPM not in {}` asserts nothing. The non-emptiness
    # assertion below is what makes the exclusion a finding rather than a
    # coincidence.
    delta = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-01-01"}
    ).json()
    assert delta["events"], "an empty rail makes the JPM clause vacuous"
    assert "JPM" not in {e["ticker"] for e in delta["events"]}
    # JPM's event IS in the ledger — the absence above is the section filter
    # working, not the fixture being empty.
    assert ResearchEventsRepository(
        seeded_desk.conn, schema=seeded_desk._schema
    ).events_for("JPM")


def test_an_unknown_section_is_404_not_an_empty_desk(desk_client):
    """An empty desk for a section that does not exist is a lie shaped like
    data."""
    assert desk_client.get("/api/fundamentals/biotech/matrix").status_code == 404


# ================================================================= calendar
#
# Every test below runs the assembler at FROZEN_TODAY and asserts EXACT,
# non-empty content. The previous version called the endpoint with the real
# clock and guarded each assertion behind `if ticker in by_ticker`, so as the
# seeded real prints aged out the tests went SILENTLY vacuous — passing while
# asserting nothing. A frozen clock removes the decay entirely rather than
# postponing it.


def test_calendar_lists_section_prints_in_read_through_order(seeded_desk):
    body = _calendar(seeded_desk)
    assert body.section == "ai-semi"
    assert body.as_of == FROZEN_TODAY
    got = [(r.ticker, r.report_date, r.layer_rank) for r in body.rows]
    assert got == EXPECTED_CALENDAR
    # The three real prints before the clock are history, not calendar. NVDA's
    # 2026-08-26 print is yesterday's and must not appear even though NVDA has
    # a LATER print that does.
    assert (date(2026, 8, 26)) not in {r.report_date for r in body.rows}
    # MRVL's print is ON the frozen day: the floor is inclusive.
    assert ("MRVL", FROZEN_TODAY, 20) in got


def test_calendar_is_independent_of_the_wall_clock(seeded_desk):
    """Re-ask the same question at a clock five years on: the answer changes
    because the CALENDAR moved, not because the test decayed. Nothing here
    reads `date.today()`."""
    later = _calendar(seeded_desk, today=FROZEN_TODAY.replace(year=2031))
    assert later.as_of == date(2031, 8, 27)
    assert later.rows == []
    earlier = _calendar(seeded_desk, today=date(2020, 1, 1))
    # Every seeded print is ahead of 2020, so all nine rows' worth appear —
    # including the ones that are "past" at FROZEN_TODAY and JPM's, which is
    # excluded by SECTION rather than by date.
    assert {r.ticker for r in earlier.rows} == {"LITE", "COHR", "NVDA", "MRVL", "AVGO"}


def test_calendar_renders_an_unknown_session_as_null_never_as_a_guess(seeded_desk):
    rows = {r.ticker: r for r in _calendar(seeded_desk).rows}
    # COHR's real 2026-11-04 print is one UW reports as `report_time:
    # "unknown"` — it lands in neither classified slot.
    assert rows["COHR"].session is None
    assert rows["MRVL"].session == "afterhours"


def test_calendar_carries_implied_move_and_names_its_absence(seeded_desk):
    rows = {r.ticker: r for r in _calendar(seeded_desk).rows}
    for covered in ("AVGO", "MRVL"):
        assert rows[covered].implied_move_pct == pytest.approx(MOVE_PCT[covered])
        assert rows[covered].implied_move_asof == SNAPSHOT_DATE
    # COHR has no implied-move row at all: not covered, and null says so.
    assert rows["COHR"].implied_move_pct is None
    assert rows["COHR"].implied_move_asof is None


def test_calendar_never_carries_an_implied_move_from_a_different_print(seeded_desk):
    """The defect this test exists for: NVDA's NEWEST implied-move row was
    computed for its 2026-08-26 print, and the calendar lists its NEXT print
    on 2026-11-18 — 83 days out, with no snapshot of its own. The snapshot job
    only writes rows inside a short lookahead window, so for most of a quarter
    the newest row belongs to a print that already happened. Rendering it
    would put a three-month-old number under the label "market-implied move",
    which is the carry-forward the honest-absence rule forbids.
    """
    rows = {r.ticker: r for r in _calendar(seeded_desk).rows}
    assert rows["NVDA"].report_date == date(2026, 11, 18)
    assert rows["NVDA"].implied_move_pct is None
    assert rows["NVDA"].implied_move_asof is None
    # The row IS in the store and IS the newest for NVDA — the endpoint
    # declined it, rather than there being nothing to decline.
    stored = ImpliedMoveRepository(
        seeded_desk.conn, schema=seeded_desk._schema
    ).latest_for(["NVDA"])["NVDA"]
    assert stored["report_date"] == date(2026, 8, 26)
    assert float(stored["implied_move_pct"]) == pytest.approx(MOVE_PCT["NVDA"])


def test_calendar_reactions_are_newest_first_and_capped_at_four(seeded_desk):
    rows = {r.ticker: r for r in _calendar(seeded_desk).rows}
    assert rows["NVDA"].reactions == pytest.approx(
        [219.51 / 223.47 - 1, 184.89 / 195.56 - 1]
    )
    assert len(rows["NVDA"].reactions) <= 4
    # A name with no reaction history gets an empty list, never a zero.
    assert rows["COHR"].reactions == []


def test_calendar_percentile_state_distinguishes_refusal_from_absence(seeded_desk):
    rows = {r.ticker: r for r in _calendar(seeded_desk).rows}
    assert rows["COHR"].spot_percentile == pytest.approx(0.05)
    assert rows["COHR"].percentile_state == "ok"
    # Real REFUSED bands: a row exists, every level and the percentile null.
    for refused in ("AVGO", "LITE", "NVDA"):
        assert rows[refused].spot_percentile is None
        assert rows[refused].percentile_state == "unsupported_capability"


def test_calendar_chain_filter_scopes_to_that_chains_members(seeded_desk):
    body = _calendar(seeded_desk, chain=GPU)
    assert [r.ticker for r in body.rows] == ["NVDA"]
    assert {r.chain for r in body.rows} == {GPU}
    # Unfiltered, the same call returns the whole section — so the assertion
    # above is about the filter, not about an empty desk.
    assert len(_calendar(seeded_desk).rows) == len(EXPECTED_CALENDAR)


def test_calendar_endpoint_is_wired_and_reads_the_real_clock(desk_client, seeded_desk):
    """The router passes no clock, so the endpoint answers for TODAY. This is
    the one calendar assertion that touches the wall clock, and it asserts
    only that the default is today — never which prints exist."""
    body = desk_client.get("/api/fundamentals/ai-semi/calendar").json()
    assert body["section"] == "ai-semi"
    assert body["as_of"] == date.today().isoformat()
    assert isinstance(body["rows"], list)


# ------------------------------------------------- an unknown chain is a 404


def test_an_unknown_chain_is_404_on_every_endpoint_that_takes_one(
    desk_client, seeded_desk
):
    """Same argument as the section 404, one level down: `200 []` for a chain
    that does not exist says this desk contains that node and it is empty. A
    typo in a link would render as a real, empty node."""
    for path in (
        "/api/fundamentals/ai-semi/calendar",
        "/api/fundamentals/ai-semi/node/underwriting",
    ):
        r = desk_client.get(path, params={"chain": "Substation/Typo"})
        assert r.status_code == 404, path
        assert "Substation/Typo" in r.json()["detail"]


def test_an_unknown_chain_is_404_even_with_no_active_taxonomy(desk_client, seeded_desk):
    """The no-taxonomy path reached `200 []` by a shorter route.

    With no active version every assembler returned an empty result BEFORE the
    chain guard ran, so an unknown `?chain=` was answered with an empty desk —
    the same false claim the 404 exists to refuse, arrived at from the other
    side. With no taxonomy, NO chain exists, so every named chain is unknown.
    """
    with seeded_desk.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {seeded_desk._schema}.research_taxonomy_versions "
            f"SET is_active = false"
        )
    seeded_desk.conn.commit()

    for path in (
        "/api/fundamentals/ai-semi/calendar",
        "/api/fundamentals/ai-semi/node/underwriting",
    ):
        assert desk_client.get(path, params={"chain": OPTICAL}).status_code == 404, path
    # An UNFILTERED read still answers 200 with nothing: no taxonomy is a
    # statement about Argon, and the desk is entitled to make it.
    assert desk_client.get("/api/fundamentals/ai-semi/calendar").status_code == 200


def test_a_chain_outside_the_section_is_404_not_an_empty_node(desk_client, seeded_desk):
    """`Banks` exists in the taxonomy but in `unclassified`. Asking the
    ai-semi desk for it is asking for something that does not exist HERE."""
    r = desk_client.get(
        "/api/fundamentals/ai-semi/node/underwriting", params={"chain": BANKS}
    )
    assert r.status_code == 404


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


def test_delta_rail_stays_descending_through_the_collapse(desk_client, seeded_desk):
    """The collapse substitutes the winner into the LOSER's list position, and
    the two do not share a clock: COHR's statements were known 2026-08-16 and
    its SEC index entry 2026-08-25, with MRVL's band entry at 2026-08-20 in
    between. Without a re-sort the surviving entry inherits the 08-25 slot
    while carrying 08-16, and the rail reads ['08-16', '08-20'] — ASCENDING,
    against a model that documents the knowledge clock as descending.

    Giving both COHR events the same `first_known_at` makes the collapse
    order-neutral, which is why this test could not previously fail.
    """
    body = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-01-01"}
    ).json()
    known = [e["first_known_at"] for e in body["events"]]
    assert known == ["2026-08-20", "2026-08-16"]
    assert known == sorted(known, reverse=True)
    # The surviving COHR entry keeps the statement's OWN knowledge date, not
    # the suppressed sec_filing's later one.
    cohr = next(e for e in body["events"] if e["ticker"] == "COHR")
    assert cohr["first_known_at"] == "2026-08-16"


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
    """MRVL's band entry OCCURRED 2026-05-15 and became knowable 2026-08-20 —
    three months apart, so the two clocks cannot be confused for each other.
    A `since` of 2026-08-20 must still include it; a reader that predicated on
    `occurred_at` would have dropped it back in May."""
    body = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-08-20"}
    ).json()
    assert "MRVL" in {e["ticker"] for e in body["events"]}
    later = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-08-21"}
    ).json()
    assert "MRVL" not in {e["ticker"] for e in later["events"]}
    # ...and a `since` after the event OCCURRED but before it was KNOWN must
    # still return it — the assertion an occurred_at reader fails outright.
    between = desk_client.get(
        "/api/fundamentals/ai-semi/delta", params={"since": "2026-06-01"}
    ).json()
    assert "MRVL" in {e["ticker"] for e in between["events"]}


# ==================================================================== matrix


def test_matrix_chains_are_ordered_by_layer_rank_never_by_a_metric(
    desk_client, seeded_desk
):
    """Ascending minimum `layer_rank`, and NOTHING else.

    THREE chains, because with two this test could not do its job. The earlier
    fixture held only Optical-Communication (rank 10) and Computer/GPU (rank
    40), where descending-alphabetical happens to equal ascending-rank — so a
    `sorted(lowest, reverse=True)` implementation stayed GREEN no matter what
    was asserted. `Semi-Cap/EDA` at rank 20 makes the three candidate orderings
    genuinely distinct:

        rank ascending  -> Optical-Communication, Semi-Cap/EDA, Computer/GPU
        name ascending  -> Computer/GPU, Optical-Communication, Semi-Cap/EDA
        name descending -> Semi-Cap/EDA, Optical-Communication, Computer/GPU

    Each of the three wrong orders is excluded by its own assertion below.
    """
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    assert body["section"] == "ai-semi"
    got = body["chains"]
    assert got == CHAINS_BY_RANK
    # Not alphabetical, in EITHER direction — the two assertions are separate
    # because with a two-chain fixture the descending one silently held.
    assert got != sorted(got)
    assert got != sorted(got, reverse=True)
    # Nor ordered by any metric. Computer/GPU's only member, NVDA, carries the
    # highest gross margin in the section (0.749 against
    # Optical-Communication's 0.521 median and Semi-Cap/EDA's null), so a
    # metric-descending order would put it first.
    medians = {
        c["chain"]: c["median"] for c in body["cells"] if c["metric"] == "gross_margin"
    }
    by_metric = sorted(medians, key=lambda c: -(medians[c] or 0.0))
    assert got != by_metric


def test_a_chain_with_no_rollup_rows_abstains_and_names_both_members(
    desk_client, seeded_desk
):
    """Semi-Cap/EDA's real members carry no rollup row at all. The median must
    be null — not 0 — and BOTH names must appear in `coverage_missing`."""
    body = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    cell = _cell(body, SEMICAP, "gross_margin")
    assert cell["median"] is None
    assert cell["coverage_missing"] == ["AMAT", "LRCX"]
    assert cell["members_total"] == 2
    assert all(d["value"] is None for d in cell["dots"])
    assert {d["state"] for d in cell["dots"]} == {"no_compatible_run"}


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
    assert [layer["chain"] for layer in layers] == CHAINS_BY_RANK
    assert [layer["layer_rank"] for layer in layers] == [10, 20, 30, 40]
    # A chain with no rollup rows abstains rather than reporting 0.
    semicap = next(layer for layer in layers if layer["chain"] == SEMICAP)
    assert semicap["median_gross_margin"] is None
    assert semicap["median_rev_yoy"] is None
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


def test_limits_net_income_figures_are_scoped_to_the_section(desk_client, seeded_desk):
    """A section-scoped URL must not answer for a different population.

    VZ carries a REAL net-income basis gap (881M attributable-to-parent
    against 2,698M consolidated including Vodafone's NCI) and NO chain
    membership. Under a header reading "AI/Semi — what this desk cannot say",
    naming VZ is false in the page's own frame. NVDA's real agreeing pair is
    in-section, so the counts are non-zero on the correct side — a scope bug
    cannot hide behind two zeroes.
    """
    body = desk_client.get("/api/fundamentals/ai-semi/limits").json()
    assert "VZ" not in body["ni_largest_basis_differences"]
    assert body["ni_largest_basis_differences"] == []
    assert body["ni_basis_differ"] == 0
    # NVDA's 2026-04-30 pair agrees on both statements and IS in section.
    assert body["ni_basis_agree"] == 1
    # ...and VZ really is in the store, so the absence above is the scope
    # working rather than the fixture being empty.
    unscoped = FundamentalObsRepository(
        seeded_desk.conn, schema=seeded_desk._schema
    ).net_income_basis_summary()
    assert unscoped["differ"] == 1
    assert [r["ticker"] for r in unscoped["by_ticker"]] == ["VZ"]


def test_a_sign_flip_is_a_violation_and_never_also_an_agreement(
    desk_client, seeded_desk
):
    """UMC's real 2010-09-30 pair is one of the five sign flips measured across
    28,973 historical pairs: opposite sign, magnitudes matching within 1%.

    `net_income_basis_difference` returns None for it — deliberately, because a
    literal sign inversion is a VENDOR DEFECT, not an accounting basis gap — so
    a reader that folds every None into `agree` books the pair twice: once as
    evidence the two statements are consistent, and again as a violation. It is
    comparable and it does NOT match, so it is neither agreement nor a basis
    difference; it belongs only to `ni_sign_flip_violations`.
    """
    body = desk_client.get("/api/fundamentals/ai-semi/limits").json()
    assert body["ni_sign_flip_violations"] == 1
    # Only NVDA's genuinely-agreeing pair. UMC's must NOT be here.
    assert body["ni_basis_agree"] == 1
    assert body["ni_basis_differ"] == 0
    assert "UMC" not in body["ni_largest_basis_differences"]
    # UMC IS in section — the exclusion above is the split working, not a
    # membership gap.
    matrix = desk_client.get("/api/fundamentals/ai-semi/matrix").json()
    assert "UMC" in {d["ticker"] for c in matrix["cells"] for d in c["dots"]}


def test_limits_membership_evidence_is_computed_not_prose(desk_client, seeded_desk):
    body = desk_client.get("/api/fundamentals/ai-semi/limits").json()
    counts = {
        e["evidence_class"]: e["memberships"] for e in body["membership_evidence"]
    }
    # Eleven section memberships: 6 in Optical-Communication + 2 in
    # Semi-Cap/EDA + 2 in Foundry + 1 in Computer/GPU. `Banks`' JPM row is out
    # of section.
    assert counts == {"analyst": 11}
    coverage = {c["chain"]: c for c in body["exposure_coverage"]}
    assert set(coverage) == {OPTICAL, SEMICAP, FOUNDRY, GPU}
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
