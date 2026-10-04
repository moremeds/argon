"""Golden of every job each worker process registers (Phase 6a baseline).

Phase 6a moves scheduler.py's job wiring into per-family modules, one family per
PR. Each of those PRs must leave this golden byte-identical: same job ids, same
functions, same triggers, same add_job options, on every process of the fleet.

Boots the REAL ``scheduler.main()`` with a recording BlockingScheduler that stops
at ``start()``. Hermetic: the environment is cleared and settings load from an
empty env file, so a developer's ``.env`` / shell cannot change the result.

Two profiles per process:
- ``defaults``: the code defaults, as a fresh deploy would boot.
- ``all_enabled``: every ``*_enabled`` flag on and every optional key set, so
  feature-gated jobs are covered too.

Regenerate ONLY on purpose: ``UPDATE_SCHEDULER_GOLDEN=1 uv run pytest <this file>``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from pydantic import SecretStr

import uw_scan.worker.scheduler as scheduler
from uw_scan.config import Settings

GOLDEN = Path(__file__).parent / "fixtures" / "scheduler_jobs_golden.json"

#: Every process shape: the prod fleet (/opt/argon/compose.yml) plus the other
#: legal roles, which dev and the legacy single-scheduler shape use.
FLEET = [
    ("uw", 0, 2),
    ("uw", 1, 2),
    ("massive", 0, 2),
    ("massive", 1, 2),
    ("ai-deepseek", 0, 2),
    ("ai-deepseek", 1, 2),
    ("ai", 0, 2),
    ("ai", 1, 2),
    ("all", 0, 1),
]
PROFILES = ("defaults", "all_enabled")
_NO_BOOT = {"r2_access_key_id", "r2_secret_access_key"}  # retired; boot refuses them


class _Stop(Exception):
    pass


def _norm(value: object) -> str:
    return re.sub(r" at 0x[0-9a-f]+", "", repr(value))


def _trigger(trigger: object) -> str:
    """``str()`` of an APScheduler trigger has no start_date (the repr embeds "now").
    Cron triggers add their timezone: the scheduler always passes rth_tz, and a
    host-local cron would be a bug worth seeing. Interval triggers default to the
    host zone, so it is left out (it would differ between a laptop and CI)."""
    text = str(trigger)
    if type(trigger).__name__ == "CronTrigger":
        text += f" tz={trigger.timezone}"
    return text


def _settings(profile: str, tmp_path: Path) -> Settings:
    empty = tmp_path / "empty.env"
    empty.write_text("")
    settings = Settings.from_env(env_path=empty)
    if profile == "all_enabled":
        update: dict[str, object] = {
            name: True for name in Settings.model_fields if name.endswith("_enabled")
        }
        for name, field in Settings.model_fields.items():
            if "SecretStr" in str(field.annotation) and name not in _NO_BOOT:
                if getattr(settings, name) is None:
                    update[name] = SecretStr("x")
        settings = settings.model_copy(update=update)
    return settings


def _dump(monkeypatch, tmp_path: Path, profile: str, role: str, index: int, count: int):
    for key in list(os.environ):
        monkeypatch.delenv(key, raising=False)
    env = {
        "UW_SCAN_API_KEY": "x",
        "UW_SCAN_DB_HOST": "127.0.0.1",
        "UW_SCAN_DB_NAME": "option_wizard_local",
        "UW_SCAN_WORKER_ROLE": role,
        "UW_SCAN_WORKER_INDEX": str(index),
        "UW_SCAN_WORKER_COUNT": str(count),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = _settings(profile, tmp_path)
    jobs: list[dict] = []

    class _Recorder:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *args, **kwargs) -> None:
            func = args[0] if args else kwargs.pop("func")
            trigger = args[1] if len(args) > 1 else kwargs.pop("trigger", None)
            jobs.append(
                {
                    "id": kwargs.pop("id", None),
                    # __name__, not __qualname__: a family move turns
                    # main.<locals>._ohlc_pull into <module>._ohlc_pull, which
                    # must not count as a change; the wrapper's name must.
                    "func": getattr(func, "__name__", _norm(func)),
                    "trigger": _trigger(trigger),
                    "options": {k: _norm(v) for k, v in sorted(kwargs.items())},
                }
            )

        def start(self) -> None:
            raise _Stop

        def shutdown(self, *_a, **_k) -> None:
            pass

    class _Signal:
        SIGTERM = 15
        SIGINT = 2

        def signal(self, *_a, **_k) -> None:
            return None

    monkeypatch.setattr(scheduler, "BlockingScheduler", _Recorder)
    monkeypatch.setattr(scheduler, "signal", _Signal())
    monkeypatch.setattr(scheduler.Settings, "from_env", lambda *_a, **_k: settings)
    with pytest.raises(_Stop):
        scheduler.main()
    return sorted(jobs, key=lambda j: (j["id"] or "", j["func"]))


def _capture(monkeypatch, tmp_path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for profile in PROFILES:
        for role, index, count in FLEET:
            with monkeypatch.context() as m:
                out[f"{profile}/{role}-{index}"] = _dump(
                    m, tmp_path, profile, role, index, count
                )
    return out


def test_scheduler_jobs_match_golden(monkeypatch, tmp_path):
    current = _capture(monkeypatch, tmp_path)
    if os.environ.get("UPDATE_SCHEDULER_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n")
    golden = json.loads(GOLDEN.read_text())
    assert sorted(current) == sorted(golden)
    for process in sorted(golden):
        assert current[process] == golden[process], process
