"""Unit tests for canary backtest CLI guardrails."""

from __future__ import annotations

import sys

import pytest

from scripts import backtest_canary


def test_form_sweep_full_is_mutually_exclusive(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["backtest_canary.py", "--form-sweep", "--form-sweep-full"],
    )
    with pytest.raises(SystemExit) as exc:
        backtest_canary.main()
    assert exc.value.code == 2
    assert "only one of --calibrate" in capsys.readouterr().err
