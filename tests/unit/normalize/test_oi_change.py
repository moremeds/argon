import json
from decimal import Decimal
from pathlib import Path

from uw_scan.normalize import normalize_oi_change

FIXTURE = Path(__file__).parents[2] / "fixtures" / "oi_change_googl.json"


def test_oi_change_has_aggressor_fields() -> None:
    payload = json.loads(FIXTURE.read_text())
    rows = normalize_oi_change(payload)

    assert rows, "fixture should contain at least one row"
    assert all(hasattr(r, "prev_ask_volume") for r in rows)
    assert all(hasattr(r, "prev_bid_volume") for r in rows)
    assert all(hasattr(r, "prev_total_premium") for r in rows)
    assert all(hasattr(r, "last_ask") for r in rows)

    populated = [r for r in rows if r.prev_ask_volume is not None]
    assert populated, "at least one row should carry an aggressor breakdown"
    sample = populated[0]
    assert isinstance(sample.prev_ask_volume, int)
    assert (
        isinstance(sample.prev_total_premium, Decimal)
        or sample.prev_total_premium is None
    )
