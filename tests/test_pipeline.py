from uw_scan.config import UwScanConfig
from uw_scan.ingest.pipeline import dashboard_for_mode, run_fixture_pipeline, run_live_pipeline


def test_fixture_pipeline_returns_dashboard_and_budget():
    dashboard = run_fixture_pipeline(UwScanConfig())
    assert dashboard.opportunities
    assert dashboard.request_budget.total_estimated_requests > 0


def test_live_mode_without_api_key_returns_fixture_with_warning():
    dashboard, notices = dashboard_for_mode("Live polling", UwScanConfig(api_key=None))

    assert dashboard.opportunities
    assert notices
    assert notices[0].level == "warning"
    assert "UW_SCAN_API_KEY" in notices[0].message


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *, endpoint, params, market_date):
        return type(
            "FakeResponse",
            (),
            {
                "endpoint": endpoint,
                "params": params,
                "status_code": 200,
                "json_payload": self.payload,
                "latency_ms": 12,
                "request_fingerprint": "abc",
            },
        )()


class _RoutingFakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, *, endpoint, params, market_date):
        self.calls.append((endpoint, params, market_date))
        for marker, payload in self.routes.items():
            if marker in endpoint:
                return type(
                    "FakeResponse",
                    (),
                    {
                        "endpoint": endpoint,
                        "params": params,
                        "status_code": 200,
                        "json_payload": payload,
                        "latency_ms": 12,
                        "request_fingerprint": marker.replace("/", "") or "abc",
                    },
                )()
        raise AssertionError(f"unexpected endpoint {endpoint}")


def test_live_pipeline_turns_flow_alerts_into_opportunities():
    payload = {
        "data": [
            {
                "ticker": "NVDA",
                "option_symbol": "NVDA260619C00650000",
                "expiry": "2026-06-19",
                "strike": "650",
                "option_type": "call",
                "premium": "1250000",
                "volume": "2400",
                "open_interest": "900",
                "side": "ask",
                "ask_side_pct": "0.88",
                "dte": "39",
            }
        ]
    }

    dashboard, notices = run_live_pipeline(UwScanConfig(api_key="test-key"), client=_FakeClient(payload))

    assert notices[0].level == "success"
    assert dashboard.flow_rows[0].ticker == "NVDA"
    assert dashboard.opportunities[0].score == 5
    assert dashboard.opportunities[0].structure_idea is not None


def test_live_pipeline_builds_computed_stock_analysis_from_enrichment_payloads():
    routes = {
        "flow-alerts": {
            "data": [
                {
                    "ticker": "TSLA",
                    "option_symbol": "TSLA260417C00385000",
                    "expiry": "2026-04-17",
                    "strike": "385",
                    "option_type": "call",
                    "premium": "524300000",
                    "volume": "136564",
                    "open_interest": "56586",
                    "side": "ask",
                    "dte": "24",
                }
            ]
        },
        "iv-rank": {"data": {"iv_rank": "3.37"}},
        "volatility/stats": {
            "data": {
                "price": "380.88",
                "implied_volatility": "42.0",
                "historical_volatility": "31.1",
                "iv_low_52w": "39.3",
                "iv_high_52w": "107.2",
                "rv_low_52w": "28.5",
                "rv_high_52w": "112.9",
                "vrp": "7.6",
                "date": "2026-03-19",
            }
        },
        "term-structure": {"data": [{"dte": "11", "iv": "38.6"}, {"dte": "29", "iv": "41.5"}, {"dte": "91", "iv": "45.0"}]},
        "greek-exposure": {
            "data": [
                {"strike": "382.5", "gex": "100400000"},
                {"strike": "392.5", "gex": "28200000"},
                {"strike": "400", "gex": "20700000"},
                {"strike": "375", "gex": "-17900000"},
                {"strike": "370", "gex": "-44200000"},
                {"strike": "350", "gex": "-42800000"},
            ]
        },
        "spot-exposures": {"data": [{"strike": "380", "dex": "152500000"}]},
        "oi-per-strike": {"data": [{"strike": "385", "call_volume": "136564", "put_volume": "56586"}]},
        "darkpool": {"data": [{"premium": "2300000"}]},
    }

    client = _RoutingFakeClient(routes)
    dashboard, notices = run_live_pipeline(UwScanConfig(api_key="test-key"), client=client)

    assert notices[0].level == "success"
    called_endpoints = " ".join(endpoint for endpoint, _, _ in client.calls)
    assert "iv-rank" in called_endpoints
    assert "greek-exposure" in called_endpoints
    assert dashboard.stock_analyses
    assert dashboard.stock_analyses[0].ticker == "TSLA"
    assert dashboard.stock_analyses[0].signal == "BUY"
    assert dashboard.stock_analyses[0].trade_plan.title == "Bull Call Spread - TSLA"


def test_live_pipeline_enriches_ranked_distinct_tickers_up_to_cap():
    routes = {
        "flow-alerts": {
            "data": [
                {
                    "ticker": "TSLA",
                    "option_symbol": "TSLA260417C00385000",
                    "expiry": "2026-04-17",
                    "strike": "385",
                    "option_type": "call",
                    "premium": "524300000",
                    "volume": "136564",
                    "open_interest": "56586",
                    "side": "ask",
                    "dte": "24",
                },
                {
                    "ticker": "NVDA",
                    "option_symbol": "NVDA260619C00650000",
                    "expiry": "2026-06-19",
                    "strike": "650",
                    "option_type": "call",
                    "premium": "1250000",
                    "volume": "2400",
                    "open_interest": "900",
                    "side": "ask",
                    "dte": "39",
                },
            ]
        },
        "iv-rank": {"data": {"iv_rank": "3.37"}},
        "volatility/stats": {
            "data": {
                "price": "380.88",
                "implied_volatility": "42.0",
                "historical_volatility": "31.1",
                "iv_low_52w": "39.3",
                "iv_high_52w": "107.2",
                "rv_low_52w": "28.5",
                "rv_high_52w": "112.9",
                "vrp": "7.6",
                "date": "2026-03-19",
            }
        },
        "term-structure": {"data": [{"dte": "11", "iv": "38.6"}, {"dte": "29", "iv": "41.5"}, {"dte": "91", "iv": "45.0"}]},
        "greek-exposure": {
            "data": [
                {"strike": "382.5", "gex": "100400000"},
                {"strike": "392.5", "gex": "28200000"},
                {"strike": "400", "gex": "20700000"},
                {"strike": "375", "gex": "-17900000"},
                {"strike": "370", "gex": "-44200000"},
                {"strike": "350", "gex": "-42800000"},
            ]
        },
        "spot-exposures": {"data": [{"strike": "380", "dex": "152500000"}]},
        "oi-per-strike": {"data": [{"strike": "385", "call_volume": "136564", "put_volume": "56586"}]},
        "darkpool": {"data": [{"premium": "2300000"}]},
    }

    client = _RoutingFakeClient(routes)
    dashboard, notices = run_live_pipeline(UwScanConfig(api_key="test-key", max_analysis_tickers=2), client=client)

    analyzed_tickers = [analysis.ticker for analysis in dashboard.stock_analyses]
    assert analyzed_tickers == ["TSLA", "NVDA"]
    called_endpoints = " ".join(endpoint for endpoint, _, _ in client.calls)
    assert "/api/stock/TSLA/iv-rank" in called_endpoints
    assert "/api/stock/NVDA/iv-rank" in called_endpoints
    assert "Built computed analyses for 2 tickers" in " ".join(notice.message for notice in notices)
