"""Parameter-sweep runner: run every config, persist every row as it completes.

Standing rule (CLAUDE.md): a sweep's FULL result set persists — every config,
every metric, plus the exact reproduce command. stdout-only is data loss.
Persist-as-you-go: a crash at config 80/100 keeps the first 79 rows.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)


def json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with None. json.dumps(nan) emits
    'NaN', which Postgres jsonb rejects — a zero-dispersion config's nan Sharpe
    must persist as null, not kill the run."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def run_sweep(
    configs: Iterable[dict],
    run_one: Callable[[dict], dict],
    *,
    repo,
    strategy: str,
    reproduce_cmd: str,
    params_grid: dict | None = None,
    git_sha: str | None = None,
    data_start=None,
    data_end=None,
    notes: str | None = None,
) -> dict:
    """run_one(config) -> {'metrics': dict, 'gates': dict | None,
    'n_trades': int | None, ...}. A config that raises is logged, persisted as
    an error row, and the sweep continues. Returns
    {'run_id', 'n_ok', 'n_error', 'results'} — results carries only ok configs
    (each as {'config': ..., **run_one_output}) for in-process ranking."""
    run_id = repo.create_run(
        strategy=strategy,
        reproduce_cmd=reproduce_cmd,
        params_grid=params_grid,
        git_sha=git_sha,
        data_start=data_start,
        data_end=data_end,
        notes=notes,
    )
    n_ok = n_error = 0
    results: list[dict] = []
    for config in configs:
        try:
            out = run_one(config)
        except Exception as exc:
            log.error("sweep config %s failed: %r", config, exc)
            repo.insert_result(
                run_id, config=json_safe(config), status="error", error=repr(exc)
            )
            n_error += 1
            continue
        repo.insert_result(
            run_id,
            config=json_safe(config),
            metrics=json_safe(out.get("metrics")),
            gates=json_safe(out.get("gates")),
            n_trades=out.get("n_trades"),
        )
        n_ok += 1
        results.append({"config": config, **out})
    repo.complete_run(
        run_id,
        status="completed" if n_ok else "error",
        error=None if n_ok else "all configs failed",
    )
    return {"run_id": run_id, "n_ok": n_ok, "n_error": n_error, "results": results}
