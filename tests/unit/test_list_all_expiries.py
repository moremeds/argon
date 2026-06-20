from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from uw_scan.cards.option_chain import list_all_expiries


def _c(sym: str):
    # The function only reads `.option_symbol`; SimpleNamespace duck-types OptionContractRow.
    return SimpleNamespace(option_symbol=sym)


def test_list_all_expiries_returns_all_future_sorted_dedup():
    contracts = [
        _c("TSLA  260717C00250000"),
        _c("TSLA  260717P00250000"),  # duplicate expiry, different right
        _c("TSLA  260620C00250000"),  # earlier expiry
        _c("TSLA  240101C00250000"),  # past -> excluded
    ]
    assert list_all_expiries(contracts, today=date(2026, 6, 19)) == [
        date(2026, 6, 20),
        date(2026, 7, 17),
    ]


def test_list_all_expiries_empty_when_no_parseable_contracts():
    assert list_all_expiries([_c("not-an-occ-symbol")], today=date(2026, 6, 19)) == []
