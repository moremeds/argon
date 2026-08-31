from __future__ import annotations

from pathlib import Path

import pytest

from scripts.release.require_ci_success import CiGateError, wait_for_ci_success


SHA = "a" * 40


def _run(
    *,
    sha: str = SHA,
    event: str = "push",
    branch: str = "main",
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: int = 123,
) -> dict:
    return {
        "databaseId": run_id,
        "headSha": sha,
        "event": event,
        "headBranch": branch,
        "status": status,
        "conclusion": conclusion,
        "url": f"https://example.test/runs/{run_id}",
    }


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_exact_sha_main_push_success_passes_immediately():
    clock = _Clock()

    result = wait_for_ci_success(
        lambda: [_run()],
        sha=SHA,
        branch="main",
        timeout_seconds=30,
        poll_seconds=5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result["databaseId"] == 123
    assert clock.sleeps == []


def test_pr_or_wrong_branch_success_does_not_satisfy_main_push_gate():
    clock = _Clock()

    with pytest.raises(CiGateError, match="timed out"):
        wait_for_ci_success(
            lambda: [
                _run(event="pull_request"),
                _run(branch="release/v9.9.9", run_id=124),
            ],
            sha=SHA,
            branch="main",
            timeout_seconds=5,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


def test_wrong_sha_success_does_not_satisfy_gate():
    clock = _Clock()

    with pytest.raises(CiGateError, match="timed out"):
        wait_for_ci_success(
            lambda: [_run(sha="b" * 40)],
            sha=SHA,
            branch="main",
            timeout_seconds=0,
            poll_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


def test_active_exact_run_is_polled_until_success():
    clock = _Clock()
    responses = iter(
        [
            [_run(status="in_progress", conclusion=None)],
            [_run(status="completed", conclusion="success")],
        ]
    )

    result = wait_for_ci_success(
        lambda: next(responses),
        sha=SHA,
        branch="main",
        timeout_seconds=30,
        poll_seconds=3,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result["conclusion"] == "success"
    assert clock.sleeps == [3]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_terminal_non_success_fails_without_waiting(conclusion: str):
    clock = _Clock()

    with pytest.raises(CiGateError, match=conclusion):
        wait_for_ci_success(
            lambda: [_run(conclusion=conclusion)],
            sha=SHA,
            branch="main",
            timeout_seconds=30,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.sleeps == []


def test_missing_run_polls_until_timeout():
    clock = _Clock()

    with pytest.raises(CiGateError, match="no matching main push CI run"):
        wait_for_ci_success(
            lambda: [],
            sha=SHA,
            branch="main",
            timeout_seconds=10,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [5, 5]


def test_malformed_run_payload_fails_loudly():
    clock = _Clock()

    with pytest.raises(CiGateError, match="invalid GitHub Actions payload"):
        wait_for_ci_success(
            lambda: [{"status": "completed"}],
            sha=SHA,
            branch="main",
            timeout_seconds=10,
            poll_seconds=5,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


def test_cut_tag_waits_for_ci_before_creating_tag():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "release" / "cut.sh").read_text()

    gate = "scripts/release/require_ci_success.py"
    assert gate in script
    assert script.index(gate) < script.index('git tag -a "v$version"')
