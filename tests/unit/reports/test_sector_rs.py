"""sector_rs compute against frozen REAL closes (fixture as-of 2026-09-18).

Fixture: tests/unit/reports/fixtures/sector_rs_closes_2026-09-18.json — apex
bulk GET /v1/equity/bars, 1d, price_mode=adjusted, listing=any; the 260 sessions
2025-09-08 → 2026-09-18 for SPY, XLK, AAPL, MSFT, NVDA. No network.

Numeric checks are made twice: once against an index-based recomputation from
the fixture (authoritative), and once against the literal measured when the
fixture was frozen (adjustment_revision 81). A silent formula change fails the
first; a silent fixture swap fails the second.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from uw_scan.reports.sector_rs import (
    WINDOWS,
    GroupSpec,
    compute_group_rows,
    window_return,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "sector_rs_closes_2026-09-18.json"
AS_OF = date(2026, 9, 18)
TECH = ("AAPL", "MSFT", "NVDA")
ETF_TECH = GroupSpec("gics", "Technology", "etf", "XLK", TECH)
EQUAL_TECH = GroupSpec("chain", "Tech-Trio", "equal", None, TECH)


def _closes() -> dict[str, list[tuple[date, float]]]:
    raw = json.loads(_FIXTURE.read_text())
    return {
        s: [(date.fromisoformat(d), float(c)) for d, c in rows]
        for s, rows in raw["closes"].items()
    }


def _ret(series: list[tuple[date, float]], n: int) -> float:
    c = [x for _, x in series]
    return c[-1] / c[-1 - n] - 1.0


def test_fixture_is_the_frozen_window():
    closes = _closes()
    spy_dates = [d for d, _ in closes["SPY"]]
    assert len(spy_dates) == 260 and spy_dates[-1] == AS_OF
    for s in ("XLK", *TECH):
        assert [d for d, _ in closes[s]] == spy_dates, s


def test_window_return_needs_n_plus_one_closes():
    spy = [c for _, c in _closes()["SPY"]]
    assert window_return(spy[:21], 21) is None
    assert window_return(spy[:22], 21) == pytest.approx(spy[21] / spy[0] - 1.0)
    assert window_return(spy, 0) is None


def test_etf_rs_is_etf_return_minus_spy_in_points():
    closes = _closes()
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    for label, n in WINDOWS.items():
        expected = (_ret(closes["XLK"], n) - _ret(closes["SPY"], n)) * 100.0
        assert row.rs[label] == pytest.approx(expected, abs=1e-9), label
    # literals at adjustment_revision 81: XLK lagged SPY over 3m, led over 12m
    assert row.rs["3m"] == pytest.approx(-3.098, abs=0.01)
    assert row.rs["12m"] == pytest.approx(23.315, abs=0.01)
    assert row.rs_symbol == "XLK" and row.weighting == "etf"
    assert row.as_of == AS_OF and row.source == "apex"


def test_equal_weighting_uses_the_member_mean_not_the_etf():
    closes = _closes()
    (row,) = compute_group_rows(AS_OF, [EQUAL_TECH], closes)
    n = WINDOWS["12m"]
    mean = sum(_ret(closes[m], n) for m in TECH) / len(TECH)
    assert row.rs["12m"] == pytest.approx(
        (mean - _ret(closes["SPY"], n)) * 100.0, abs=1e-9
    )
    assert row.rs["12m"] == pytest.approx(6.083, abs=0.02)
    assert row.rs_symbol is None and row.weighting == "equal"


def test_breadth_counts_members_beating_spy():
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], _closes())
    # 12m: MSFT −2.39% vs SPY +17.12%; AAPL and NVDA beat it
    assert row.breadth["12m"] == pytest.approx(2 / 3)
    assert row.breadth["1m"] == pytest.approx(1.0)
    assert (row.n_members, row.n_classified, row.n_priced) == (3, 3, 3)
    assert row.degraded is False


def test_member_short_a_window_is_unpriced_and_degrades():
    closes = _closes()
    closes["NVDA"] = closes["NVDA"][-200:]  # starts after the 12m anchor
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert row.n_priced == 2  # the 12m count
    assert row.breadth["12m"] == pytest.approx(1 / 2)  # AAPL beats, MSFT does not
    assert row.breadth["1m"] == pytest.approx(1.0)  # all three priced over 1m
    assert row.degraded is True  # 2 < 0.8 * 3


def test_member_delisted_mid_window_is_not_priced_on_a_stale_window():
    closes = _closes()
    closes["NVDA"] = closes["NVDA"][:-10]  # bars stop 10 sessions before as_of
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert row.n_priced == 2
    # 2 of 2 priced members beat SPY over 1m; NVDA is absent, not stale-priced
    assert row.breadth["1m"] == pytest.approx(1.0)
    assert row.degraded is True


def test_member_absent_from_closes_is_unpriced_not_zero():
    # A delisted former member lands in apex's bulk `missing` map (no Silver for
    # delisted names), so it is absent from `closes`: counted in n_members,
    # never in n_priced, and never a 0% return.
    closes = _closes()
    del closes["MSFT"]
    (row,) = compute_group_rows(AS_OF, [EQUAL_TECH], closes)
    assert (row.n_members, row.n_priced) == (3, 2)
    assert row.breadth["12m"] == pytest.approx(1.0)  # AAPL and NVDA both beat SPY
    n = WINDOWS["12m"]
    mean = (_ret(closes["AAPL"], n) + _ret(closes["NVDA"], n)) / 2
    assert row.rs["12m"] == pytest.approx(
        (mean - _ret(closes["SPY"], n)) * 100.0, abs=1e-9
    )
    assert row.degraded is True  # 2 < 0.8 * 3


def test_missing_etf_gives_null_rs_and_degraded_but_keeps_breadth():
    closes = _closes()
    del closes["XLK"]
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert all(v is None for v in row.rs.values())
    assert row.degraded is True
    assert row.breadth["12m"] == pytest.approx(2 / 3)


def test_rs_valid_from_nulls_only_the_windows_that_start_before_it():
    # 1m starts 21 sessions before 2026-09-18 (late August); 12m starts in 2025-09.
    g = GroupSpec(
        "gics", "Technology", "etf", "XLK", TECH, rs_valid_from=date(2026, 8, 1)
    )
    (row,) = compute_group_rows(AS_OF, [g], _closes())
    assert row.rs["1m"] is not None
    assert row.rs["3m"] is None and row.rs["6m"] is None and row.rs["12m"] is None
    assert row.degraded is True  # 12m RS input missing
    assert row.breadth["12m"] == pytest.approx(2 / 3)  # breadth ignores the ETF


def test_single_member_group():
    (row,) = compute_group_rows(
        AS_OF, [GroupSpec("chain", "Solo", "equal", None, ("MSFT",))], _closes()
    )
    assert row.breadth["12m"] == 0.0
    assert row.rs["12m"] == pytest.approx(-19.509, abs=0.01)
    assert row.n_priced == 1 and row.degraded is False


def test_empty_group_is_degraded_with_null_breadth():
    (row,) = compute_group_rows(
        AS_OF, [GroupSpec("gics", "Energy", "etf", "XLK", ())], _closes()
    )
    assert row.n_members == 0 and row.n_priced == 0
    assert row.degraded is True
    assert all(v is None for v in row.breadth.values())


def test_missing_or_short_benchmark_raises():
    closes = _closes()
    del closes["SPY"]
    with pytest.raises(ValueError):
        compute_group_rows(AS_OF, [ETF_TECH], closes)
    closes = _closes()
    closes["SPY"] = closes["SPY"][-100:]
    with pytest.raises(ValueError, match="12m"):
        compute_group_rows(AS_OF, [ETF_TECH], closes)


def test_bars_after_as_of_are_ignored():
    closes = _closes()
    earlier = date(2026, 9, 11)
    (row,) = compute_group_rows(earlier, [ETF_TECH], closes)
    cut = {s: [(d, c) for d, c in v if d <= earlier] for s, v in closes.items()}
    n = WINDOWS["1m"]
    expected = (_ret(cut["XLK"], n) - _ret(cut["SPY"], n)) * 100.0
    assert row.rs["1m"] == pytest.approx(expected, abs=1e-9)
    assert row.as_of == earlier


def test_non_trading_as_of_uses_the_last_session():
    closes = _closes()
    (sat,) = compute_group_rows(date(2026, 9, 19), [ETF_TECH], closes)
    (fri,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert sat.rs == fri.rs and sat.breadth == fri.breadth


def test_unknown_weighting_is_refused():
    with pytest.raises(ValueError, match="weighting"):
        compute_group_rows(
            AS_OF, [GroupSpec("chain", "X", "cap", None, TECH)], _closes()
        )
