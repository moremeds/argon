"""Gold warmup CLI wiring."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import SecretStr

from uw_scan.worker import gold_warmup


def test_gold_warmup_uses_full_history_etf_holdings_lookback(monkeypatch) -> None:
    calls: dict[str, object] = {}
    settings = SimpleNamespace(
        api_key=SecretStr("test-uw-key"),
        db_name="option_wizard_test",
        massive_api_key=None,
        massive_base_url="https://api.massive.com",
        wgc_goldhub_cookie=None,
        wgc_etf_flows_workbook_path="/tmp/wgc-workbooks",
        base_url="https://api.unusualwhales.com",
        request_timeout_seconds=30.0,
        db_dsn=lambda: "dbname=option_wizard_test",
    )

    monkeypatch.setattr(gold_warmup.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(gold_warmup, "gold_fred_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_gpr_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_spot_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_comex_vault_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_cftc_cot_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_lbma_vault_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_wgc_cb_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_uw_options_ingest_job", lambda **_kwargs: None)
    monkeypatch.setattr(gold_warmup, "gold_posture_compute_job", lambda **_kwargs: None)

    def _capture_etf_holdings(**kwargs) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(gold_warmup, "gold_etf_holdings_ingest_job", _capture_etf_holdings)

    assert gold_warmup.main() == 0
    assert calls["holdings_lookback_days"] >= 365 * 25

