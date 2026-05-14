from uw_scan.config import Settings


def test_trade_insights_ai_default_timeout_matches_deep_prompt_budget():
    settings = Settings(
        api_key="dummy",
    )

    assert settings.trade_insights_ai_timeout_seconds == 300.0
