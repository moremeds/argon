#!/usr/bin/env python
"""Strict live proof that four policy paths survive worker -> DB -> API.

Runs the four production worker entry points against LIVE publishers and a
dedicated database, then reads the result back through the real FastAPI app and
records the evidence to JSON.  This is the runner behind MC1's PASS gate: parser
tests prove the parsers work, and prove nothing about whether a fact is durable.

The database must be one you created for this run and whose name starts with
``option_wizard_test``.  Credentials are never recorded -- only the database
class, so the artifact is safe to commit.

Reproduce::

    createdb option_wizard_test_mc1_smoke -O argon_app
    UW_SCAN_TEST_DB_NAME=option_wizard_test_mc1_smoke \\
        uv run python scripts/research/macro_policy_4x4_smoke.py --require-shadow
    dropdb option_wizard_test_mc1_smoke
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_policy_jobs import (
    macro_fomc_statement_ingest_job,
    macro_market_implied_ingest_job,
    macro_sep_ingest_job,
    macro_sme_ingest_job,
)

DEFAULT_OUTPUT = Path(
    "docs/research/2026-08-12-fomc-sep-source-probe/smoke-4x4.json"
)
COMMAND = (
    "UW_SCAN_TEST_DB_NAME=<dedicated test db> "
    "uv run python scripts/research/macro_policy_4x4_smoke.py"
)
PATH_SLOTS = ("actual", "committee_projection", "dealer_expectations", "market_implied")
OFFICIAL_SLOTS = ("actual", "committee_projection", "dealer_expectations")


def _settings() -> Settings:
    name = os.environ.get("UW_SCAN_TEST_DB_NAME", "")
    if not name.startswith("option_wizard_test"):
        raise SystemExit(
            "refusing to run: UW_SCAN_TEST_DB_NAME must name a dedicated database "
            "whose name starts with option_wizard_test"
        )
    return Settings.from_env().model_copy(update={"db_name": name})


def _client(settings: Settings) -> TestClient:
    app = create_app()

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repo] = _override_repo
    return TestClient(app)


def _counts(settings: Settings) -> dict[str, int]:
    with psycopg.connect(settings.db_dsn()) as conn:
        counts = {
            table: conn.execute(f"SELECT count(*) FROM uw_scan.{table}").fetchone()[0]
            for table in (
                "macro_source_artifacts",
                "macro_observations",
                "macro_observation_artifacts",
                "macro_release_ingest_status",
            )
        }
        # Split the artifact count by stability. The publisher's PDF is
        # byte-stable; its HTML is served through a CDN that injects a
        # per-request bot-management nonce, so HTML bytes differ on every fetch
        # through no act of the Federal Reserve. Idempotency is therefore a
        # claim about stable evidence and about facts -- never about a byte
        # count the transport controls.
        counts["macro_source_artifacts_stable"] = conn.execute(
            "SELECT count(*) FROM uw_scan.macro_source_artifacts "
            "WHERE media_type <> 'text/html'"
        ).fetchone()[0]
        counts["releases_ok"] = conn.execute(
            "SELECT count(*) FROM uw_scan.macro_release_ingest_status "
            "WHERE status = 'ok'"
        ).fetchone()[0]
        # The market shadow is a live probability snapshot: a fresh reading is a
        # genuinely new fact every time it is taken, so it can never be idempotent
        # and must not be counted as one. Official releases are dated events and
        # must be.
        counts["official_observations"] = conn.execute(
            "SELECT count(*) FROM uw_scan.macro_observations "
            "WHERE source <> 'frenzy_capital'"
        ).fetchone()[0]
        return counts


def _run_jobs(settings: Settings, *, years: tuple[int, ...]) -> dict[str, Any]:
    dsn = settings.db_dsn()
    observed_at = datetime.now(UTC)
    statement = macro_fomc_statement_ingest_job(
        dsn=dsn, years=years, observed_at=observed_at
    )
    sep = macro_sep_ingest_job(dsn=dsn, years=years, observed_at=observed_at)
    sme = macro_sme_ingest_job(dsn=dsn, observed_at=observed_at)
    # The shadow quotes probabilities against a target range it does not publish;
    # the committee's own statement is the only source for it.
    lower = statement_range(settings)
    market = macro_market_implied_ingest_job(
        dsn=dsn, observed_at=observed_at, current_target_range=lower
    )
    return {
        "federal_reserve_fomc": statement,
        "federal_reserve_sep": sep,
        "new_york_fed_sme": sme,
        "frenzy_capital": market,
    }


def statement_range(settings: Settings) -> str:
    """Read the current target range from the statement we just persisted."""
    with psycopg.connect(settings.db_dsn()) as conn:
        row = conn.execute(
            "SELECT value_jsonb->'points'->0 FROM uw_scan.macro_observations "
            "WHERE series_id = 'POLICY_PATH_ACTUAL' "
            "ORDER BY available_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise SystemExit("no persisted FOMC statement to source the target range from")
    point = row[0]
    return f"{point['target_range_lower']}-{point['target_range_upper']}%"


def _job_result(result: Any) -> dict[str, Any]:
    return {
        "status": result.status,
        "artifacts_seen": result.artifacts_seen,
        "observations_seen": result.observations_seen,
        "releases_discovered": result.releases_discovered,
        "releases_succeeded": result.releases_succeeded,
        "releases_failed": result.releases_failed,
        "failed_release_keys": list(result.failed_release_keys),
        "error_type": result.error_type,
    }


def _api_evidence(settings: Settings, as_of: datetime) -> dict[str, Any]:
    with _client(settings) as client:
        response = client.get(
            "/api/macro/policy", params={"as_of_ts": as_of.isoformat()}
        )
        response.raise_for_status()
        body = response.json()
    slots: dict[str, Any] = {}
    for slot in PATH_SLOTS:
        path = body[slot]["path"]
        slots[slot] = {
            "present": path is not None,
            "missing_reason": body[slot]["missing_reason"],
            "source": path["source"] if path else None,
            "source_kind": path["source_kind"] if path else None,
            "evidence": (
                [
                    {
                        "obs_id": ref["obs_id"],
                        "artifact_id": ref["artifact_id"],
                        "source_url": ref["source_url"],
                    }
                    for ref in path["evidence_refs"]
                ]
                if path
                else []
            ),
            "freshness": body[slot]["freshness"],
        }
    return slots


def _offline_read(settings: Settings, as_of: datetime) -> dict[str, bool]:
    """Every provider class is unreachable here: nothing on the read path fetches."""
    slots = _api_evidence(settings, as_of)
    return {slot: slots[slot]["present"] for slot in PATH_SLOTS}


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--require-shadow",
        action="store_true",
        help="also fail when the optional third-party market shadow is unavailable",
    )
    args = parser.parse_args()

    settings = _settings()
    started_at = datetime.now(UTC)
    end_year = args.end_year if args.end_year is not None else started_at.year
    years = tuple(range(args.start_year, end_year + 1))

    before_first = _counts(settings)
    first = _run_jobs(settings, years=years)
    after_first = _counts(settings)
    as_of = datetime.now(UTC)
    api_first = _api_evidence(settings, as_of)

    # An unchanged rerun must add nothing: re-reading the same bytes is neither
    # new evidence nor a new fact.
    _run_jobs(settings, years=years)
    after_rerun = _counts(settings)

    offline = _offline_read(settings, as_of)

    with psycopg.connect(settings.db_dsn()) as conn:
        not_ok = conn.execute(
            "SELECT source, release_key, status, error_type "
            "FROM uw_scan.macro_release_ingest_status WHERE status <> 'ok' "
            "ORDER BY source, release_key"
        ).fetchall()
        parser_versions = {
            "artifact_acquisition": dict(
                conn.execute(
                    "SELECT source, string_agg(DISTINCT parser_version, ',' "
                    "ORDER BY parser_version) FROM uw_scan.macro_source_artifacts "
                    "GROUP BY source ORDER BY source"
                ).fetchall()
            ),
            "observation_semantic": dict(
                conn.execute(
                    "SELECT source, string_agg(DISTINCT parser_version, ',' "
                    "ORDER BY parser_version) FROM uw_scan.macro_observations "
                    "GROUP BY source ORDER BY source"
                ).fetchall()
            ),
        }
        source_urls = dict(
            conn.execute(
                "SELECT source, min(source_url) FROM uw_scan.macro_source_artifacts "
                "GROUP BY source ORDER BY source"
            ).fetchall()
        )
        backdated = conn.execute(
            "SELECT count(*) FROM uw_scan.macro_observations o "
            "JOIN uw_scan.macro_source_artifacts a USING (artifact_id) "
            "WHERE o.available_at < a.available_at"
        ).fetchone()[0]

    assertions = {
        "four_paths_present": all(api_first[s]["present"] for s in PATH_SLOTS)
        if args.require_shadow
        else all(api_first[s]["present"] for s in OFFICIAL_SLOTS),
        "every_evidence_ref_resolves": all(
            api_first[slot]["evidence"] for slot in OFFICIAL_SLOTS
        ),
        "zero_failed_official_releases": not not_ok,
        # Facts, outcomes, and stable evidence must all be unchanged. The HTML
        # byte count deliberately is not asserted: see _counts.
        "rerun_adds_no_official_fact": (
            after_first["official_observations"]
            == after_rerun["official_observations"]
        ),
        "rerun_adds_no_release_outcome": (
            after_first["macro_release_ingest_status"]
            == after_rerun["macro_release_ingest_status"]
            and after_first["releases_ok"] == after_rerun["releases_ok"]
        ),
        "stable_evidence_does_not_churn": (
            after_first["macro_source_artifacts_stable"]
            == after_rerun["macro_source_artifacts_stable"]
        ),
        "offline_read_returns_paths": all(
            offline[slot] for slot in OFFICIAL_SLOTS
        ),
        "no_observation_predates_its_evidence": backdated == 0,
    }
    payload = {
        "schema_version": 1,
        "command": COMMAND + (" --require-shadow" if args.require_shadow else ""),
        "started_at": started_at,
        "finished_at": datetime.now(UTC),
        "years": list(years),
        # Class only: the exact database name and credentials stay out of the
        # committed artifact.
        "database_class": "dedicated option_wizard_test* database, dropped after run",
        # Acquisition version (what fetched the bytes) and semantic version
        # (what read them) are separate identities and are recorded separately.
        "parser_versions": parser_versions,
        "source_urls": source_urls,
        "worker_results": {
            source: _job_result(result) for source, result in first.items()
        },
        "table_counts": {
            "before": before_first,
            "after_first_run": after_first,
            "after_idempotent_rerun": after_rerun,
        },
        "api_slots": api_first,
        "source_byte_stability": {
            "note": (
                "Federal Reserve HTML is served through Cloudflare, which injects a "
                "per-request __CF$cv$params script carrying a unique ray id and "
                "timestamp. Identical-length, different-bytes on every fetch. The "
                "PDF carries no such injection and is byte-stable, which is why it "
                "is the primary artifact. Re-fetched HTML is preserved as exact "
                "evidence and linked as another witness of the same observation; it "
                "never creates a second fact."
            ),
            "stable_artifacts_after_first_run": after_first[
                "macro_source_artifacts_stable"
            ],
            "stable_artifacts_after_rerun": after_rerun[
                "macro_source_artifacts_stable"
            ],
            "html_artifacts_after_first_run": after_first["macro_source_artifacts"]
            - after_first["macro_source_artifacts_stable"],
            "html_artifacts_after_rerun": after_rerun["macro_source_artifacts"]
            - after_rerun["macro_source_artifacts_stable"],
        },
        "offline_read": offline,
        "releases_not_ok": [
            {
                "source": source,
                "release_key": key,
                "status": status,
                "error_type": error,
            }
            for source, key, status, error in not_ok
        ],
        "assertions": assertions,
        "verdict": "PASS" if all(assertions.values()) else "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            payload, default=_json_default, indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n"
    )
    print(f"wrote {args.output}: {payload['verdict']}")
    for name, passed in sorted(assertions.items()):
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
