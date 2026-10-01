"""The vendored S&P 500 list ships with the package and passes its own validation.

The file is copied from livewire presets/sp500.json (real constituents) by
scripts/research/sync_sp500_members.py. No network.
"""

from __future__ import annotations

import json
from importlib.resources import files

import pytest
from uw_scan.sources.sp500_members import (
    MIN_MEMBERS,
    Sp500ListInvalid,
    sp500_members,
    validate_tickers,
)


def test_vendored_list_is_large_unique_upper_case_and_current():
    tickers = sp500_members()
    assert len(tickers) >= MIN_MEMBERS
    assert len(set(tickers)) == len(tickers)
    assert all(t == t.upper() and t.strip() == t for t in tickers)
    # two of the names apex's membership route dropped on 2026-09-26
    assert {"META", "XOM"} <= set(tickers)


def test_vendored_file_records_its_provenance():
    body = json.loads(
        (files("uw_scan.sources") / "data" / "sp500_members.json").read_text()
    )
    assert body["source"].startswith("livewire presets/sp500.json @ ")
    assert len(body["source"].rsplit(" ", 1)[-1]) == 40  # full git commit hash
    assert body["as_of"]


def test_validate_rejects_duplicates_and_short_lists():
    good = list(sp500_members())
    assert validate_tickers(good) == tuple(sorted(good))
    with pytest.raises(Sp500ListInvalid, match="duplicate"):
        validate_tickers(good + [good[0].lower()])
    with pytest.raises(Sp500ListInvalid, match="450"):
        validate_tickers(good[:449])
    with pytest.raises(Sp500ListInvalid):
        validate_tickers(None)
