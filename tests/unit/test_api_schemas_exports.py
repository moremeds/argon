from uw_scan.api import schemas


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
    missing = [name for name in PUBLIC_WATCHLIST_SCHEMA_NAMES if not hasattr(schemas, name)]

    assert missing == []
    for name in PUBLIC_WATCHLIST_SCHEMA_NAMES:
        assert getattr(schemas, name).__module__ == "uw_scan.api.schemas"


def test_watchlist_schema_defaults_stay_stable():
    assert schemas.WatchlistMutation(ticker="TSLA", sector="Mega Cap").pinned is False
    assert schemas.WatchlistMutation(ticker="TSLA", sector="Mega Cap").sort_rank == 0
    assert schemas.QueueSummary().total == 0
    assert schemas.WatchlistResponse(tickers=[]).queue.total == 0


def test_empty_singletons_remain_available_from_schemas():
    assert isinstance(schemas.EMPTY_GEX_RESPONSE, schemas.GexResponse)
    assert isinstance(schemas.EMPTY_CRI_RESPONSE, schemas.CriResponse)
    assert isinstance(schemas.EMPTY_VCG_RESPONSE, schemas.VcgResponse)
    assert isinstance(
        schemas.EMPTY_DEALER_REGIME_RESPONSE,
        schemas.DealerRegimeResponse,
    )
