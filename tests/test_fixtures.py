from uw_scan.fixtures import demo_dashboard


def test_demo_dashboard_has_expected_tabs_data():
    dashboard = demo_dashboard()

    assert len(dashboard.opportunities) >= 6
    assert len(dashboard.flow_rows) >= 6
    assert len(dashboard.watchlist_sources) >= 1
    assert len(dashboard.tracked_items) >= 4
    assert len(dashboard.surface_metrics) >= 4
    assert dashboard.request_budget.total_estimated_requests > 0


def test_opportunity_fixture_contains_structure_without_sizing():
    dashboard = demo_dashboard()
    first = dashboard.opportunities[0]

    assert first.structure_idea is not None
    assert first.structure_idea.max_risk_note == "Sizing deferred"
    assert first.score >= 0


def test_demo_dashboard_contains_actionable_analysis_language():
    dashboard = demo_dashboard()
    combined = " ".join(
        [
            " ".join(row.confirmations + row.warnings + row.setup_types)
            for row in dashboard.opportunities
        ]
    )

    assert "Volume > OI" in combined
    assert "OI" in combined
    assert "IV" in combined


def test_demo_dashboard_contains_full_single_stock_analysis():
    dashboard = demo_dashboard()

    analysis = next(row for row in dashboard.stock_analyses if row.ticker == "TSLA")

    assert analysis.live_price == "$380.88"
    assert analysis.signal == "BUY"
    assert analysis.score == "+31/100"
    assert analysis.iv_rank == "3.4/100"
    assert analysis.market_structure.score == "+8/28"
    assert len(analysis.market_structure.levels) >= 7
    assert analysis.market_structure.levels[0].strike == "$382.50"
    assert analysis.market_structure.gex_flip == "$376.25 - 1.2% below live price $380.88"
    assert analysis.volatility.score == "+8/28"
    assert analysis.flow_positioning.net_premium == "+$524.3M"
    assert len(analysis.flow_positioning.oi_changes) == 3
    assert analysis.vrp_assessment.signal == "DO NOT SELL"
    assert analysis.trade_plan.title == "Bull Call Spread - TSLA"
    assert "Buy $385 Call / Sell $400 Call" in analysis.trade_plan.structure
