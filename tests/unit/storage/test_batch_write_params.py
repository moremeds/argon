from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan import models
from uw_scan.storage.flow import _flow_event_params
from uw_scan.storage.flow import _FlowMixin
from uw_scan.storage.options import (
    _OptionsMixin,
    _greek_exposure_params,
    _greeks_params,
    _iv_term_params,
    _option_contract_params,
)
from uw_scan.storage.volatility_raw import (
    _VolatilityRawMixin,
    _iv_rank_params,
    _realized_vol_params,
    _skew_params,
    _volatility_stats_params,
)


def test_options_param_builders_preserve_order_and_values():
    iv_rows = [
        models.TermStructureRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            dte=32,
            volatility=Decimal("0.42"),
            implied_move=Decimal("12.3"),
            implied_move_perc=Decimal("0.031"),
        ),
        models.TermStructureRow(
            ticker="NVDA",
            date=date(2026, 5, 18),
            expiry=date(2026, 7, 17),
            dte=60,
            volatility=Decimal("0.51"),
        ),
    ]
    assert _iv_term_params(77, iv_rows) == [
        (
            77,
            "TSLA",
            date(2026, 5, 18),
            date(2026, 6, 19),
            32,
            Decimal("0.42"),
            Decimal("12.3"),
            Decimal("0.031"),
        ),
        (
            77,
            "NVDA",
            date(2026, 5, 18),
            date(2026, 7, 17),
            60,
            Decimal("0.51"),
            None,
            None,
        ),
    ]

    exposure_rows = [
        models.GreekExposureRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("450"),
            dte=32,
            call_delta=Decimal("0.51"),
            put_delta=Decimal("-0.49"),
            call_gex=Decimal("1000"),
            put_gex=Decimal("-900"),
            call_vanna=Decimal("12"),
            put_vanna=Decimal("-11"),
            call_charm=Decimal("5"),
            put_charm=Decimal("-4"),
        )
    ]
    assert _greek_exposure_params(78, "TSLA", exposure_rows) == [
        (
            78,
            "TSLA",
            date(2026, 5, 18),
            date(2026, 6, 19),
            Decimal("450"),
            32,
            Decimal("0.51"),
            Decimal("-0.49"),
            Decimal("1000"),
            Decimal("-900"),
            Decimal("12"),
            Decimal("-11"),
            Decimal("5"),
            Decimal("-4"),
        )
    ]

    greeks_rows = [
        models.GreeksRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("450"),
            call_delta=Decimal("0.51"),
            put_delta=Decimal("-0.49"),
            call_gamma=Decimal("0.02"),
            put_gamma=Decimal("0.03"),
            call_vega=Decimal("1.2"),
            put_vega=Decimal("1.1"),
            call_theta=Decimal("-0.1"),
            put_theta=Decimal("-0.2"),
            call_rho=Decimal("0.04"),
            put_rho=Decimal("-0.03"),
            call_vanna=Decimal("12"),
            put_vanna=Decimal("-11"),
            call_charm=Decimal("5"),
            put_charm=Decimal("-4"),
            call_volatility=Decimal("0.42"),
            put_volatility=Decimal("0.44"),
            call_option_symbol="TSLA260619C00450000",
            put_option_symbol="TSLA260619P00450000",
        )
    ]
    assert _greeks_params(79, "TSLA", greeks_rows) == [
        (
            79,
            "TSLA",
            date(2026, 5, 18),
            date(2026, 6, 19),
            Decimal("450"),
            Decimal("0.51"),
            Decimal("-0.49"),
            Decimal("0.02"),
            Decimal("0.03"),
            Decimal("1.2"),
            Decimal("1.1"),
            Decimal("-0.1"),
            Decimal("-0.2"),
            Decimal("0.04"),
            Decimal("-0.03"),
            Decimal("12"),
            Decimal("-11"),
            Decimal("5"),
            Decimal("-4"),
            Decimal("0.42"),
            Decimal("0.44"),
            "TSLA260619C00450000",
            "TSLA260619P00450000",
        )
    ]

    contract_rows = [
        models.OptionContractRow(
            option_symbol="TSLA260619C00450000",
            last_price=Decimal("12.1"),
            nbbo_bid=Decimal("12"),
            nbbo_ask=Decimal("12.2"),
            implied_volatility=Decimal("0.42"),
            open_interest=1000,
            prev_oi=900,
            volume=300,
            ask_volume=200,
            bid_volume=80,
            mid_volume=20,
            multi_leg_volume=10,
            stock_multi_leg_volume=5,
            floor_volume=2,
            sweep_volume=7,
            no_side_volume=1,
            avg_price=Decimal("12.05"),
            high_price=Decimal("12.5"),
            low_price=Decimal("11.9"),
            total_premium=Decimal("36150"),
        )
    ]
    assert _option_contract_params(80, "TSLA", contract_rows) == [
        (
            80,
            "TSLA",
            "TSLA260619C00450000",
            Decimal("12.1"),
            Decimal("12"),
            Decimal("12.2"),
            Decimal("0.42"),
            1000,
            900,
            300,
            200,
            80,
            20,
            10,
            5,
            2,
            7,
            1,
            Decimal("12.05"),
            Decimal("12.5"),
            Decimal("11.9"),
            Decimal("36150"),
        )
    ]


class _FakeCursor:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, object | None]] = []
        self.executemany_calls: list[tuple[str, list[tuple[object, ...]]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, sql: str, params: object | None = None) -> None:
        self.execute_calls.append((sql, params))

    def executemany(self, sql: str, params: list[tuple[object, ...]]) -> None:
        self.executemany_calls.append((sql, params))


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


class _FakeRepository(_OptionsMixin, _VolatilityRawMixin, _FlowMixin):
    def __init__(self) -> None:
        self._conn = _FakeConnection()
        self._schema = "uw_scan"

    @property
    def fake_cursor(self) -> _FakeCursor:
        return self._conn.cursor_obj


def _sample_iv_rows() -> list[models.TermStructureRow]:
    return [
        models.TermStructureRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            dte=32,
            volatility=Decimal("0.42"),
        ),
        models.TermStructureRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            expiry=date(2026, 7, 17),
            dte=60,
            volatility=Decimal("0.51"),
        ),
    ]


def _sample_exposure_rows() -> list[models.GreekExposureRow]:
    return [
        models.GreekExposureRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("450"),
            dte=32,
            call_gex=Decimal("1000"),
        ),
        models.GreekExposureRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("460"),
            dte=32,
            call_gex=Decimal("1100"),
        ),
    ]


def _sample_greeks_rows() -> list[models.GreeksRow]:
    return [
        models.GreeksRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("450"),
            call_delta=Decimal("0.51"),
            put_delta=Decimal("-0.49"),
        ),
        models.GreeksRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("460"),
            call_delta=Decimal("0.45"),
            put_delta=Decimal("-0.55"),
        ),
    ]


def _sample_contract_rows() -> list[models.OptionContractRow]:
    return [
        models.OptionContractRow(
            option_symbol="TSLA260619C00450000",
            last_price=Decimal("12.1"),
            volume=300,
        ),
        models.OptionContractRow(
            option_symbol="TSLA260619P00450000",
            last_price=Decimal("10.2"),
            volume=200,
        ),
    ]


def _sample_iv_rank_rows() -> list[models.IvRankRow]:
    return [
        models.IvRankRow(date=date(2026, 5, 18), close=Decimal("450")),
        models.IvRankRow(date=date(2026, 5, 19), close=Decimal("455")),
    ]


def _sample_vol_stats_rows() -> list[models.VolStatsRow]:
    return [
        models.VolStatsRow(ticker="TSLA", date=date(2026, 5, 18), iv=Decimal("0.42")),
        models.VolStatsRow(ticker="TSLA", date=date(2026, 5, 19), iv=Decimal("0.43")),
    ]


def _sample_realized_vol_rows() -> list[models.RealizedVolRow]:
    return [
        models.RealizedVolRow(date=date(2026, 5, 18), price=Decimal("450")),
        models.RealizedVolRow(date=date(2026, 5, 19), price=Decimal("455")),
    ]


def _sample_skew_rows() -> list[models.SkewRow]:
    return [
        models.SkewRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            delta=25,
            expiry=date(2026, 6, 19),
            risk_reversal=Decimal("-0.04"),
        ),
        models.SkewRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            delta=25,
            expiry=date(2026, 7, 17),
            risk_reversal=Decimal("-0.05"),
        ),
    ]


def _sample_flow_alerts() -> list[models.FlowAlert]:
    return [
        models.FlowAlert(
            id="flow-1",
            ticker="TSLA",
            created_at=datetime(2026, 5, 18, 14, 30, tzinfo=UTC),
            total_premium=Decimal("100"),
        ),
        models.FlowAlert(
            id="flow-2",
            ticker="TSLA",
            created_at=datetime(2026, 5, 18, 14, 31, tzinfo=UTC),
            total_premium=Decimal("200"),
        ),
    ]


def _assert_single_executemany(repo: _FakeRepository, expected_count: int) -> None:
    assert len(repo.fake_cursor.executemany_calls) == 1
    assert len(repo.fake_cursor.executemany_calls[0][1]) == expected_count
    assert repo.fake_cursor.execute_calls == []


def test_batch_writer_methods_use_one_executemany_call_for_multi_row_inputs():
    cases = [
        lambda repo: repo.insert_iv_term_rows(1, _sample_iv_rows()),
        lambda repo: repo.insert_greek_exposure_rows(1, "TSLA", _sample_exposure_rows()),
        lambda repo: repo.insert_greeks_rows(1, "TSLA", _sample_greeks_rows()),
        lambda repo: repo.insert_option_contract_rows(1, "TSLA", _sample_contract_rows()),
        lambda repo: repo.upsert_iv_rank_rows("TSLA", _sample_iv_rank_rows()),
        lambda repo: repo.upsert_volatility_stats_rows(_sample_vol_stats_rows()),
        lambda repo: repo.upsert_realized_vol_rows("TSLA", _sample_realized_vol_rows()),
        lambda repo: repo.upsert_skew_rows("TSLA", _sample_skew_rows()),
        lambda repo: repo.insert_flow_events(1, "TSLA", _sample_flow_alerts()),
    ]

    for call_method in cases:
        repo = _FakeRepository()
        assert call_method(repo) == 2
        _assert_single_executemany(repo, expected_count=2)


def test_volatility_param_builders_preserve_order_and_values():
    assert _iv_rank_params(
        "TSLA",
        [
            models.IvRankRow(
                date=date(2026, 5, 18),
                close=Decimal("450"),
                volatility=Decimal("0.42"),
                iv_rank_1y=Decimal("69"),
                updated_at=datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
            )
        ],
    ) == [
        (
            "TSLA",
            date(2026, 5, 18),
            Decimal("450"),
            Decimal("0.42"),
            Decimal("69"),
            datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
        )
    ]

    assert _volatility_stats_params(
        [
            models.VolStatsRow(
                ticker="TSLA",
                date=date(2026, 5, 18),
                iv=Decimal("0.42"),
                iv_low=Decimal("0.20"),
                iv_high=Decimal("0.80"),
                iv_rank=Decimal("0.65"),
                rv=Decimal("0.30"),
                rv_low=Decimal("0.15"),
                rv_high=Decimal("0.70"),
            )
        ]
    ) == [
        (
            "TSLA",
            date(2026, 5, 18),
            Decimal("0.42"),
            Decimal("0.20"),
            Decimal("0.80"),
            Decimal("0.65"),
            Decimal("0.30"),
            Decimal("0.15"),
            Decimal("0.70"),
        )
    ]

    assert _realized_vol_params(
        "TSLA",
        [
            models.RealizedVolRow(
                date=date(2026, 5, 18),
                price=Decimal("450"),
                implied_volatility=Decimal("0.42"),
                realized_volatility=Decimal("0.31"),
                unshifted_rv_date=date(2026, 5, 15),
            )
        ],
    ) == [
        (
            "TSLA",
            date(2026, 5, 18),
            Decimal("450"),
            Decimal("0.42"),
            Decimal("0.31"),
            date(2026, 5, 15),
        )
    ]

    assert _skew_params(
        "TSLA",
        [
            models.SkewRow(
                ticker="TSLA",
                date=date(2026, 5, 18),
                delta=25,
                expiry=date(2026, 6, 19),
                risk_reversal=Decimal("-0.04"),
            )
        ],
    ) == [
        ("TSLA", date(2026, 5, 18), 25, date(2026, 6, 19), Decimal("-0.04"))
    ]


def test_flow_event_params_preserve_order_and_derived_values():
    created_at = datetime(2026, 5, 18, 14, 30, tzinfo=UTC)
    rows = [
        models.FlowAlert(
            id="flow-1",
            ticker="TSLA",
            option_chain="TSLA260619C00450000",
            expiry=date(2026, 6, 19),
            strike=Decimal("450"),
            type="call",
            price=Decimal("12.1"),
            underlying_price=Decimal("451.2"),
            total_size=10,
            total_premium=Decimal("12100"),
            total_ask_side_prem=Decimal("9000"),
            total_bid_side_prem=Decimal("3100"),
            volume=100,
            open_interest=1000,
            volume_oi_ratio=Decimal("0.10"),
            has_sweep=True,
            has_floor=False,
            has_multileg=False,
            all_opening_trades=True,
            iv_start=Decimal("0.40"),
            iv_end=Decimal("0.42"),
            alert_rule="RepeatedHits",
            rule_id="rule-1",
            sector="Consumer Cyclical",
            issue_type="Common Stock",
            next_earnings_date=date(2026, 7, 24),
            created_at=created_at,
        )
    ]

    assert _flow_event_params(81, rows) == [
        (
            81,
            "flow-1",
            "TSLA",
            "TSLA260619C00450000",
            date(2026, 6, 19),
            Decimal("450"),
            "call",
            Decimal("12.1"),
            Decimal("451.2"),
            10,
            Decimal("12100"),
            Decimal("9000"),
            Decimal("3100"),
            100,
            1000,
            Decimal("0.10"),
            True,
            False,
            False,
            True,
            Decimal("0.40"),
            Decimal("0.42"),
            "RepeatedHits",
            "directional_whale",
            Decimal("0.74"),
            "rule-1",
            "Consumer Cyclical",
            "Common Stock",
            date(2026, 7, 24),
            created_at,
        )
    ]
