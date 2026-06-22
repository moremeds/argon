from datetime import date

from uw_scan.reports.vrp_gate import (
    GateResult,
    passes_gate,
    sellable_asset_classes,
    sellable_single_name_sectors,
)


class _StubRepo:
    """Minimal stand-in exposing only the repo methods the gate reads."""

    def __init__(self, *, sectors=None, earnings=None, by_sector=None, multih=None):
        self._sectors = sectors or {}
        self._earnings = earnings or {}
        self._by_sector = by_sector or []
        self._multih = multih or []

    def fetch_watchlist_sector(self, ticker):
        return self._sectors.get(ticker)

    def fetch_historical_earnings_dates(self, ticker):
        return self._earnings.get(ticker, set())

    def fetch_vrp_harvest_by_sector(self):
        return self._by_sector

    def fetch_vrp_harvest_multihorizon(self):
        return self._multih


def _mh(ac, horizon, verdict="HARVEST_SELLABLE", dev="RICH"):
    return {
        "asset_class": ac,
        "horizon": horizon,
        "deviation_class": dev,
        "verdict": verdict,
    }


# ── single_name path ─────────────────────────────────────────────────────────
def test_single_name_admitted_when_sector_sellable_and_has_earnings():
    repo = _StubRepo(sectors={"NVDA": "Semis"}, earnings={"NVDA": {date(2025, 2, 26)}})
    g = passes_gate(repo, "NVDA", sellable_sectors={"Semis"}, sellable_classes=set())
    assert g == GateResult(asset_class="single_name", bucket_key="Semis")


def test_single_name_excluded_without_earnings_calendar():
    repo = _StubRepo(sectors={"NVDA": "Semis"}, earnings={})  # no calendar
    assert (
        passes_gate(repo, "NVDA", sellable_sectors={"Semis"}, sellable_classes=set())
        is None
    )


def test_single_name_excluded_when_sector_not_sellable():
    repo = _StubRepo(sectors={"NVDA": "Semis"}, earnings={"NVDA": {date(2025, 2, 26)}})
    assert (
        passes_gate(repo, "NVDA", sellable_sectors={"Energy"}, sellable_classes=set())
        is None
    )


# ── macro path (index_macro / sector_etf / credit) ───────────────────────────
def test_macro_index_admitted_on_asset_class_without_earnings():
    # SPX classifies as index_macro and has NO earnings calendar — still admitted.
    repo = _StubRepo(sectors={"SPX": None}, earnings={})
    g = passes_gate(
        repo, "SPX", sellable_sectors=set(), sellable_classes={"index_macro"}
    )
    assert g == GateResult(asset_class="index_macro", bucket_key="index_macro")


def test_macro_excluded_when_asset_class_not_sellable():
    repo = _StubRepo(sectors={"SPX": None})
    assert (
        passes_gate(repo, "SPX", sellable_sectors=set(), sellable_classes=set()) is None
    )


# ── sellable-set helpers ─────────────────────────────────────────────────────
def test_sellable_asset_classes_filters_horizon_and_excludes_single_name():
    repo = _StubRepo(
        multih=[
            _mh("index_macro", 20),
            _mh("sector_etf", 20),
            _mh("credit", 20),
            _mh("single_name", 20),  # excluded: single_name has its own gate
            _mh("index_macro", 60, verdict="NONE"),  # excluded: not sellable
            _mh("index_macro", 5),  # excluded: wrong horizon for hold=20
        ]
    )
    assert sellable_asset_classes(repo, hold_days=20) == {
        "index_macro",
        "sector_etf",
        "credit",
    }


def test_sellable_single_name_sectors_only_rich_sellable():
    repo = _StubRepo(
        by_sector=[
            {
                "sector": "Semis",
                "deviation_class": "RICH",
                "verdict": "HARVEST_SELLABLE",
            },
            {"sector": "Energy", "deviation_class": "RICH", "verdict": "NONE"},
            {
                "sector": "Banks",
                "deviation_class": "CHEAP",
                "verdict": "HARVEST_SELLABLE",
            },
        ]
    )
    assert sellable_single_name_sectors(repo) == {"Semis"}
