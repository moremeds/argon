from __future__ import annotations

from datetime import date


def test_snapshot_ticker_passes_ticker_to_interpolated_iv_insert(monkeypatch) -> None:
    from uw_scan.worker.jobs import cockpit_daily_snapshot as job

    captured: dict[str, object] = {}

    class Repo:
        def upsert_realized_vol_rows(self, ticker, rows):
            return len(rows)

        def upsert_iv_rank_rows(self, ticker, rows):
            return len(rows)

        def insert_iv_term_rows(self, run_id, rows):
            return len(rows)

        def insert_interpolated_iv_rows(self, run_id, ticker, rows):
            captured["interp_args"] = (run_id, ticker, rows)
            return len(rows)

    monkeypatch.setattr(job, "fetch_realized_volatility", lambda *_args: ["rv"])
    monkeypatch.setattr(job, "fetch_iv_rank", lambda *_args: ["ivrank"])
    monkeypatch.setattr(job, "fetch_term_structure", lambda *_args: ["term"])
    monkeypatch.setattr(job, "fetch_interpolated_iv", lambda *_args: ["interp"])
    monkeypatch.setattr(job, "fetch_option_contracts", lambda *_args, **_kwargs: [])

    job._snapshot_ticker(
        repo=Repo(),
        client=object(),
        run_id=123,
        ticker="SPY",
        market_date=date(2026, 5, 15),
        target_dtes=[0, 14, 30, 90],
    )

    assert captured["interp_args"] == (123, "SPY", ["interp"])
