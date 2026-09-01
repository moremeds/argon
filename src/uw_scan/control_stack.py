#!/usr/bin/env python3
"""Stack liveness and process lifecycle for control-argon.

Split from control_argon.py because none of this touches Postgres: port
ownership, process ancestry, and signalling are pure stdlib + lsof/ps, so they
unit-test without a database.

Why this module exists at all. On 2026-09-01 this machine was carrying five
orphaned stacks — 2 to 4 days old, from four different worktrees, two of which
had already been `git worktree remove`d. One of them was `next start` serving a
four-day-old `.next/standalone` build on port 3001, argon's default web port. It
answered 200. Any agent that edited code, started a stack, and curled :3001 was
validating a build from four days earlier and getting a green light for it.
A stale process that errors is a nuisance; one that answers correctly is a trap.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# liveness
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    """One HTTP probe. `detail` carries WHY it failed, never an empty shrug.

    A diagnostic that reports "unreachable" and drops the reason makes the
    operator re-run the request by hand to learn what a tool already knew.
    """

    status: int | None
    body: dict | None
    detail: str

    def __bool__(self) -> bool:
        return self.status == 200


def probe(url: str, timeout: float = 5.0) -> Probe:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        return Probe(exc.code, None, repr(exc))
    except (urllib.error.URLError, OSError) as exc:
        return Probe(None, None, repr(exc))
    try:
        return Probe(status, json.loads(raw), "")
    except ValueError as exc:
        # A 200 that is not JSON is still a reachable page (the web root, say).
        return Probe(status, None, repr(exc))

# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


# Recognised stack roles, longest-specific first. This is an ALLOW-list on
# purpose, and the opposite choice from sync's deny-list, because the costs point
# the other way: a missed orphan is caught on the next run, while one wrongly
# matched process is a killed MCP server or editor. Being in the argon tree is
# not enough to be argon's — uv-installed MCP servers run with the repo as their
# cwd and listen on ports of their own.
ROLE_PATTERNS: tuple[tuple[str, str], ...] = (
    # Supervisors first. `concurrently` is handed every child command as
    # arguments, so its own command line contains all the patterns below it;
    # matched in the other order it would report itself as a WS consumer.
    ("scripts/dev.sh", "dev.sh"),
    ("concurrently", "dev.sh"),
    ("uw_scan.worker.massive_ws_consumer", "ws"),
    ("uw_scan.worker.scheduler", "worker"),
    ("uw_scan.api.server", "api"),
    ("uvicorn", "api"),
    ("next dev", "web(dev)"),
    ("next start", "web(start)"),
    ("next-server", "web"),
)


def role_of(command: str) -> str | None:
    for needle, label in ROLE_PATTERNS:
        if needle in command:
            return label
    return None


@dataclass(frozen=True)
class Proc:
    """A listening process, with the checkout it was started from."""

    pid: int
    ppid: int
    age_seconds: int
    cwd: str
    command: str
    ports: tuple[int, ...]
    role: str

    @property
    def age_human(self) -> str:
        h, m = divmod(self.age_seconds // 60, 60)
        d, h = divmod(h, 24)
        if d:
            return f"{d}d{h:02d}h"
        return f"{h}h{m:02d}m" if h else f"{m}m"


def parse_etime(etime: str) -> int:
    """`[[DD-]HH:]MM:SS` -> seconds. macOS ps has no `etimes` keyword."""
    days = 0
    if "-" in etime:
        d, etime = etime.split("-", 1)
        days = int(d)
    parts = [int(x) for x in etime.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return ((days * 24 + h) * 60 + m) * 60 + s


def _run(cmd: list[str]) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[control-argon] {cmd[0]} failed: {repr(exc)}", file=sys.stderr)
        return ""
    # lsof exits 1 when nothing matches — that is data, not an error.
    return done.stdout


logger = logging.getLogger(__name__)


def _ints(*values: str) -> tuple[int, ...] | None:
    """Parse integer columns out of a ps/lsof row; None when the row is not one.

    One handler instead of four identical `except ValueError: continue` blocks.
    A skipped row is logged rather than swallowed: silently dropping a line here
    means `down` silently misses an orphan, which is the failure this module is
    for.
    """
    try:
        return tuple(int(v) for v in values)
    except ValueError as exc:
        logger.debug("unparsable process column in %r: %s", values, repr(exc))
        return None


def argon_root() -> Path:
    """The main checkout, shared by every worktree (worktrees live under it)."""
    out = _run(
        [
            "git",
            "-C",
            str(Path(__file__).resolve().parent),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ]
    ).strip()
    return Path(out).parent if out else Path(__file__).resolve().parents[2]


def _listen_ports() -> dict[int, set[int]]:
    """pid -> listening TCP ports, from one lsof call."""
    ports: dict[int, set[int]] = {}
    for line in _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"]).splitlines()[1:]:
        fields = line.split()
        if len(fields) < 9:
            continue
        # NAME is column 9, but a LISTEN row appends a `(LISTEN)` state column,
        # so the last field is not the address. Take the last field that looks
        # like one instead of trusting either position.
        name = next((f for f in reversed(fields) if ":" in f), "")
        if not name:
            continue
        parsed = _ints(fields[1], name.rsplit(":", 1)[1])
        if parsed is None:
            continue
        ports.setdefault(parsed[0], set()).add(parsed[1])
    return ports


def _cwds(pids: list[int]) -> dict[int, str]:
    """pid -> cwd. `lsof -F` emits a `p<pid>` line then an `n<path>` line."""
    if not pids:
        return {}
    out = _run(["lsof", "-a", "-d", "cwd", "-Fn", "-p", ",".join(map(str, pids))])
    cwds: dict[int, str] = {}
    current = None
    for line in out.splitlines():
        if line.startswith("p"):
            parsed = _ints(line[1:])
            current = parsed[0] if parsed else None
        elif line.startswith("n") and current is not None:
            cwds[current] = line[1:]
    return cwds


def _ps(pids: list[int]) -> dict[int, tuple[int, int, str]]:
    """pid -> (ppid, age_seconds, command)."""
    if not pids:
        return {}
    out = _run(
        ["ps", "-o", "pid=,ppid=,etime=,command=", "-p", ",".join(map(str, pids))]
    )
    rows: dict[int, tuple[int, int, str]] = {}
    for line in out.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 4:
            continue
        parsed = _ints(fields[0], fields[1])
        if parsed is None:
            continue
        rows[parsed[0]] = (parsed[1], parse_etime(fields[2]), fields[3])
    return rows


def _all_processes() -> dict[int, tuple[int, int, str]]:
    """Every process on the box -> (ppid, age_seconds, command)."""
    out = _run(["ps", "-eo", "pid=,ppid=,etime=,command="])
    rows: dict[int, tuple[int, int, str]] = {}
    for line in out.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 4:
            continue
        parsed = _ints(fields[0], fields[1])
        if parsed is None:
            continue
        rows[parsed[0]] = (parsed[1], parse_etime(fields[2]), fields[3])
    return rows


def argon_procs() -> list[Proc]:
    """Every argon stack process, identified by role and attributed by cwd.

    Enumeration is by ROLE, not by listening port. Only 2 of the stack's 7
    processes bind a TCP socket — the 4 schedulers and the WS consumer do not —
    so a port-driven sweep stops web and API and leaves the workers orphaned,
    manufacturing the very thing it was run to clean up.

    cwd is what attributes a process to a checkout: `next dev` and `uvicorn` are
    identical across worktrees. It keeps reporting the path after the worktree is
    deleted, which is precisely when you most need to know where it came from.
    """
    root = str(argon_root())
    ports = _listen_ports()
    meta = _all_processes()
    candidates = {
        pid: (ppid, age, command, role)
        for pid, (ppid, age, command) in meta.items()
        if (role := role_of(command)) is not None
    }
    cwds = _cwds(list(candidates))
    procs = []
    for pid, (ppid, age, command, role) in candidates.items():
        cwd = cwds.get(pid, "")
        if not cwd.startswith(root):
            continue
        procs.append(
            Proc(pid, ppid, age, cwd, command, tuple(sorted(ports.get(pid, ()))), role)
        )
    return sorted(procs, key=lambda p: -p.age_seconds)


# --------------------------------------------------------------------------
# termination
# --------------------------------------------------------------------------


def _children_of(roots: set[int]) -> set[int]:
    """Transitive descendants, from one `ps -eo pid,ppid` pass."""
    edges: dict[int, list[int]] = {}
    for line in _run(["ps", "-eo", "pid=,ppid="]).splitlines():
        fields = line.split()
        if len(fields) == 2:
            parsed = _ints(fields[0], fields[1])
            if parsed:
                edges.setdefault(parsed[1], []).append(parsed[0])
    seen: set[int] = set()
    stack = list(roots)
    while stack:
        for child in edges.get(stack.pop(), []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _protected() -> set[int]:
    """Us and our ancestors. Never signal the session we are running in."""
    safe = {os.getpid()}
    pid = os.getppid()
    parents = {}
    for line in _run(["ps", "-eo", "pid=,ppid="]).splitlines():
        fields = line.split()
        if len(fields) == 2:
            parsed = _ints(fields[0], fields[1])
            if parsed:
                parents[parsed[0]] = parsed[1]
    while pid and pid not in safe:
        safe.add(pid)
        pid = parents.get(pid, 0)
    return safe


def terminate(pids: set[int], grace: float = 4.0) -> tuple[set[int], set[int]]:
    """SIGTERM the processes and their descendants, then SIGKILL survivors.

    Descendants are killed explicitly rather than by process group. Signalling a
    group we did not create can reach further than intended; the tree rooted at
    a known pid cannot. Killing children matters: `uv run uvicorn` does NOT
    forward SIGTERM, so terminating the wrapper alone leaves uvicorn holding the
    port — measured, not assumed.
    """
    targets = (pids | _children_of(pids)) - _protected()
    if not targets:
        return set(), set()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = {pid for pid in targets if _alive(pid)}
        if not alive:
            break
        for pid in alive:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError) as exc:
                print(f"[control-argon] kill {pid}: {repr(exc)}", file=sys.stderr)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(_alive(p) for p in alive):
            time.sleep(0.2)
    survivors = {pid for pid in targets if _alive(pid)}
    return targets - survivors, survivors


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        # ProcessLookupError: gone. PermissionError: alive, but not ours to
        # signal — reporting it as dead would make `down` claim a success it
        # did not have.
        logger.debug("kill(%d, 0): %s", pid, repr(exc))
        return isinstance(exc, PermissionError)
    return True


if __name__ == "__main__":  # pragma: no cover - manual inspection aid
    for proc in argon_procs():
        print(f"{proc.pid:>7} {proc.role:<10} {proc.age_human:>7} {proc.ports} {proc.cwd}")


# --------------------------------------------------------------------------
# readiness — the single definition of "the stack is up", shared by doctor and up
# --------------------------------------------------------------------------

WORKER_LAG_MAX = 900.0


@dataclass(frozen=True)
class StackState:
    """What is actually serving, as opposed to what is listening.

    The four fields below are one predicate, not four: a 200 from /api/health
    only proves a process holds the socket. Version pins it to THIS checkout,
    and worker lag catches the half-stack — concurrently is not run with
    --kill-others, so a scheduler can die and leave web+API answering happily.
    """

    web: Probe
    api: Probe
    repo_version: str
    running_version: str | None
    worker_lag: float | None
    ws_source: str | None

    @property
    def ready(self) -> bool:
        return not self.blockers()

    def blockers(self) -> list[str]:
        out = []
        if not self.web:
            out.append(f"web down ({self.web.detail or self.web.status})")
        if not self.api:
            out.append(f"api down ({self.api.detail or self.api.status})")
        elif self.running_version != self.repo_version:
            out.append(
                f"api serving {self.running_version}, repo is {self.repo_version}"
            )
        if self.api and self.worker_lag is None:
            out.append("no worker heartbeat")
        elif self.worker_lag is not None and self.worker_lag > WORKER_LAG_MAX:
            out.append(f"worker heartbeat {self.worker_lag / 3600:.1f}h old")
        return out


def read_stack(web_port: int, api_port: int, repo_root: Path) -> StackState:
    web = probe(f"http://127.0.0.1:{web_port}/")
    api = probe(f"http://127.0.0.1:{api_port}/api/health")
    body = api.body or {}
    return StackState(
        web=web,
        api=api,
        repo_version=(repo_root / "VERSION").read_text().strip(),
        running_version=str(body["version"]) if body.get("version") else None,
        worker_lag=body.get("worker_lag_seconds"),
        ws_source=(body.get("ws_consumer") or {}).get("active_source"),
    )


# --------------------------------------------------------------------------
# up / down
# --------------------------------------------------------------------------


def _describe(proc: Proc, repo_root: Path) -> str:
    where = proc.cwd
    if not Path(where.split("/web")[0]).exists():
        where += "  (worktree deleted)"
    elif not where.startswith(str(repo_root)):
        where += "  (other checkout)"
    ports = ",".join(f":{p}" for p in proc.ports) or "-"
    return f"  pid {proc.pid:<7} {proc.role:<10} {ports:<13} {proc.age_human:>7}  {where}"


def cmd_up(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    wanted = {args.web_port, args.api_port}

    holders = [p for p in argon_procs() if wanted & set(p.ports)]
    mine = [p for p in holders if p.cwd.startswith(str(repo_root))]
    foreign = [p for p in holders if p not in mine]

    state = read_stack(args.web_port, args.api_port, repo_root)
    if state.ready and not args.force:
        print(f"[ok  ] already up and current (v{state.repo_version})")
        return 0

    if holders:
        if not args.force:
            print("[FAIL] ports are already held:")
            for proc in holders:
                print(_describe(proc, repo_root))
            print(
                "\n  Something is serving these ports and it is not this checkout's\n"
                "  current code. Re-run with --force to stop them first, or pick\n"
                "  other ports with --web-port / --api-port."
            )
            if foreign:
                print("  --force will stop processes from ANOTHER checkout (listed above).")
            return 1
        print("[..  ] stopping what holds the ports:")
        for proc in holders:
            print(_describe(proc, repo_root))
        killed, survived = terminate({p.pid for p in holders})
        print(f"[ok  ] stopped {len(killed)} process(es)")
        if survived:
            print(f"[FAIL] would not die: {sorted(survived)}")
            return 1

    log_dir = repo_root / "output" / "dev"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.log"
    env = {
        **os.environ,
        "WEB_PORT": str(args.web_port),
        "API_PORT": str(args.api_port),
        "DEV_FULL": "1" if args.full else "0",
    }
    # Detached in its own session: the stack must outlive this command, and the
    # log must go to a file. dev.sh's `concurrently` writes ~26 lines/sec, which
    # is not something to hand back to a caller through a pipe.
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            ["bash", "scripts/dev.sh"],
            cwd=repo_root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    print(f"[..  ] started dev.sh (pid {proc.pid}), log: {log_path}")

    started = time.monotonic()
    deadline = started + args.timeout
    last = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print(f"[FAIL] dev.sh exited with {proc.returncode} — see {log_path}")
            _tail(log_path)
            return 1
        elapsed = time.monotonic() - started
        state = read_stack(args.web_port, args.api_port, repo_root)
        blockers = state.blockers()
        # doctor can only ask "is the heartbeat recent" — it has no start time to
        # compare against. `up` does, so it asks the stronger question: was this
        # heartbeat written AFTER we launched? Without it, the row a worker wrote
        # minutes before the restart passes the 15-minute freshness bar and `up`
        # reports ready while dev.sh is still in its `sleep 20` before any worker
        # exists. Measured: a down/up cycle called ready at 19s with no worker.
        if state.api and (state.worker_lag is None or state.worker_lag >= elapsed):
            blockers = [b for b in blockers if "heartbeat" not in b]
            blockers.append("worker not started yet (heartbeat predates this run)")
        if not blockers:
            print(
                f"[ok  ] stack ready in {elapsed:.0f}s — "
                f"web :{args.web_port}, api :{args.api_port}, v{state.repo_version}"
            )
            return 0
        current = "; ".join(blockers)
        if current != last:
            print(f"[..  ] waiting: {current}")
            last = current
        time.sleep(3)

    print(f"[FAIL] not ready after {args.timeout}s: {'; '.join(blockers)}")
    print(f"       the stack is still running — log: {log_path}")
    _tail(log_path)
    return 1


def _tail(path: Path, lines: int = 15) -> None:
    try:
        tail = path.read_text(errors="replace").splitlines()[-lines:]
    except OSError as exc:
        print(f"       (could not read log: {repr(exc)})")
        return
    for line in tail:
        print(f"       | {line[:160]}")


def cmd_down(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    procs = argon_procs()
    if not args.all:
        procs = [p for p in procs if p.cwd.startswith(str(repo_root))]
    if args.older_than:
        procs = [p for p in procs if p.age_seconds >= args.older_than * 3600]

    if not procs:
        scope = "the argon tree" if args.all else "this checkout"
        print(f"[ok  ] nothing to stop in {scope}")
        return 0

    for proc in procs:
        print(_describe(proc, repo_root))
    if args.dry_run:
        print(f"[ok  ] dry run — {len(procs)} process(es) would be stopped")
        return 0

    killed, survived = terminate({p.pid for p in procs})
    print(f"[ok  ] stopped {len(killed)} process(es)")
    if survived:
        print(f"[FAIL] would not die: {sorted(survived)}")
        return 1
    return 0
