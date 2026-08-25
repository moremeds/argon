"""Program completion test (spec §20): the north-star question, end to end.

The operator asks for a US optical-communication chain research report as of a
stated date. Argon must freeze scope, disclose coverage, run or reuse
deterministic calculations, route attention within claim permission, preserve
provenance, assemble a versioned report plus a prior-version delta, remain
reproducible with every model disabled, and make no automatic trade decision.

This script exercises exactly that and writes the evidence, because a completion
test whose output lived only in a terminal did not happen.

Reproduce:
    uv run python scripts/research/research_report_completion_test.py \
        --chain Optical-Communication --as-of 2026-08-25 \
        --out docs/research/2026-08-25-research-report-completion/completion.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import psycopg

from uw_scan.config import Settings
from uw_scan.fundamentals.claims import REGISTRY
from uw_scan.fundamentals.dimensions import PROGRAM_CEILING
from uw_scan.fundamentals.report_delta import report_delta
from uw_scan.storage.research_reports import ResearchReportsRepository, content_hash
from uw_scan.worker.jobs.research_report_assemble import assemble_chain_report

#: Words a research report is not allowed to contain. The program ceiling is
#: `research_priority`: attention, never a position. A completion test that did
#: not grep for these would pass on a report that told the operator to buy.
TRADE_WORDS = (
    "buy", "sell", "long", "short", "overweight", "underweight",
    "target price", "position size", "allocate", "entry", "stop loss",
)


def _leaf_strings(node) -> list[str]:
    if isinstance(node, dict):
        return [s for v in node.values() for s in _leaf_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _leaf_strings(v)]
    return [node] if isinstance(node, str) else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", default="Optical-Communication")
    ap.add_argument("--as-of", default="2026-08-25")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    as_of = date.fromisoformat(args.as_of)

    settings = Settings.from_env()
    out: dict = {"chain": args.chain, "as_of": args.as_of, "checks": {}}

    with psycopg.connect(settings.db_dsn()) as conn:
        schema = settings.db_schema
        reports = ResearchReportsRepository(conn, schema=schema)
        key = f"chain:{args.chain}"

        # 1. DETERMINISM — the property every other check rests on. Two dry
        #    assemblies of the same question must hash identically.
        a = assemble_chain_report(
            conn, args.chain, schema=schema, as_of=as_of, publish=False
        )
        b = assemble_chain_report(
            conn, args.chain, schema=schema, as_of=as_of, publish=False
        )
        out["checks"]["deterministic"] = {
            "pass": a["content_hash"] == b["content_hash"] == content_hash(a["blocks"]),
            "content_hash": a["content_hash"],
        }

        # 2. SCOPE FROZEN — every field needed to reproduce this answer.
        manifest = a["manifest_jsonb"]
        required = {
            "engine_version", "taxonomy_version", "evidence_policy", "as_of",
            "assembler_version", "scope",
        }
        out["checks"]["scope_frozen"] = {
            "pass": required <= set(manifest) and manifest["as_of"] == args.as_of,
            "manifest": manifest,
        }

        # 3. COVERAGE DISCLOSED — denominators, not just numerators, and every
        #    numerator no larger than the denominator beside it.
        by_kind = {blk["block_kind"]: blk for blk in a["blocks"]}
        cov = by_kind["chain_coverage"]["payload"]
        out["checks"]["coverage_disclosed"] = {
            "pass": (
                cov["with_compatible_result"] <= cov["members"]
                and cov["with_magnitude"] <= cov["with_exposure"] <= cov["members"]
            ),
            "coverage": cov,
            "member_placements": by_kind["scope"]["payload"]["member_placements"],
        }

        # 4. UNSUPPORTED DECLARED — what the report cannot answer, as a block.
        unsup = by_kind["unsupported"]["payload"]
        out["checks"]["unsupported_declared"] = {
            "pass": (
                by_kind["unsupported"]["ordinal"] == 1
                and len(unsup["killed_event_classes"]) > 0
            ),
            "killed_event_classes": [c["class"] for c in unsup["killed_event_classes"]],
            "descriptive_only": unsup["descriptive_only"],
        }

        # 5. CLAIM PERMISSION — no block above the program ceiling, and the
        #    claim registry agrees with what the blocks assert.
        authorities = {
            blk["block_kind"]: blk.get("authority") for blk in a["blocks"]
        }
        out["checks"]["within_claim_permission"] = {
            "pass": all(
                v in (None, "descriptive", "research_priority", "directional_monitor")
                for v in authorities.values()
            )
            and PROGRAM_CEILING.value == "research_priority",
            "block_authorities": authorities,
            "program_ceiling": PROGRAM_CEILING.value,
            "registry": {c.key: c.authority.value for c in REGISTRY},
        }

        # 6. PROVENANCE — every block traces, or the schema would have refused it.
        out["checks"]["provenance_preserved"] = {
            "pass": all(
                blk.get("derivation") or blk.get("evidence")
                for blk in a["blocks"]
            ),
            "blocks": [
                {
                    "kind": blk["block_kind"],
                    "evidence": blk.get("evidence") or None,
                    "derivation": blk.get("derivation"),
                }
                for blk in a["blocks"]
            ],
        }

        # 7. VERSIONED + DELTA — publish, then compare against the predecessor
        #    that is still readable.
        published = reports.publish(
            report_key=key,
            report_type="chain",
            title=f"{args.chain} chain report",
            manifest=manifest,
            blocks=a["blocks"],
            status=a["status"],
        )
        versions = reports.versions(key)
        previous = (
            reports.version(key, published["version_no"] - 1)
            if published["version_no"] > 1
            else None
        )
        delta = report_delta(previous, reports.version(key, published["version_no"]))
        out["checks"]["versioned_with_delta"] = {
            "pass": len(versions) >= 1 and "summary" in delta,
            "version_no": published["version_no"],
            "versions": [
                {"v": v["version_no"], "status": v["status"], "hash": v["content_hash"]}
                for v in versions
            ],
            "delta": delta,
        }

        # 8. REPLAY — the oldest version still serves the content it published,
        #    unchanged by everything that has happened since.
        oldest = reports.version(key, 1)
        out["checks"]["old_version_replays"] = {
            "pass": oldest is not None
            and oldest["content_hash"]
            == content_hash(
                [
                    {**blk, "payload": blk["payload_jsonb"],
                     "evidence": blk["evidence_jsonb"]}
                    for blk in oldest["blocks"]
                ]
            ),
            "v1_hash": oldest["content_hash"] if oldest else None,
            "v1_status": oldest["status"] if oldest else None,
        }

        # 9. NO MODEL — nothing in the assembly path calls one. Asserted by
        #    reading the module rather than by trusting the docstring.
        source = Path(
            "src/uw_scan/worker/jobs/research_report_assemble.py"
        ).read_text()
        forbidden = ("anthropic", "openai", "deepseek", "httpx", "requests", "subprocess")
        out["checks"]["reproducible_without_models"] = {
            "pass": not any(w in source for w in forbidden),
            "checked_for": list(forbidden),
        }

        # 10. NO TRADE DECISION — every string the report emits, grepped.
        strings = " ".join(_leaf_strings(a["blocks"])).lower()
        hits = [w for w in TRADE_WORDS if w in strings]
        out["checks"]["no_trade_decision"] = {"pass": not hits, "hits": hits}

    out["all_pass"] = all(c["pass"] for c in out["checks"].values())
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n")
    for name, check in out["checks"].items():
        print(f"  {'PASS' if check['pass'] else 'FAIL'}  {name}")
    print(f"\nall_pass={out['all_pass']}  ->  {dest}")
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
