from uw_scan.models import regime_cri_vcg, regime_dealer, regime_gex, watchlist


PUBLIC_WATCHLIST_SCHEMA_NAMES = [
    "SetupBlock",
    "ReturnsBlock",
    "GammaBlock",
    "SkewBlock",
    "PositioningBlock",
    "QueueStatus",
    "WatchlistCard",
    "QueueSummary",
    "WatchlistResponse",
    "WatchlistMutation",
    "WatchlistPatch",
    "JobStatus",
    "OhlcRow",
]


def test_watchlist_schema_import_surface_and_module_identity():
    missing = [name for name in PUBLIC_WATCHLIST_SCHEMA_NAMES if not hasattr(watchlist, name)]

    assert missing == []
    for name in PUBLIC_WATCHLIST_SCHEMA_NAMES:
        assert getattr(watchlist, name).__module__ == "uw_scan.models.watchlist"


def test_watchlist_schema_defaults_stay_stable():
    assert watchlist.WatchlistMutation(ticker="TSLA", sector="Mega Cap").pinned is False
    assert watchlist.WatchlistMutation(ticker="TSLA", sector="Mega Cap").sort_rank == 0
    assert watchlist.QueueSummary().total == 0
    assert watchlist.WatchlistResponse(tickers=[]).queue.total == 0


def test_empty_singletons_remain_available_from_schemas():
    assert isinstance(regime_gex.EMPTY_GEX_RESPONSE, regime_gex.GexResponse)
    assert isinstance(regime_cri_vcg.EMPTY_CRI_RESPONSE, regime_cri_vcg.CriResponse)
    assert isinstance(regime_cri_vcg.EMPTY_VCG_RESPONSE, regime_cri_vcg.VcgResponse)
    assert isinstance(
        regime_dealer.EMPTY_DEALER_REGIME_RESPONSE,
        regime_dealer.DealerRegimeResponse,
    )
