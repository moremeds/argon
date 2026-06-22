def test_081_tables_present(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='uw_scan' AND table_name LIKE 'vrp_%'"
        )
        names = {r[0] for r in cur.fetchall()}
    assert {
        "vrp_trade_candidates",
        "vrp_backtest_results",
        "vrp_backtest_trades",
        "vrp_paper_positions",
        "vrp_leg_nbbo",
    } <= names
