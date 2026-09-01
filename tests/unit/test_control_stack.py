"""Unit tests for control-argon's stack liveness and process attribution.

No database, no network, no processes started: everything here is the parsing
and predicate logic that decides what `up` waits for and what `down` is allowed
to kill. The kill path itself is deliberately not exercised — a test that
signals real pids is not a unit test.
"""

from __future__ import annotations

from pathlib import Path

from uw_scan.control_stack import (
    WORKER_LAG_MAX,
    Probe,
    Proc,
    StackState,
    parse_etime,
    role_of,
)


def _state(**kw) -> StackState:
    base = dict(
        web=Probe(200, None, ""),
        api=Probe(200, {}, ""),
        repo_version="0.13.2",
        running_version="0.13.2",
        worker_lag=3.0,
        ws_source="massive.com_ws",
    )
    base.update(kw)
    return StackState(**base)


class TestParseEtime:
    def test_mm_ss(self) -> None:
        assert parse_etime("07:51") == 7 * 60 + 51

    def test_hh_mm_ss(self) -> None:
        assert parse_etime("07:54:27") == 7 * 3600 + 54 * 60 + 27

    def test_days(self) -> None:
        # The real orphan that held :8400 for three and a half days.
        assert parse_etime("03-14:49:09") == 3 * 86400 + 14 * 3600 + 49 * 60 + 9


class TestRoleOf:
    def test_supervisor_wins_over_its_arguments(self) -> None:
        # concurrently is handed every child command as an argument, so its own
        # command line contains the worker patterns. Ordering must not let it
        # report itself as a WS consumer.
        cmd = (
            "npx --prefix web concurrently -n next,api,massive-ws "
            "uv run python -m uw_scan.worker.massive_ws_consumer"
        )
        assert role_of(cmd) == "dev.sh"

    def test_known_roles(self) -> None:
        assert role_of("uv run python -m uw_scan.worker.scheduler") == "worker"
        assert role_of("uv run uvicorn uw_scan.api.server:app --port 8400") == "api"
        assert role_of("node ./node_modules/.bin/next dev") == "web(dev)"
        assert role_of("npm exec next start -p 3012") == "web(start)"
        assert role_of("next-server (v16.2.6)") == "web"

    def test_unrelated_process_is_not_argon(self) -> None:
        # A uv-installed MCP server runs with the repo as its cwd and listens on
        # a port of its own. cwd alone would sweep it up; the role allow-list is
        # what keeps `down` from killing the user's agent session.
        assert role_of("/Users/x/.cache/uv/archive-v0/8KM/bin/python -m serena") is None
        assert role_of("psql -h 127.0.0.1 -d option_wizard_local") is None


class TestStackState:
    def test_all_green_is_ready(self) -> None:
        assert _state().ready
        assert _state().blockers() == []

    def test_version_mismatch_blocks(self) -> None:
        # The 4-day-old `next start` on :3001 answered 200. Liveness alone is
        # not readiness.
        state = _state(running_version="0.13.0")
        assert not state.ready
        assert "serving 0.13.0" in state.blockers()[0]

    def test_stale_worker_blocks(self) -> None:
        state = _state(worker_lag=WORKER_LAG_MAX + 1)
        assert not state.ready
        assert "heartbeat" in state.blockers()[0]

    def test_missing_worker_heartbeat_blocks(self) -> None:
        state = _state(worker_lag=None)
        assert not state.ready
        assert state.blockers() == ["no worker heartbeat"]

    def test_web_down_names_the_reason(self) -> None:
        # A diagnostic that drops the cause makes the operator re-run the
        # request by hand to learn what the tool already knew.
        state = _state(web=Probe(None, None, "URLError(ConnectionRefusedError(61))"))
        assert "ConnectionRefused" in state.blockers()[0]

    def test_api_down_does_not_also_report_a_version_mismatch(self) -> None:
        # With no API there is no running version; reporting "serving None"
        # would be noise on top of the real failure.
        state = _state(api=Probe(None, None, "refused"), running_version=None)
        assert len(state.blockers()) == 1
        assert "api down" in state.blockers()[0]


class TestProc:
    def test_age_human(self) -> None:
        assert Proc(1, 0, 90, "/x", "c", (), "web").age_human == "1m"
        assert Proc(1, 0, 3 * 3600 + 300, "/x", "c", (), "web").age_human == "3h05m"
        assert (
            Proc(1, 0, 4 * 86400 + 6 * 3600, "/x", "c", (), "web").age_human == "4d06h"
        )

    def test_cwd_attributes_a_process_to_its_checkout(self) -> None:
        worktree = "/Users/x/projects/argon/.worktrees/feat-a/web"
        proc = Proc(1, 0, 60, worktree, "next dev", (3001,), "web(dev)")
        assert not proc.cwd.startswith("/Users/x/projects/argon/.worktrees/feat-b")
        assert Path(proc.cwd).is_absolute()
