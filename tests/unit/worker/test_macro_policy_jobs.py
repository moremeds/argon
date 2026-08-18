from __future__ import annotations

import pytest

from uw_scan.worker.jobs.macro_policy_jobs import _fetch_with_retry


class _TransientProvider:
    calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch(self):
        type(self).calls += 1
        if type(self).calls < 3:
            raise OSError("temporary publisher failure")
        return "release"


def test_fetch_retry_is_bounded_and_uses_exponential_backoff() -> None:
    _TransientProvider.calls = 0
    sleeps: list[float] = []

    result = _fetch_with_retry(
        lambda provider: provider.fetch(),
        provider_factory=_TransientProvider,
        max_attempts=3,
        backoff_base_seconds=2,
        sleep_fn=sleeps.append,
    )

    assert result == "release"
    assert _TransientProvider.calls == 3
    assert sleeps == [2, 4]


def test_fetch_retry_stops_after_configured_attempts() -> None:
    _TransientProvider.calls = 0

    with pytest.raises(OSError, match="temporary publisher failure"):
        _fetch_with_retry(
            lambda provider: provider.fetch(),
            provider_factory=_TransientProvider,
            max_attempts=2,
            backoff_base_seconds=0,
            sleep_fn=lambda _delay: None,
        )

    assert _TransientProvider.calls == 2
