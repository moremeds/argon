from decimal import Decimal

from uw_scan.analysis import build_stock_analysis
from uw_scan.sources.uw_analysis import build_analysis_inputs_from_payloads
from uw_scan.sources.uw_flow import flow_rows_from_payload


def test_build_analysis_inputs_from_uw_payloads_derives_report_inputs():
    flow_rows = flow_rows_from_payload(
        {
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
        source_label="UW Flow Poll",
        limit=100,
    )
    payloads = {
        "iv_rank": {"data": {"iv_rank": "3.37"}},
        "volatility_stats": {
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
        "flow_summary": {
            "data": {
                "net_premium": "524300000",
                "bull_premium": "2290000000",
                "bear_premium": "1770000000",
                "call_put_ratio": "0.94",
            }
        },
        "gex_flip": {"data": {"gex_flip": "376.25"}},
        "term_structure": {
            "data": [
                {"dte": "11", "iv": "38.6"},
                {"dte": "29", "iv": "41.5"},
                {"dte": "91", "iv": "45.0"},
            ]
        },
        "greek_exposure": {
            "data": [
                {"strike": "382.5", "gex": "100400000"},
                {"strike": "392.5", "gex": "28200000"},
                {"strike": "400", "gex": "20700000"},
                {"strike": "375", "gex": "-17900000"},
                {"strike": "370", "gex": "-44200000"},
                {"strike": "350", "gex": "-42800000"},
            ]
        },
        "spot_exposures": {"data": [{"strike": "380", "dex": "152500000"}]},
        "oi_per_strike": {
            "data": [
                {"strike": "385", "call_volume": "136564", "put_volume": "56586"},
                {"strike": "390", "call_volume": "114894", "put_volume": "52794"},
                {"strike": "380", "call_volume": "106881", "put_volume": "167016"},
            ]
        },
        "skew": {"data": {"put_25_delta_iv": "41.6", "call_25_delta_iv": "40.2"}},
        "darkpool": {"data": [{"premium": "1000000"}, {"premium": "1300000"}]},
        "short_interest": {"data": {"short_interest_ratio": "43.7", "z_score": "-0.78", "history_days": "122"}},
    }

    inputs = build_analysis_inputs_from_payloads(
        ticker="TSLA",
        flow_rows=flow_rows,
        payloads=payloads,
        data_date="3/24/2026",
    )
    analysis = build_stock_analysis(inputs)

    assert inputs.spot == Decimal("380.88")
    assert inputs.net_premium == Decimal("524300000")
    assert inputs.gex_flip == Decimal("376.25")
    assert inputs.call_put_ratio == Decimal("0.94")
    assert inputs.dark_pool_premium == Decimal("2300000")
    assert analysis.signal == "BUY"
    assert analysis.flow_positioning.oi_bias == "Bullish above $385"


def test_build_analysis_inputs_accepts_live_uw_field_names():
    flow_rows = flow_rows_from_payload(
        {
            "data": [
                {
                    "ticker": "SMH",
                    "option_symbol": "SMH260515P00565000",
                    "expiry": "2026-05-15",
                    "strike": "565",
                    "option_type": "put",
                    "premium": "750000",
                    "volume": "1200",
                    "open_interest": "300",
                    "side": "ask",
                    "dte": "4",
                }
            ]
        },
        source_label="UW Flow Poll",
        limit=10,
    )
    payloads = {
        "iv_rank": {"data": [{"iv_rank_1y": "18.5"}]},
        "volatility_stats": {
            "data": {
                "iv": "29.4",
                "rv": "21.1",
                "iv_low": "19.0",
                "iv_high": "55.0",
                "rv_low": "14.0",
                "rv_high": "48.0",
                "date": "2026-05-11",
            }
        },
        "term_structure": {
            "data": [
                {"dte": "4", "volatility": "28.0"},
                {"dte": "18", "volatility": "31.0"},
                {"dte": "46", "volatility": "34.0"},
            ]
        },
        "greek_exposure": {
            "data": [
                {"strike": "570", "call_gex": "12000000", "put_gex": "4000000"},
                {"strike": "560", "call_gex": "1000000", "put_gex": "-18000000"},
                {"strike": "550", "call_gex": "500000", "put_gex": "-12000000"},
            ]
        },
        "spot_exposures": {
            "data": [{"price": "565", "call_delta_vol": "2000000", "put_delta_vol": "-3500000"}]
        },
        "oi_per_strike": {"data": [{"strike": "565", "call_oi": "1234", "put_oi": "9876"}]},
        "darkpool": {"data": [{"premium": "100000"}]},
    }

    inputs = build_analysis_inputs_from_payloads(
        ticker="SMH",
        flow_rows=flow_rows,
        payloads=payloads,
        data_date="2026-05-11",
    )

    assert inputs.iv_rank == Decimal("18.5")
    assert inputs.near_term_iv_pct == Decimal("28.0")
    assert inputs.gex_levels[0].net_gex == Decimal("16000000")
    assert inputs.oi_rows[0].put_volume == 9876
    assert inputs.spot == Decimal("565")
