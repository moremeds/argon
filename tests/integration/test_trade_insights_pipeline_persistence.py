from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import (
    FlowSnapshot,
    MarketStructure,
    OptionContractRow,
    SingleStockReport,
    TermStructureRow,
    VolatilityProfile,
    VRPAssessment,
)
from uw_scan.pipeline import _persist_trade_insights_for_run


def _contract(
    symbol: str, bid: str, ask: str, volume: int, oi: int
) -> OptionContractRow:
    return OptionContractRow(
        option_symbol=symbol,
        last_price=Decimal(bid),
        nbbo_bid=Decimal(bid),
        nbbo_ask=Decimal(ask),
        implied_volatility=Decimal("0.52"),
        open_interest=oi,
        prev_oi=max(oi - 50, 0),
        volume=volume,
        ask_volume=int(volume * 0.55),
        bid_volume=int(volume * 0.35),
        total_premium=Decimal(bid) * Decimal(volume),
    )


def test_trade_insights_pipeline_persistence_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("TSLA")
    # Expiries inside the swing-HOLD entry window (21-60 DTE from 2026-05-13):
    #   2026-06-19 -> DTE 37 (preferred 28-45 band)
    #   2026-06-26 -> DTE 44 (preferred 28-45 band)
    repo.insert_option_contract_rows(
        run_id,
        "TSLA",
        [
            _contract("TSLA260619P00420000", "6.10", "6.30", 450, 500),
            _contract("TSLA260619P00425000", "8.00", "8.20", 600, 700),
            _contract("TSLA260619P00430000", "10.20", "10.50", 900, 850),
            _contract("TSLA260619C00430000", "9.40", "9.60", 1500, 1000),
            _contract("TSLA260619C00435000", "6.90", "7.10", 1200, 800),
            _contract("TSLA260626C00430000", "13.80", "14.20", 700, 900),
        ],
    )
    repo.insert_iv_term_rows(
        run_id,
        [
            TermStructureRow(
                ticker="TSLA",
                date=date(2026, 5, 13),
                expiry=date(2026, 6, 19),
                dte=37,
                implied_move_perc=Decimal("0.048"),
            ),
            TermStructureRow(
                ticker="TSLA",
                date=date(2026, 5, 13),
                expiry=date(2026, 6, 26),
                dte=44,
                implied_move_perc=Decimal("0.067"),
            ),
        ],
    )
    report = SingleStockReport(
        run_id=run_id,
        ticker="TSLA",
        generated_at=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        market_structure=MarketStructure(spot=Decimal("428")),
        volatility=VolatilityProfile(),
        flow=FlowSnapshot(
            ticker="TSLA",
            flow_count=0,
            net_premium=Decimal("0"),
            bull_premium=Decimal("0"),
            bear_premium=Decimal("0"),
            ask_side_premium=Decimal("0"),
            bid_side_premium=Decimal("0"),
        ),
        vrp=VRPAssessment(signal="UNKNOWN", note="test"),
    )

    _persist_trade_insights_for_run(repo=repo, report=report)
    _persist_trade_insights_for_run(repo=repo, report=report)

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot_id FROM uw_scan.trade_insight_snapshots WHERE run_id = %s",
            (run_id,),
        )
        snapshots = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.trade_insight_candidates WHERE run_id = %s",
            (run_id,),
        )
        candidate_count = cur.fetchone()[0]

    assert len(snapshots) == 1
    assert candidate_count > 0
