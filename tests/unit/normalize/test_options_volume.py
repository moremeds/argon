import json
from decimal import Decimal
from pathlib import Path

import pytest

from uw_scan.normalize import NormalizationError, normalize_options_volume_daily

FIXTURE = Path(__file__).parents[2] / "fixtures" / "options_volume_googl.json"


def test_normalize_options_volume_happy_path() -> None:
    payload = json.loads(FIXTURE.read_text())
    rows = normalize_options_volume_daily(payload)

    assert len(rows) == 5
    first = rows[0]
    assert first.call_volume is not None
    assert first.put_volume is not None
    assert isinstance(first.bullish_premium, Decimal) or first.bullish_premium is None
    assert first.avg_30_day_call_volume is not None


def test_normalize_options_volume_missing_data_key() -> None:
    with pytest.raises(NormalizationError):
        normalize_options_volume_daily({})


def test_normalize_options_volume_empty_data_is_ok() -> None:
    rows = normalize_options_volume_daily({"data": []})
    assert rows == []
