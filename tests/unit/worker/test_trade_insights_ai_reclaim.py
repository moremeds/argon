"""A stale 'running' AI row is reclaimed only after ITS provider's timeout."""

from types import SimpleNamespace

from uw_scan.worker.jobs.trade_insights_ai import _reclaim_after_seconds

_SETTINGS = SimpleNamespace(
    trade_insights_ai_model="",
    trade_insights_ai_timeout_seconds=300,
    trade_insights_ai_claude_model="",
    trade_insights_ai_claude_timeout_seconds=600,
    trade_insights_ai_deepseek_model="",
    trade_insights_ai_deepseek_timeout_seconds=450,
)


def test_pinned_provider_uses_its_own_timeout():
    # Before: every pool used the codex timeout, so a Claude row with a 600 s
    # timeout was reclaimed at 361 s while its first run was still live.
    assert _reclaim_after_seconds(_SETTINGS, "claude") == 660
    assert _reclaim_after_seconds(_SETTINGS, "codex") == 360
    assert _reclaim_after_seconds(_SETTINGS, "deepseek") == 510


def test_any_provider_pool_waits_out_the_longest_timeout():
    assert _reclaim_after_seconds(_SETTINGS, None) == 660


def test_every_runner_names_real_settings_fields():
    # The lookup reads Settings by the runner-declared field names; a typo
    # would only surface when that provider's first row is claimed.
    from uw_scan.config import Settings
    from uw_scan.worker.jobs.trade_insights_ai import RUNNERS

    for runner in RUNNERS.values():
        assert runner.model_setting in Settings.model_fields, runner.name
        assert runner.timeout_setting in Settings.model_fields, runner.name
