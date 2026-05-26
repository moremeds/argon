"""Argparse-level tests for the new --research-proxy / --composite-method flags.

Full end-to-end backtest invocation is exercised in Task 15 (the actual run
against a real DB). Here we exercise only the flag-parse surface, which is
runnable without a DB connection because argparse rejects invalid combos
BEFORE the script's body executes."""

from __future__ import annotations

import subprocess


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "python", "scripts/backtest_vcg.py", *args],
        capture_output=True,
        text=True,
    )


def test_proxy_and_composite_are_mutually_exclusive() -> None:
    r = _run(["--proxy", "HYG", "--composite-method", "risk_parity_3"])
    assert r.returncode != 0
    combined = (r.stderr + r.stdout).lower()
    assert (
        "not allowed" in combined
        or "mutually exclusive" in combined
        or "argument --composite-method" in combined
    )


def test_proxy_and_research_proxy_are_mutually_exclusive() -> None:
    r = _run(["--proxy", "HYG", "--research-proxy", "HYG"])
    assert r.returncode != 0


def test_research_proxy_choices_validated() -> None:
    # argparse exits 2 on invalid --choices BEFORE the script body runs.
    r = _run(["--research-proxy", "BADTICKER"])
    assert r.returncode != 0
    assert "invalid choice" in (r.stderr + r.stdout).lower()


def test_composite_method_choices_validated() -> None:
    r = _run(["--composite-method", "not_a_method"])
    assert r.returncode != 0
    assert "invalid choice" in (r.stderr + r.stdout).lower()
