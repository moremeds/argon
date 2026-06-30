"""Gap-healer report/evidence artifact (intention #2: leave a readable report).

Pure builders (`build_evidence`, `render_markdown`) plus a thin writer that drops
``<as_of>-gap-report.{md,json}`` under an output dir. The DB (data_gap_runs +
gaps-only data_gap_items) is the durable source; this is the readable view.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from uw_scan.reports.data_gap_healer import (
    REGISTRY,
    CoverageSummary,
    GapItem,
)


def build_evidence(
    *,
    run_id: int | None,
    summaries: list[CoverageSummary],
    items: list[GapItem],
    unregistered: list[str],
    caveat_count: int,
    db_host: str,
    db_name: str,
    schema: str,
    command: str,
    as_of: date,
    budget: dict[str, int] | None = None,
    outcome: dict[str, int] | None = None,
) -> dict:
    by_dataset = {
        s.dataset: {
            "audit_mode": s.audit_mode,
            "expected": s.expected_pairs,
            "covered": s.covered_pairs,
            "missing": s.missing_pairs,
            "gap_days": len(s.gap_dates),
        }
        for s in summaries
    }
    return {
        "command": command,
        "db": {"host": db_host, "name": db_name, "schema": schema},
        "checked_at": as_of.isoformat(),
        "run_id": run_id,
        "registry_count": len(REGISTRY),
        "unregistered_tables": unregistered,
        "unregistered_count": len(unregistered),
        "total_gaps": len(items),
        "caveats": caveat_count,
        "datasets": by_dataset,
        "budget_spent": budget or {},
        "heal_outcome": outcome or {},
    }


def render_markdown(ev: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Data gap report — {ev['checked_at']}")
    lines.append("")
    db = ev["db"]
    lines.append(f"- **DB**: `{db['host']}` / `{db['name']}` / schema `{db['schema']}`")
    lines.append(f"- **Command**: `{ev['command']}`")
    lines.append(f"- **Run**: `{ev['run_id']}`")
    lines.append(
        f"- **Registry**: {ev['registry_count']} datasets, "
        f"{ev['unregistered_count']} unregistered, {ev['caveats']} caveats"
    )
    lines.append(f"- **Total gaps**: {ev['total_gaps']}")
    if ev["heal_outcome"]:
        lines.append(f"- **Heal outcome**: {ev['heal_outcome']}")
    if ev["budget_spent"]:
        lines.append(f"- **Provider spend**: {ev['budget_spent']}")
    if ev["unregistered_tables"]:
        lines.append(f"- **Unregistered**: {', '.join(ev['unregistered_tables'])}")
    lines.append("")
    lines.append("| dataset | mode | missing | gap_days | covered/expected |")
    lines.append("|---|---|---:|---:|---|")
    rows = sorted(ev["datasets"].items(), key=lambda kv: kv[1]["missing"], reverse=True)
    for name, d in rows:
        lines.append(
            f"| {name} | {d['audit_mode']} | {d['missing']} | {d['gap_days']} | "
            f"{d['covered']}/{d['expected']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_evidence(ev: dict, out_dir: Path, as_of: date) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"{as_of.isoformat()}-gap-report"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps(ev, indent=2, default=str))
    md_path.write_text(render_markdown(ev))
    return {"json": str(json_path), "md": str(md_path)}
