"""A stale 'running' AI row is reclaimed only after ITS provider's timeout."""

import pytest
from types import SimpleNamespace

from uw_scan.worker.jobs.trade_insights_ai import _reclaim_after_seconds
from uw_scan.worker.jobs.trade_insights_ai_runners import (
    TradeInsightsAiRunnerError,
)

_SETTINGS = SimpleNamespace(
    trade_insights_ai_deepseek_model="",
    trade_insights_ai_deepseek_timeout_seconds=450,
)


def test_pinned_provider_uses_its_own_timeout():
    assert _reclaim_after_seconds(_SETTINGS, "deepseek") == 510


def test_any_provider_pool_waits_out_the_longest_timeout():
    # DeepSeek is the only provider, so the legacy any-provider pool waits
    # out its timeout.
    assert _reclaim_after_seconds(_SETTINGS, None) == 510


def test_removed_provider_has_no_timeout():
    with pytest.raises(TradeInsightsAiRunnerError):
        _reclaim_after_seconds(_SETTINGS, "codex")
