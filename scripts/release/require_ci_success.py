#!/usr/bin/env python3
"""Require a successful exact-SHA main-push CI run before release.

The helper is stdlib-only so release.yml can run it before dependency setup. It
delegates GitHub authentication and API transport to the already-authenticated
``gh`` CLI, both locally and on GitHub-hosted runners.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any


class CiGateError(RuntimeError):
    """The required CI proof is absent, unsuccessful, or malformed."""


_REQUIRED_KEYS = {
    "databaseId",
    "headSha",
    "event",
    "headBranch",
    "status",
    "conclusion",
    "url",
}
_ACTIVE_STATUSES = {"queued", "in_progress", "pending", "requested", "waiting"}


def _validate_runs(runs: Any) -> list[dict[str, Any]]:
    if not isinstance(runs, list):
        raise CiGateError("invalid GitHub Actions payload: expected a JSON list")
    validated: list[dict[str, Any]] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or not _REQUIRED_KEYS.issubset(run):
            raise CiGateError(
                f"invalid GitHub Actions payload at run[{index}]: "
                f"required keys={sorted(_REQUIRED_KEYS)}"
            )
        validated.append(run)
    return validated


def _matching_runs(
    runs: Sequence[dict[str, Any]], *, sha: str, branch: str
) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if run["headSha"] == sha
        and run["event"] == "push"
        and run["headBranch"] == branch
    ]


def wait_for_ci_success(
    fetch_runs: Callable[[], Any],
    *,
    sha: str,
    branch: str,
    timeout_seconds: float,
    poll_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Wait for an exact-SHA successful ``push`` CI run on ``branch``."""
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be >= 0")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be > 0")

    deadline = monotonic() + timeout_seconds
    last_state = "no matching main push CI run"
    while True:
        runs = _validate_runs(fetch_runs())
        matching = _matching_runs(runs, sha=sha, branch=branch)

        successful = [run for run in matching if run["conclusion"] == "success"]
        if successful:
            return max(successful, key=lambda run: int(run["databaseId"]))

        active = [run for run in matching if run["status"] in _ACTIVE_STATUSES]
        if active:
            observed = max(active, key=lambda run: int(run["databaseId"]))
            last_state = (
                f"run {observed['databaseId']} is {observed['status']} "
                f"({observed['url']})"
            )
        elif matching:
            observed = max(matching, key=lambda run: int(run["databaseId"]))
            conclusion = observed["conclusion"] or observed["status"]
            raise CiGateError(
                f"exact-SHA main push CI run {observed['databaseId']} ended "
                f"with {conclusion}: {observed['url']}"
            )

        if monotonic() >= deadline:
            raise CiGateError(
                f"timed out waiting for exact-SHA main push CI success for {sha}: "
                f"{last_state}"
            )
        sleep(min(poll_seconds, max(0.0, deadline - monotonic())))


def fetch_gh_runs(*, repo: str, workflow: str, sha: str) -> list[dict[str, Any]]:
    command = [
        "gh",
        "run",
        "list",
        "--repo",
        repo,
        "--workflow",
        workflow,
        "--commit",
        sha,
        "--event",
        "push",
        "--limit",
        "20",
        "--json",
        "databaseId,headSha,event,headBranch,status,conclusion,url",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        detail = stderr.strip() or str(exc)
        raise CiGateError(f"failed to query GitHub Actions with gh: {detail}") from exc
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CiGateError(f"gh returned invalid JSON: {exc}") from exc
    return _validate_runs(payload)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository, owner/name")
    parser.add_argument("--sha", required=True, help="exact commit SHA to require")
    parser.add_argument("--workflow", default="ci.yml")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--poll-seconds", type=float, default=5)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run = wait_for_ci_success(
            lambda: fetch_gh_runs(
                repo=args.repo,
                workflow=args.workflow,
                sha=args.sha,
            ),
            sha=args.sha,
            branch=args.branch,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (CiGateError, ValueError) as exc:
        print(f"CI gate failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"CI gate OK: exact SHA {args.sha} passed run "
        f"{run['databaseId']} ({run['url']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
