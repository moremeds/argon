from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from uw_scan.normalize import NormalizationError
from uw_scan.sources.nyfed_sme import SmeSourceBundle, parse_sme_release


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
RETRIEVED_AT = datetime(2026, 7, 9, 15, 0, tzinfo=UTC)
DATA_URL = (
    "https://www.newyorkfed.org/medialibrary/media/markets/survey/2026/"
    "jun-2026-data.xlsx"
)
REPORT_URL = (
    "https://www.newyorkfed.org/medialibrary/media/markets/survey/2026/"
    "jun-2026-sme-results.pdf"
)


def _bundle(*, data_bytes: bytes | None = None) -> SmeSourceBundle:
    return SmeSourceBundle.from_bytes(
        survey_month=date(2026, 6, 1),
        data_url=DATA_URL,
        data_bytes=(
            data_bytes
            if data_bytes is not None
            else (FIXTURES / "nyfed_sme_2026_06.xlsx").read_bytes()
        ),
        report_url=REPORT_URL,
        report_bytes=(FIXTURES / "nyfed_sme_2026_06.pdf").read_bytes(),
        retrieved_at=RETRIEVED_AT,
    )


def test_sme_parses_dealer_policy_path_without_mixing_market_participants() -> None:
    release = parse_sme_release(_bundle(), panel_type="Dealer")

    assert release.survey_release_date == date(2026, 6, 3)
    assert release.response_due_date == date(2026, 6, 8)
    assert release.available_at == RETRIEVED_AT
    assert release.published_at is None
    assert release.panel_type == "Dealer"
    assert release.source_record_id == "nyfed-sme:2026-06:Dealer"

    june = next(
        point
        for point in release.path_points
        if point.horizon_date == date(2026, 6, 17)
    )
    assert june.unit == "percent"
    assert june.respondent_count == 26
    assert june.p25 == Decimal("3.63")
    assert june.median == Decimal("3.63")
    assert june.p75 == Decimal("3.63")
    assert june.source_record_id == (
        "nyfed-sme:2026-06:Sheet1:Dealer:fftr_pathofmodes_20260617"
    )

    july_distribution = next(
        item
        for item in release.probability_distributions
        if item.horizon_date == date(2026, 7, 29)
    )
    assert july_distribution.respondent_count == 26
    assert sum(bucket.probability for bucket in july_distribution.buckets) == Decimal(
        "100"
    )
    modal_bucket = next(
        bucket for bucket in july_distribution.buckets if bucket.label == "3.51 - 3.75%"
    )
    assert modal_bucket.lower_bound == Decimal("3.51")
    assert modal_bucket.upper_bound == Decimal("3.75")
    assert modal_bucket.probability == Decimal("85")


def test_sme_bundle_retains_exact_structured_data_and_human_report_bytes() -> None:
    bundle = _bundle()

    assert bundle.data_artifact.source_record_id == "nyfed-sme:2026-06:xlsx"
    assert bundle.data_artifact.content_hash == (
        "d0cf390537a631ba32990aba2bf0229dd5c92a9a18b7e95fd2c1119eeb5e5ecb"
    )
    assert bundle.data_artifact.content_length == 253_265
    assert bundle.data_artifact.media_type == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert bundle.data_artifact.published_at is None
    assert bundle.data_artifact.available_at == RETRIEVED_AT
    assert bundle.report_artifact.source_record_id == "nyfed-sme:2026-06:pdf"
    assert bundle.report_artifact.content_hash == (
        "48c2846ac5ee6f54611fef925499476e31dab5ea2d4f7b8669b64a6b32a920a6"
    )
    assert bundle.report_artifact.content_length == 305_404


def test_sme_rejects_schema_drift_instead_of_returning_empty_release() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["unexpected", "columns"])
    buffer = BytesIO()
    workbook.save(buffer)

    with pytest.raises(NormalizationError, match="missing required columns"):
        parse_sme_release(_bundle(data_bytes=buffer.getvalue()), panel_type="Dealer")


def test_sme_rejects_probability_totals_outside_rounding_tolerance() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "survey_release_date",
            "survey_due_date",
            "panel_type",
            "spd_question_number",
            "theme",
            "subject_group",
            "subject",
            "question_type",
            "question_mode",
            "question_text",
            "question_tag",
            "value_tag",
            "top_header_value",
            "left_header_value",
            "horizon",
            "horizon_date",
            "bucket_range",
            "bucket_low",
            "bucket_high",
            "aggregation",
            "aggregation_value",
        ]
    )
    common = [
        "2026-06-03",
        "2026-06-08",
        "Dealer",
        2,
        "monetary_policy",
        "fed_funds_target_range",
        "fed_funds_target_range",
        "probability_distribution",
        "levels",
        "question",
        "fftr_probdist_20260729",
        "fftr_probdist_20260729_351to375",
        "3.51 - 3.75%",
        "July 28-29",
        "Jul 28-29",
        "2026-07-29",
        "3.51 - 3.75%",
        0.0351,
        0.0375,
    ]
    sheet.append([*common, "count", 26])
    sheet.append([*common, "avg", 0.85])
    buffer = BytesIO()
    workbook.save(buffer)

    with pytest.raises(NormalizationError, match="probability total"):
        parse_sme_release(_bundle(data_bytes=buffer.getvalue()), panel_type="Dealer")
