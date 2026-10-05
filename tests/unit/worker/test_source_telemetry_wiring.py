"""Every wired non-UW production path lands request events on the recorder
its wrapper owns.

Modelled on ``test_scheduler.py::test_rates_fred_ingest_helper_uses_unwrapped_key_and_recorder``:
patch the wrapper's ``_external_api_recorder`` to yield a fake recorder, patch
the job to capture its kwargs, fire the supplied hook with a stub event, and
assert the fake recorder received it. ``telemetry_recorder`` paths assert
identity instead -- the provider receives the recorder object itself.

The two ``scheduler.main()``-local wrappers and the five healer adapters are
covered by the same parametrized test.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

import uw_scan.worker.scheduler as scheduler
from uw_scan.config import Settings
from uw_scan.worker.jobs import data_gap_heal_runners
from uw_scan.worker.jobs.data_gap_heal_context import HealContext, RequestBudget


class _Stop(Exception):
    pass


class _FakeRecorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


class _Monday(datetime):
    """_technical_live_scan returns early on weekends; pin a Monday."""

    @classmethod
    def now(cls, tz=None) -> "_Monday":
        return cls(2026, 5, 18, 12, 0, tzinfo=tz)


def _settings() -> Settings:
    settings = Settings(
        api_key="uw",
        worker_role="all",
        fred_api_key=SecretStr("fred-secret"),
        massive_api_key=SecretStr("massive-secret"),
    )
    # Same "all_enabled" profile as the scheduler-jobs golden: every gated job
    # registers, so every wired wrapper is reachable by job id.
    return settings.model_copy(
        update={n: True for n in Settings.model_fields if n.endswith("_enabled")}
    )


def _boot_jobs(monkeypatch) -> dict[str, Any]:
    """Boot ``scheduler.main()`` against a scheduler that records add_job."""
    jobs: dict[str, Any] = {}

    class _Sched:
        def __init__(self, *a, **k) -> None:
            pass

        def add_listener(self, *a, **k) -> None:
            pass

        def add_job(self, func, *a, **k) -> None:
            jobs[k["id"]] = func

        def start(self) -> None:
            raise _Stop

        def shutdown(self, *a, **k) -> None:
            pass

    monkeypatch.setattr(scheduler, "BlockingScheduler", _Sched)
    monkeypatch.setattr(
        scheduler,
        "signal",
        SimpleNamespace(SIGTERM=15, SIGINT=2, signal=lambda *a: None),
    )
    settings = _settings()
    monkeypatch.setattr(
        scheduler.Settings, "from_env", classmethod(lambda *a, **k: settings)
    )
    with pytest.raises(_Stop):
        scheduler.main()
    return jobs


def _patch_recorder(monkeypatch, hook_owner: str, recorder: _FakeRecorder) -> None:
    @contextmanager
    def fake_ctx(_settings):
        yield recorder

    monkeypatch.setattr(f"{hook_owner}._external_api_recorder", fake_ctx)


class _AnyResult:
    """Job result stand-in: wrappers log ``result.<attr>`` after the call."""

    def __getattr__(self, _name: str) -> int:
        return 0


def _capture(captured: dict) -> Any:
    def _fake(*args, **kwargs) -> Any:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _AnyResult()

    return _fake


@dataclass(frozen=True)
class _Case:
    """kind: "wrapper" (booted scheduler), "wrapper_repo" (also stubs
    _repo/_uw_client/weekday), or "adapter" (data_gap_heal_runners._run_*)."""

    kind: str
    job_id: str = ""
    hook_owner: str = ""
    job_attr: str = ""
    kwarg: str = "record_request"
    adapter: str = ""
    adapter_args: tuple = ()


_CASES = [
    # schedule/macro.py wrappers
    _Case(
        "wrapper",
        job_id="regime_fred_ingest",
        hook_owner="uw_scan.worker.schedule.macro",
        job_attr="uw_scan.worker.schedule.macro.regime_fred_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="macro_market_shadow_ingest",
        hook_owner="uw_scan.worker.schedule.macro",
        job_attr="uw_scan.worker.schedule.macro.macro_market_implied_ingest_job",
        kwarg="provider_factory",
    ),
    _Case(
        "wrapper",
        job_id="macro_series_ingest",
        hook_owner="uw_scan.worker.schedule.macro",
        job_attr="uw_scan.worker.schedule.macro.macro_fred_series_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="macro_market_layer_ingest",
        hook_owner="uw_scan.worker.schedule.macro",
        job_attr="uw_scan.worker.schedule.macro.macro_market_layer_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="macro_gold_ingest",
        hook_owner="uw_scan.worker.schedule.macro",
        job_attr="uw_scan.worker.schedule.macro.macro_gold_ingest_job",
        kwarg="telemetry_recorder",
    ),
    # schedule/gold.py wrappers
    _Case(
        "wrapper",
        job_id="gold_fred_ingest",
        hook_owner="uw_scan.worker.schedule.gold",
        job_attr="uw_scan.worker.schedule.gold.gold_fred_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="gold_spot_ingest",
        hook_owner="uw_scan.worker.schedule.gold",
        job_attr="uw_scan.worker.schedule.gold.gold_spot_ingest_job",
        kwarg="telemetry_recorder",
    ),
    _Case(
        "wrapper",
        job_id="gold_gpr_ingest",
        hook_owner="uw_scan.worker.schedule.gold",
        job_attr="uw_scan.worker.schedule.gold.gold_gpr_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="gold_etf_holdings_ingest",
        hook_owner="uw_scan.worker.schedule.gold",
        job_attr="uw_scan.worker.schedule.gold.gold_etf_holdings_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="gold_cftc_cot_ingest",
        hook_owner="uw_scan.worker.schedule.gold",
        job_attr="uw_scan.worker.schedule.gold.gold_cftc_cot_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="gold_lbma_vault_ingest",
        hook_owner="uw_scan.worker.schedule.gold",
        job_attr="uw_scan.worker.schedule.gold.gold_lbma_vault_ingest_job",
    ),
    _Case(
        "wrapper",
        job_id="gold_wgc_cb_ingest",
        hook_owner="uw_scan.worker.schedule.gold",
        job_attr="uw_scan.worker.schedule.gold.gold_wgc_cb_ingest_job",
    ),
    # scheduler.py's two newly-wired wrappers
    _Case(
        "wrapper_repo",
        job_id="macro_release_calendar_capture",
        hook_owner="uw_scan.worker.scheduler",
        job_attr=(
            "uw_scan.worker.jobs.macro_release_calendar.macro_release_calendar_capture"
        ),
    ),
    _Case(
        "wrapper_repo",
        job_id="technical_live_scan",
        hook_owner="uw_scan.worker.scheduler",
        job_attr="uw_scan.worker.jobs.technical_live.technical_live_scan",
        kwarg="telemetry_recorder",
    ),
    # healer adapters (data_gap_heal_runners.py)
    _Case(
        "adapter",
        adapter="_run_macro_fred",
        adapter_args=(30,),
        job_attr="uw_scan.worker.jobs.gold_jobs.gold_fred_ingest_job",
    ),
    _Case(
        "adapter",
        adapter="_run_rates_fred",
        adapter_args=(30,),
        job_attr="uw_scan.worker.jobs.rates_jobs.rates_fred_ingest_job",
    ),
    _Case(
        "adapter",
        adapter="_run_gold_lbma",
        job_attr="uw_scan.worker.jobs.gold_jobs.gold_lbma_vault_ingest_job",
    ),
    _Case(
        "adapter",
        adapter="_run_gold_cot",
        job_attr="uw_scan.worker.jobs.gold_jobs.gold_cftc_cot_ingest_job",
    ),
    _Case(
        "adapter",
        adapter="_run_index_ohlc",
        adapter_args=(30,),
        job_attr="uw_scan.worker.volatility_jobs.daily_spy_ohlc_refresh",
        kwarg="telemetry_recorder",
    ),
]

_IDS = [
    "regime_fred",
    "macro_market_shadow",
    "macro_series",
    "macro_market_layer",
    "macro_gold",
    "gold_fred",
    "gold_spot",
    "gold_gpr",
    "gold_etf_holdings",
    "gold_cot",
    "gold_lbma",
    "gold_wgc_cb",
    "release_calendar",
    "technical_live",
    "adapter_macro_fred",
    "adapter_rates_fred",
    "adapter_gold_lbma",
    "adapter_gold_cot",
    "adapter_index_ohlc",
]


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_wired_path_reaches_recorder(monkeypatch, case: _Case) -> None:
    recorder = _FakeRecorder()
    captured: dict[str, Any] = {}

    if case.kind == "adapter":
        settings = _settings()
        ctx = HealContext(
            repo=SimpleNamespace(),
            gap=None,
            schema="uw_scan",
            today=date(2026, 5, 18),
            budget=RequestBudget(None),
            settings=settings,
            recorder=recorder,
        )
        monkeypatch.setattr(case.job_attr, _capture(captured))
        getattr(data_gap_heal_runners, case.adapter)(ctx, *case.adapter_args)
        kwargs = captured["kwargs"]
    else:
        jobs = _boot_jobs(monkeypatch)
        _patch_recorder(monkeypatch, case.hook_owner, recorder)
        if case.kind == "wrapper_repo":
            monkeypatch.setattr(
                scheduler, "_repo", lambda *a, **k: _yield(SimpleNamespace())
            )
            monkeypatch.setattr(
                scheduler, "_uw_client", lambda *a, **k: _yield(SimpleNamespace())
            )
            monkeypatch.setattr(scheduler, "datetime", _Monday)
        if case.kwarg == "provider_factory":
            monkeypatch.setattr(
                "uw_scan.worker.schedule.macro.FedFundsFuturesPathProvider",
                lambda **kwargs: SimpleNamespace(kwargs=kwargs),
            )
        monkeypatch.setattr(case.job_attr, _capture(captured))
        jobs[case.job_id]()
        kwargs = captured["kwargs"]

    event = {"params": {"stub": True}}
    if case.kwarg == "telemetry_recorder":
        assert kwargs["telemetry_recorder"] is recorder
    else:
        if case.kwarg == "provider_factory":
            provider = kwargs["provider_factory"]()
            hook = provider.kwargs["record_request"]
        else:
            hook = kwargs["record_request"]
        hook("provider", event)
        assert recorder.events == [event]


@contextmanager
def _yield(value):
    yield value
