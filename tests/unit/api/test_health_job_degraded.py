"""/api/health ``job_degraded`` block: pure read-side mapping over the records
the jobs already persist (latest scan_runs rows + macro_source_status)."""

from __future__ import annotations

from datetime import UTC, datetime

from uw_scan.reports.health_blocks import _job_degraded

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)


class _Repo:
    def __init__(self, runs=None, macro=None) -> None:
        self._runs = runs or {}
        self._macro = macro or []

    def latest_scan_run_state(self, ticker):
        return self._runs.get(ticker)

    def list_degraded_macro_sources(self):
        return list(self._macro)


def _run(status: str, aggregates=None) -> dict:
    return {"status": status, "finished_at": NOW, "aggregates": aggregates or {}}


def _macro_row(source: str = "fred", **kw) -> dict:
    row = {
        "source": source,
        "last_attempt_at": NOW,
        "updated_at": NOW,
        "consecutive_failures": 3,
        "error_type": "MacroSeriesFailures",
        "error_message": "1 of 7 series failed; first X: builtins.RuntimeError: 503",
    }
    row.update(kw)
    return row


def test_empty_when_no_records() -> None:
    assert _job_degraded(_Repo()) == []


def test_grg_degraded_run_maps_to_scan_run_entry() -> None:
    out = _job_degraded(_Repo(runs={"GRG": _run("degraded")}))
    assert len(out) == 1
    entry = out[0]
    assert entry.job_name == "regime_grg_scan"
    assert entry.record == "scan_run"
    assert entry.since == NOW
    assert entry.consecutive is None


def test_grg_non_degraded_statuses_produce_no_entry() -> None:
    for status in ("ok", "error", "fail", "failed"):
        assert _job_degraded(_Repo(runs={"GRG": _run(status)})) == []


def test_discovery_partial_enrichment_maps_to_scan_run_entry() -> None:
    run = _run(
        "ok",
        aggregates={"discovery": {"candidates_found": 50, "dp_enriched": 31}},
    )
    out = _job_degraded(_Repo(runs={"_DISCOVER": run}))
    assert len(out) == 1
    entry = out[0]
    assert entry.job_name == "discovery_scan"
    assert entry.record == "scan_run"
    assert entry.detail == "dp 31/50 enriched"


def test_discovery_clean_fail_and_empty_runs_produce_no_entry() -> None:
    # Full enrichment -> clean.
    full = _run(
        "ok", aggregates={"discovery": {"candidates_found": 2, "dp_enriched": 2}}
    )
    # A failed latest run is the streak's job, not this block's.
    failed = _run("fail")
    # Zero candidates -> no units attempted, nothing to degrade.
    empty = _run(
        "ok", aggregates={"discovery": {"candidates_found": 0, "dp_enriched": 0}}
    )
    # Missing meta entirely (older rows) -> nothing derivable, no entry.
    bare = _run("ok")
    for run in (full, failed, empty, bare):
        assert _job_degraded(_Repo(runs={"_DISCOVER": run})) == []


def test_macro_degraded_row_maps_to_macro_source_entry() -> None:
    out = _job_degraded(_Repo(macro=[_macro_row("fred")]))
    assert len(out) == 1
    entry = out[0]
    assert entry.job_name == "fred"
    assert entry.record == "macro_source"
    assert entry.consecutive == 3
    assert entry.since == NOW
    assert entry.detail is not None and entry.detail.startswith("MacroSeriesFailures:")


def test_macro_error_message_truncated_to_200_chars() -> None:
    long_msg = "x" * 400
    out = _job_degraded(_Repo(macro=[_macro_row(error_message=long_msg)]))
    detail = out[0].detail
    assert detail is not None
    assert detail == f"MacroSeriesFailures: {long_msg[:200]}"


def test_macro_entry_without_message_keeps_error_type() -> None:
    out = _job_degraded(_Repo(macro=[_macro_row(error_message=None)]))
    assert out[0].detail == "MacroSeriesFailures"


def test_since_falls_back_to_updated_at() -> None:
    later = datetime(2026, 10, 4, 16, 0, tzinfo=UTC)
    out = _job_degraded(
        _Repo(macro=[_macro_row(last_attempt_at=None, updated_at=later)])
    )
    assert out[0].since == later
