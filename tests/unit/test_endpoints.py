import pytest

from uw_scan.api.endpoints import EndpointSlug, build_path


@pytest.mark.parametrize(
    "slug,expected",
    [
        (EndpointSlug.GEX_LEVELS, "/api/stock/AAPL/gex-levels"),
        (EndpointSlug.VOLATILITY_ANOMALY, "/api/stock/AAPL/volatility/anomaly"),
        (EndpointSlug.VOLATILITY_CHARACTER, "/api/stock/AAPL/volatility/character"),
        (
            EndpointSlug.VOLATILITY_VRP,
            "/api/stock/AAPL/volatility/variance-risk-premium",
        ),
        (EndpointSlug.NET_PREM_TICKS, "/api/stock/AAPL/net-prem-ticks"),
        (EndpointSlug.GREEK_FLOW, "/api/stock/AAPL/greek-flow"),
        (EndpointSlug.LIT_FLOW, "/api/lit-flow/AAPL"),
        (EndpointSlug.FTDS, "/api/shorts/AAPL/ftds"),
        (EndpointSlug.VOLUMES_BY_EXCHANGE, "/api/shorts/AAPL/volumes-by-exchange"),
    ],
)
def test_new_alpha_endpoint_paths(slug, expected):
    assert build_path(slug, "AAPL") == expected
