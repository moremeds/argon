from datetime import datetime, timezone


def test_trade_insight_snapshot_upsert_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("TSLA")
    payload = {
        "ticker": "TSLA",
        "header": {
            "confidence_label": "LOW",
            "data_quality_label": "INSUFFICIENT",
            "preferred_idea_id": None,
        },
        "source_reconciliation": {"status": "UNKNOWN"},
        "candidate_structures": [
            {
                "idea_id": "A",
                "structure": "call_credit_spread",
                "expression_type": "SHORT_VOL",
                "rank": 1,
                "status": "needs_check",
                "max_loss": "3.75",
                "risk_flags": ["event_check_required"],
                "legs": [],
            }
        ],
    }

    kwargs = {
        "run_id": run_id,
        "ticker": "TSLA",
        "as_of": datetime(2026, 5, 13, tzinfo=timezone.utc),
        "assembler_version": "trade-insights-v1",
        "input_hash": "abc123",
        "payload": payload,
    }
    first = repo.upsert_trade_insight_snapshot(**kwargs)
    second = repo.upsert_trade_insight_snapshot(**kwargs)
    assert first == second

    written = repo.replace_trade_insight_candidates(
        snapshot_id=first,
        run_id=run_id,
        ticker="TSLA",
        candidates=payload["candidate_structures"],
    )
    assert written == 1
