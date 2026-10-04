"""live_or_eod: the regime live endpoints' shared fallback rule (I-37)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.scanners.live_quotes import live_or_eod


class _Repo:
    def __init__(self, quoted_at: datetime) -> None:
        self._row = SimpleNamespace(
            ticker="VIX", price=25.5, quoted_at=quoted_at, source="xenon_ws"
        )

    def get_intraday_quotes(self, symbols):
        return [self._row] if "VIX" in symbols else []


SETTINGS = Settings(api_key=SecretStr("test"))
NOW = datetime.now(timezone.utc)


def test_fresh_quotes_reach_live_and_skip_eod():
    eod_calls = []
    out = live_or_eod(
        _Repo(NOW),
        SETTINGS,
        lambda q: f"live:{sorted(q)}",
        lambda: eod_calls.append(1) or "eod",
    )
    assert out == "live:['VIX']"
    assert eod_calls == []


def test_live_none_falls_back_to_eod():
    assert live_or_eod(_Repo(NOW), SETTINGS, lambda q: None, lambda: "eod") == "eod"


def test_stale_quotes_reach_live_as_empty():
    stale = NOW - timedelta(seconds=SETTINGS.regime_live_quote_max_age_seconds + 60)
    seen = []
    out = live_or_eod(
        _Repo(stale), SETTINGS, lambda q: seen.append(dict(q)) or None, lambda: "eod"
    )
    assert out == "eod"
    assert seen == [{}]
