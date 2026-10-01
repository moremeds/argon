"""sync_sp500_members.py against a throwaway livewire checkout in tmp_path.

The fake preset holds the real vendored tickers, so the happy path runs on
real constituents. The two failure cases mutate that list (a duplicate, and a
truncation to 449).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from uw_scan.sources.sp500_members import sp500_members

_PATH = Path(__file__).resolve().parents[3] / "scripts/research/sync_sp500_members.py"
_spec = importlib.util.spec_from_file_location("sync_sp500_members", _PATH)
sync = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sync
_spec.loader.exec_module(sync)


def _livewire(tmp_path: Path, tickers: list[str]) -> Path:
    root = tmp_path / "livewire"
    (root / "presets").mkdir(parents=True)
    (root / "presets" / "sp500.json").write_text(
        json.dumps({"name": "sp500", "source": "test preset", "tickers": tickers})
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
    )
    return root


def test_sync_writes_the_sorted_list_with_the_commit_hash(tmp_path):
    tickers = list(sp500_members())
    root = _livewire(tmp_path, tickers)
    out = tmp_path / "sp500_members.json"
    assert (
        sync.main(["--livewire", str(root), "--out", str(out), "--as-of", "2026-09-26"])
        == 0
    )
    body = json.loads(out.read_text())
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert body["source"] == f"livewire presets/sp500.json @ {head}"
    assert body["as_of"] == "2026-09-26"
    assert body["tickers"] == sorted(tickers)


def test_a_duplicate_is_refused_and_nothing_is_written(tmp_path):
    tickers = list(sp500_members())
    root = _livewire(tmp_path, tickers + [tickers[0]])
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit):
        sync.main(["--livewire", str(root), "--out", str(out)])
    assert not out.exists()


def test_a_short_list_is_refused_and_nothing_is_written(tmp_path):
    root = _livewire(tmp_path, list(sp500_members())[:449])
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit):
        sync.main(["--livewire", str(root), "--out", str(out)])
    assert not out.exists()
