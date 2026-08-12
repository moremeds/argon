#!/usr/bin/env python
"""Probe the free official FOMC, SEP, and NY Fed SME source contracts.

Normal mode discovers the latest 2026 releases from publisher landing pages,
parses them through production adapters, and writes a compact machine-readable
audit.  ``--self-check`` is network-free and verifies both the failure-state
classifier and the pinned official fixture invariants.

Reproduce::

    uv run python scripts/research/fomc_sep_source_probe.py --self-check
    uv run python scripts/research/fomc_sep_source_probe.py
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx

from uw_scan.sources.fed_sep import FedSepProvider, SepSourceBundle, parse_sep_release
from uw_scan.sources.fed_funds_futures_path import (
    FedFundsFuturesPathProvider,
    FedFundsFuturesSourceBundle,
    parse_fed_funds_futures_snapshot,
)
from uw_scan.sources.fomc_statement import (
    FomcStatementBundle,
    FomcStatementProvider,
    parse_fomc_statement,
)
from uw_scan.sources.nyfed_sme import (
    NyFedSmeProvider,
    SmeSourceBundle,
    parse_sme_release,
)

ProbeState = Literal["ok", "http_error", "parse_error", "empty"]
OFFICIAL_SOURCE_KEYS = (
    "federal_reserve_fomc",
    "federal_reserve_sep",
    "new_york_fed_sme",
)
DEFAULT_OUTPUT = Path(
    "docs/research/2026-08-12-fomc-sep-source-probe/probe.json"
)
FIXTURES = Path("tests/fixtures/macro")


def classify_probe_state(
    *,
    http_statuses: list[int],
    parse_error: str | None,
    row_count: int | None,
) -> ProbeState:
    if not http_statuses or any(status != 200 for status in http_statuses):
        return "http_error"
    if parse_error is not None:
        return "parse_error"
    if not row_count:
        return "empty"
    return "ok"


def probe_exit_code(
    payload: dict[str, Any],
    *,
    require_shadow: bool = False,
) -> int:
    required = list(OFFICIAL_SOURCE_KEYS)
    if require_shadow:
        required.append("frenzy_capital")
    sources = payload.get("sources", {})
    return 0 if all(sources.get(key, {}).get("state") == "ok" for key in required) else 1


def probe_live(*, year: int, observed_at: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": observed_at,
        "year": year,
        "sources": {
            "federal_reserve_fomc": _probe_statement(year, observed_at),
            "federal_reserve_sep": _probe_sep(year, observed_at),
            "new_york_fed_sme": _probe_sme(observed_at),
            "frenzy_capital": _probe_market_shadow(observed_at),
        },
        "interpretation": {
            "official_jobs_depend_on_frenzy": False,
            "sep_participant_identity_inferred": False,
            "sme_panel": "Dealer",
            "sme_published_at_policy": (
                "null unless publisher supplies a reliable results timestamp; "
                "available_at is first retrieval"
            ),
            "market_shadow_is_official": False,
            "market_shadow_delay_policy": (
                "unknown because the publisher supplies no timestamp or delay field"
            ),
        },
    }


def _probe_statement(year: int, observed_at: datetime) -> dict[str, Any]:
    try:
        with FomcStatementProvider() as provider:
            bundles = provider.fetch_bundles(
                years=(year,), retrieved_at=observed_at
            )
        bundle = max(bundles, key=lambda item: item.meeting_date)
        release = parse_fomc_statement(bundle)
        output = {
            "http_statuses": [200] * (1 + 2 * len(bundles)),
            "discovered_release_count": len(bundles),
            "selected_meeting_date": release.meeting_date,
            "published_at": release.published_at,
            "action": release.action,
            "vote_split": release.vote_split,
            "target_range_lower_percent": release.target_range_lower,
            "target_range_upper_percent": release.target_range_upper,
            "primary_artifact": _artifact_summary(bundle.primary_artifact),
            "accessible_artifact": _artifact_summary(bundle.accessible_artifact),
            "parse_error": None,
            "row_count": 1,
        }
    except Exception as exc:
        output = _failure(exc)
    output["state"] = classify_probe_state(
        http_statuses=output["http_statuses"],
        parse_error=output.get("parse_error"),
        row_count=output.get("row_count"),
    )
    return output


def _probe_sep(year: int, observed_at: datetime) -> dict[str, Any]:
    try:
        with FedSepProvider() as provider:
            bundles = provider.fetch_bundles(
                years=(year,), retrieved_at=observed_at
            )
        bundle = max(bundles, key=lambda item: item.meeting_date)
        release = parse_sep_release(bundle)
        policy = [
            item
            for item in release.projections
            if item.variable == "federal_funds_rate"
        ]
        output = {
            "http_statuses": [200] * (1 + 2 * len(bundles)),
            "discovered_release_count": len(bundles),
            "selected_meeting_date": release.meeting_date,
            "published_at": release.published_at,
            "projection_row_count": len(release.projections),
            "policy_horizon_count": len(policy),
            "policy_horizons": [
                {
                    "horizon": item.horizon,
                    "published_median_percent": item.median,
                    "participant_total": sum(
                        point.participant_count
                        for point in item.participant_distribution
                    ),
                    "distinct_dot_values": len(item.participant_distribution),
                }
                for item in policy
            ],
            "primary_artifact": _artifact_summary(bundle.primary_artifact),
            "accessible_artifact": _artifact_summary(bundle.accessible_artifact),
            "parse_error": None,
            "row_count": len(policy),
        }
    except Exception as exc:
        output = _failure(exc)
    output["state"] = classify_probe_state(
        http_statuses=output["http_statuses"],
        parse_error=output.get("parse_error"),
        row_count=output.get("row_count"),
    )
    return output


def _probe_sme(observed_at: datetime) -> dict[str, Any]:
    try:
        with NyFedSmeProvider() as provider:
            bundle = provider.fetch_latest_bundle(retrieved_at=observed_at)
        release = parse_sme_release(bundle, panel_type="Dealer")
        output = {
            "http_statuses": [200, 200, 200],
            "selected_survey_month": bundle.survey_month,
            "questionnaire_release_date": release.survey_release_date,
            "response_due_date": release.response_due_date,
            "published_at": release.published_at,
            "available_at": release.available_at,
            "panel_type": release.panel_type,
            "path_point_count": len(release.path_points),
            "probability_distribution_count": len(
                release.probability_distributions
            ),
            "respondent_counts": sorted(
                {point.respondent_count for point in release.path_points}
            ),
            "data_artifact": _artifact_summary(bundle.data_artifact),
            "report_artifact": _artifact_summary(bundle.report_artifact),
            "parse_error": None,
            "row_count": len(release.path_points),
        }
    except Exception as exc:
        output = _failure(exc)
    output["state"] = classify_probe_state(
        http_statuses=output["http_statuses"],
        parse_error=output.get("parse_error"),
        row_count=output.get("row_count"),
    )
    return output


def _probe_market_shadow(observed_at: datetime) -> dict[str, Any]:
    try:
        with FedFundsFuturesPathProvider() as provider:
            bundle = provider.fetch_bundle(retrieved_at=observed_at)
        snapshot = parse_fed_funds_futures_snapshot(
            bundle, current_target_range=None
        )
        output = {
            "http_statuses": [200],
            "publisher_class": "third_party_shadow",
            "published_at": None,
            "available_at": snapshot.available_at,
            "delay_status": snapshot.delay_status,
            "delay_minutes": snapshot.delay_minutes,
            "path_point_count": len(snapshot.points),
            "first_meeting_date": snapshot.points[0].meeting_date,
            "last_meeting_date": snapshot.points[-1].meeting_date,
            "probability_totals_percent": [
                sum((point.probabilities or {}).values(), Decimal(0)) * 100
                for point in snapshot.points
            ],
            "artifact": _artifact_summary(bundle.artifact),
            "parse_error": None,
            "row_count": len(snapshot.points),
        }
    except Exception as exc:
        output = _failure(exc)
    output["state"] = classify_probe_state(
        http_statuses=output["http_statuses"],
        parse_error=output.get("parse_error"),
        row_count=output.get("row_count"),
    )
    return output


def _artifact_summary(artifact: Any) -> dict[str, Any]:
    return {
        "source_record_id": artifact.source_record_id,
        "source_url": artifact.source_url,
        "media_type": artifact.media_type,
        "content_hash": artifact.content_hash,
        "content_length": artifact.content_length,
        "published_at": artifact.published_at,
        "available_at": artifact.available_at,
        "parser_version": artifact.parser_version,
        "cost_class": artifact.cost_class,
    }


def _failure(exc: Exception) -> dict[str, Any]:
    statuses: list[int] = []
    if isinstance(exc, httpx.HTTPStatusError):
        statuses = [exc.response.status_code]
    elif not isinstance(exc, httpx.RequestError):
        # The transport completed; normalization failed after receiving bytes.
        statuses = [200]
    return {
        "http_statuses": statuses,
        "parse_error": f"{type(exc).__module__}.{type(exc).__name__}: {exc}",
        "row_count": None,
    }


def self_check() -> None:
    assert classify_probe_state(
        http_statuses=[500], parse_error=None, row_count=None
    ) == "http_error"
    assert classify_probe_state(
        http_statuses=[200], parse_error="drift", row_count=None
    ) == "parse_error"
    assert classify_probe_state(
        http_statuses=[200], parse_error=None, row_count=0
    ) == "empty"

    observed_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    statement = parse_fomc_statement(
        FomcStatementBundle.from_bytes(
            meeting_date=date(2026, 6, 17),
            accessible_url="https://www.federalreserve.gov/statement.html",
            accessible_bytes=(FIXTURES / "fomc_statement_2026_06.html").read_bytes(),
            pdf_url="https://www.federalreserve.gov/statement.pdf",
            pdf_bytes=(FIXTURES / "fomc_statement_2026_06.pdf").read_bytes(),
            retrieved_at=observed_at,
        )
    )
    sep = parse_sep_release(
        SepSourceBundle.from_bytes(
            meeting_date=date(2026, 6, 17),
            accessible_url="https://www.federalreserve.gov/sep.html",
            accessible_bytes=(FIXTURES / "fed_sep_2026_06.html").read_bytes(),
            pdf_url="https://www.federalreserve.gov/sep.pdf",
            pdf_bytes=(FIXTURES / "fed_sep_2026_06.pdf").read_bytes(),
            retrieved_at=observed_at,
        )
    )
    sme = parse_sme_release(
        SmeSourceBundle.from_bytes(
            survey_month=date(2026, 6, 1),
            data_url="https://www.newyorkfed.org/sme.xlsx",
            data_bytes=(FIXTURES / "nyfed_sme_2026_06.xlsx").read_bytes(),
            report_url="https://www.newyorkfed.org/sme.pdf",
            report_bytes=(FIXTURES / "nyfed_sme_2026_06.pdf").read_bytes(),
            retrieved_at=observed_at,
        ),
        panel_type="Dealer",
    )
    shadow_raw = b"""
    <script>window.__SSR_DATA__ = {
      "meetings": [{
        "meeting_date": "2026-09-16",
        "post_rate": 3.42,
        "probabilities": {
          "cut_25": 0.7, "cut_gt25": 0.1, "hold": 0.2,
          "hike_25": 0.0, "hike_gt25": 0.0
        }
      }]
    };</script>
    """
    shadow = parse_fed_funds_futures_snapshot(
        FedFundsFuturesSourceBundle.from_bytes(
            source_url="https://www.frenzycap.com/fedwatch",
            raw_bytes=shadow_raw,
            retrieved_at=observed_at,
        ),
        current_target_range="3.50-3.75%",
    )
    policy = [
        item for item in sep.projections if item.variable == "federal_funds_rate"
    ]
    assert (statement.action, statement.vote_split) == ("Hold", "12-0")
    assert len(policy) == 4
    assert sum(
        point.participant_count for point in policy[0].participant_distribution
    ) == 18
    assert len(sme.path_points) == 16
    assert sme.path_points[0].horizon_date == date(2026, 6, 17)
    assert sme.path_points[0].respondent_count == 26
    assert {point.respondent_count for point in sme.path_points} == {21, 22, 26}
    assert shadow.delay_status == "unknown"
    assert shadow.delay_minutes is None
    assert sum((shadow.points[0].probabilities or {}).values()) == Decimal("1.0")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument(
        "--require-shadow",
        action="store_true",
        help="also fail when the optional third-party market shadow is unavailable",
    )
    args = parser.parse_args()
    if args.self_check:
        self_check()
        print(
            "self-check ok: http/parse/empty states, 3 official fixtures, "
            "and market-shadow contract"
        )
        return 0

    payload = probe_live(year=args.year, observed_at=datetime.now(UTC))
    encoded = json.dumps(
        payload,
        default=_json_default,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded)
    states = {
        source: result["state"] for source, result in payload["sources"].items()
    }
    print(f"wrote {args.output}: {states}")
    return probe_exit_code(payload, require_shadow=args.require_shadow)


if __name__ == "__main__":
    raise SystemExit(main())
