"""Orchestrator unit test — uses an in-memory fake SignalsRepository
and a small stub Repository to verify the detector wiring without
hitting Postgres. Integration coverage of the wiring happens in
Milestone 6."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.scanner.pipeline import run_detectors


TODAY = date(2026, 5, 17)


# Match the project's integration-conftest pattern: Settings.from_env
# raises if UW_SCAN_API_KEY is missing, so seed a dummy value before
# constructing. The dummy is never used because the orchestrator
# never makes outbound HTTP calls.
os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-unused")


class FakeRepo:
    def __init__(self, **kwargs):
        self._flow_alerts = kwargs.get("flow_alerts", [])
        self._iv_rank = kwargs.get("iv_rank")
        self._strike_gex_curve = kwargs.get("strike_gex_curve", [])
        self._spot = kwargs.get("spot")
        self._posture = kwargs.get("posture")
        self._total_volume = kwargs.get("total_volume", 5000)

    def fetch_flow_events_for_run(self, run_id, ticker):
        return list(self._flow_alerts)

    def fetch_latest_iv_rank(self, ticker):
        return self._iv_rank

    def fetch_strike_gex_curve(self, run_id):
        return list(self._strike_gex_curve)

    def fetch_spot_for_ticker(self, ticker):
        return self._spot

    def fetch_gold_posture_latest(self):
        return self._posture

    def fetch_total_option_volume_for_run(self, run_id, ticker):
        return self._total_volume


class FakeSignalsRepo:
    def __init__(self):
        self.hits, self.flags, self.gates = [], [], []
        self.dp_window = []

    def upsert_signal_hit(self, **kw):
        self.hits.append(kw)

    def upsert_context_flag(self, **kw):
        self.flags.append(kw)

    def upsert_gate(self, **kw):
        self.gates.append(kw)

    def fetch_dark_pool_window(self, ticker, *, lookback_days):
        return list(self.dp_window)


def _settings() -> Settings:
    return Settings.from_env()


def _qualifying_dcf_alert() -> FlowAlert:
    return FlowAlert(
        id="x",
        ticker="AAPL",
        type="call",
        strike=Decimal("100"),
        underlying_price=Decimal("100"),
        total_premium=Decimal("800000"),
        total_ask_side_prem=Decimal("700000"),
        total_bid_side_prem=Decimal("100000"),
        volume=2000,
        open_interest=1000,
        has_multileg=False,
        expiry=TODAY + timedelta(days=30),
        next_earnings_date=TODAY + timedelta(days=60),
    )


def test_regime_block_writes_gate_and_returns_none():
    repo = FakeRepo(
        posture={"structural_posture_chip": "SUSPENDED"},
        flow_alerts=[_qualifying_dcf_alert()],
    )
    sigs = FakeSignalsRepo()
    out = run_detectors(
        repo=repo,
        signals_repo=sigs,
        settings=_settings(),
        run_id=1,
        ticker="AAPL",
        today=TODAY,
    )
    assert out is None
    assert len(sigs.gates) == 1
    assert sigs.gates[0]["regime"] == "block"
    # No hits emitted when regime blocks.
    assert sigs.hits == []
    assert sigs.flags == []


def test_dcf_only_run_emits_hit_and_gate():
    repo = FakeRepo(
        posture={"structural_posture_chip": "NEUTRAL"},
        flow_alerts=[_qualifying_dcf_alert()],
        iv_rank=Decimal("40"),
        spot=Decimal("100"),
    )
    sigs = FakeSignalsRepo()
    out = run_detectors(
        repo=repo,
        signals_repo=sigs,
        settings=_settings(),
        run_id=1,
        ticker="AAPL",
        today=TODAY,
    )
    assert out is not None
    assert out.ticker == "AAPL"
    assert out.is_type_f is False
    assert any(h["signal_type"] == "deep_conviction_flow" for h in sigs.hits)
    assert len(sigs.gates) == 1
    assert sigs.gates[0]["regime"] == "pass"


def test_dp_only_run_emits_no_candidate_but_writes_hit_and_gate():
    # DP fires but DCF does not -> no candidate returned, but the DP hit
    # is still persisted (the read query is responsible for filtering).
    repo = FakeRepo(
        posture={"structural_posture_chip": "NEUTRAL"},
        flow_alerts=[],
    )
    sigs = FakeSignalsRepo()
    sigs.dp_window = [
        {
            "executed_at": datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc),
            "tracking_id": i,
            "price": Decimal("100.0"),
            "premium": Decimal("1500000"),
        }
        for i in range(3)
    ]
    out = run_detectors(
        repo=repo,
        signals_repo=sigs,
        settings=_settings(),
        run_id=1,
        ticker="AAPL",
        today=TODAY,
    )
    assert out is None
    assert any(h["signal_type"] == "dark_pool_accumulation" for h in sigs.hits)
    assert len(sigs.gates) == 1


def test_failing_gold_posture_fetch_does_not_crash_orchestrator(monkeypatch):
    class BrokenRepo(FakeRepo):
        def fetch_gold_posture_latest(self):
            raise RuntimeError("DB hiccup")

    repo = BrokenRepo(flow_alerts=[_qualifying_dcf_alert()], spot=Decimal("100"))
    sigs = FakeSignalsRepo()
    # Fail-open: orchestrator must catch and treat as NEUTRAL.
    out = run_detectors(
        repo=repo,
        signals_repo=sigs,
        settings=_settings(),
        run_id=1,
        ticker="AAPL",
        today=TODAY,
    )
    assert out is not None
    assert sigs.gates[0]["regime"] == "pass"
