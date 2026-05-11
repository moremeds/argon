from uw_scan.api.client import build_request_fingerprint, normalize_params
from uw_scan.api.endpoints import UwEndpoint


def test_endpoint_paths_match_documented_operations():
    assert UwEndpoint.FLOW_ALERTS.path == "/api/option-trades/flow-alerts"
    assert UwEndpoint.FULL_TAPE.path == "/api/option-trades/full-tape/{date}"
    assert UwEndpoint.OPTION_CHAINS.path == "/api/stock/{ticker}/option-chains"
    assert UwEndpoint.OPTION_CONTRACTS.path == "/api/stock/{ticker}/option-contracts"
    assert UwEndpoint.OI_CHANGE.path == "/api/stock/{ticker}/oi-change"
    assert UwEndpoint.OI_PER_EXPIRY.path == "/api/stock/{ticker}/oi-per-expiry"
    assert UwEndpoint.OI_PER_STRIKE.path == "/api/stock/{ticker}/oi-per-strike"
    assert UwEndpoint.VOL_OI_PER_EXPIRY.path == "/api/stock/{ticker}/option/volume-oi-expiry"
    assert UwEndpoint.IV_RANK.path == "/api/stock/{ticker}/iv-rank"
    assert UwEndpoint.VOLATILITY_STATS.path == "/api/stock/{ticker}/volatility/stats"
    assert UwEndpoint.INTERPOLATED_IV.path == "/api/stock/{ticker}/interpolated-iv"
    assert UwEndpoint.REALIZED_VOLATILITY.path == "/api/stock/{ticker}/volatility/realized"
    assert UwEndpoint.IV_TERM_STRUCTURE.path == "/api/stock/{ticker}/volatility/term-structure"
    assert UwEndpoint.GREEKS.path == "/api/stock/{ticker}/greeks"
    assert UwEndpoint.GREEK_EXPOSURE_BY_STRIKE_EXPIRY.path == "/api/stock/{ticker}/greek-exposure/strike-expiry"
    assert UwEndpoint.SPOT_EXPOSURES_BY_STRIKE_EXPIRY.path == "/api/stock/{ticker}/spot-exposures/expiry-strike"
    assert UwEndpoint.MAX_PAIN.path == "/api/stock/{ticker}/max-pain"
    assert UwEndpoint.DARKPOOL_RECENT.path == "/api/darkpool/recent"
    assert UwEndpoint.DARKPOOL_TICKER.path == "/api/darkpool/{ticker}"


def test_normalize_params_sorts_keys_and_list_values():
    assert normalize_params({"b": "2", "a": ["NVDA", "AMD"], "empty": None}) == "a=AMD,NVDA&b=2"


def test_request_fingerprint_is_stable():
    first = build_request_fingerprint(
        endpoint="/api/stock/NVDA/option-contracts",
        params={"option_symbol": ["NVDA260619C00650000", "AMD260619C00210000"]},
        market_date="2026-05-11",
        api_base_url="https://api.unusualwhales.com",
    )
    second = build_request_fingerprint(
        endpoint="/api/stock/NVDA/option-contracts",
        params={"option_symbol": ["AMD260619C00210000", "NVDA260619C00650000"]},
        market_date="2026-05-11",
        api_base_url="https://api.unusualwhales.com",
    )
    assert first == second
    assert len(first) == 64
