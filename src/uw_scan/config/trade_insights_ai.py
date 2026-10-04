"""Trade Insights AI (DeepSeek) worker settings (D6 concern group: trade_insights_ai)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, SecretStr

from uw_scan.config._env import EnvVar


class TradeInsightsAiSettings(BaseModel):
    # Trade Insights AI shared runner knobs (DeepSeek is the only provider)
    trade_insights_ai_max_output_bytes: Annotated[
        int, EnvVar("TRADE_INSIGHTS_AI_MAX_OUTPUT_BYTES")
    ] = 262144
    trade_insights_ai_poll_seconds: Annotated[
        int, EnvVar("TRADE_INSIGHTS_AI_POLL_SECONDS")
    ] = 3
    # Trade Insights AI DeepSeek provider
    trade_insights_ai_deepseek_enabled: Annotated[
        bool, EnvVar("TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED")
    ] = True
    trade_insights_ai_deepseek_model: Annotated[
        str, EnvVar("TRADE_INSIGHTS_AI_DEEPSEEK_MODEL")
    ] = ""
    trade_insights_ai_deepseek_timeout_seconds: Annotated[
        float, EnvVar("TRADE_INSIGHTS_AI_DEEPSEEK_TIMEOUT_SECONDS")
    ] = 300.0
    trade_insights_ai_deepseek_worker_count: Annotated[
        int, EnvVar("TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT")
    ] = 2
    deepseek_api_key: Annotated[
        SecretStr | None, EnvVar("DEEPSEEK_API_KEY", strip=True, blank_is_default=True)
    ] = None
