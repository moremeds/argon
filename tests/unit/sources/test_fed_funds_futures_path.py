from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from uw_scan.normalize import NormalizationError
from uw_scan.sources.fed_funds_futures_path import (
    FedFundsFuturesPathProvider,
    FedFundsFuturesSourceBundle,
    parse_fed_funds_futures_snapshot,
)


FED_WATCH_HTML = """
<script>window.__SSR_DATA__ = {"current_effr": 3.67, "current_rate": 3.75, "meetings": [{"change_bps": -11.54, "contract": "/ZQM26", "implied_avg_effr": 3.62, "meeting_date": "2026-06-17", "post_rate": 3.5546, "pre_rate": 3.67, "probabilities": {"cut_25": 0.4615, "cut_gt25": 0.0, "hike_25": 0.0, "hike_gt25": 0.0, "hold": 0.5385}}, {"change_bps": 11.54, "contract": "/ZQN26", "implied_avg_effr": 3.635, "meeting_date": "2026-07-29", "post_rate": 3.67, "pre_rate": 3.5546, "probabilities": {"cut_25": 0.0, "cut_gt25": 0.0, "hike_25": 0.4615, "hike_gt25": 0.0, "hold": 0.5385}}], "next_meeting": "2026-06-17"};</script>
"""


def test_fed_funds_futures_path_provider_parses_move_probability_rows() -> None:
    response = httpx.Response(
        200,
        text=FED_WATCH_HTML,
        request=httpx.Request("GET", "https://www.frenzycap.com/fedwatch"),
    )

    with patch.object(FedFundsFuturesPathProvider, "_get", return_value=response):
        with FedFundsFuturesPathProvider() as provider:
            rows = provider.fetch_latest_path(current_target_range="3.50-3.75%")

    assert len(rows) == 2
    assert rows[0].meeting_date == date(2026, 6, 17)
    assert rows[0].label == "6/17"
    assert rows[0].probability == 53.9
    assert rows[0].stance == "HOLD"
    assert rows[0].target_range == "3.50-3.75%"
    assert rows[0].source == "Frenzy Capital Fed Watch"

    assert rows[1].meeting_date == date(2026, 7, 29)
    assert rows[1].probability == 53.9
    assert rows[1].stance == "HOLD"
    assert rows[1].target_range == "3.50-3.75%"


def test_fedwatch_snapshot_retains_exact_html_and_full_distribution() -> None:
    retrieved_at = datetime(2026, 6, 1, 12, tzinfo=UTC)
    bundle = FedFundsFuturesSourceBundle.from_bytes(
        source_url="https://www.frenzycap.com/fedwatch",
        raw_bytes=FED_WATCH_HTML.encode(),
        retrieved_at=retrieved_at,
    )
    snapshot = parse_fed_funds_futures_snapshot(
        bundle, current_target_range="3.50-3.75%"
    )

    assert bundle.artifact.source == "frenzy_capital"
    assert bundle.artifact.source_kind == "third_party_shadow"
    assert bundle.artifact.cost_class == "free_third_party_shadow"
    assert bundle.artifact.published_at is None
    assert bundle.artifact.available_at == retrieved_at
    assert bundle.artifact.raw_bytes == FED_WATCH_HTML.encode()
    assert snapshot.delay_status == "unknown"
    assert snapshot.delay_minutes is None
    assert snapshot.points[0].implied_rate == Decimal("3.5546")
    assert snapshot.points[0].probabilities == {
        "Cut 25 bp": Decimal("0.4615"),
        "Cut 50 bp": Decimal("0.0"),
        "Hike 25 bp": Decimal("0.0"),
        "Hike 50 bp": Decimal("0.0"),
        "Hold": Decimal("0.5385"),
    }


def test_fedwatch_artifact_identity_ignores_request_varying_cloudflare_bytes() -> None:
    retrieved_at = datetime(2026, 8, 29, 15, tzinfo=UTC)
    first = FedFundsFuturesSourceBundle.from_bytes(
        source_url="https://www.frenzycap.com/fedwatch",
        raw_bytes=FED_WATCH_HTML.encode() + b"<!-- cloudflare-ray:a -->",
        retrieved_at=retrieved_at,
    )
    second = FedFundsFuturesSourceBundle.from_bytes(
        source_url="https://www.frenzycap.com/fedwatch",
        raw_bytes=FED_WATCH_HTML.encode() + b"<!-- cloudflare-ray:b -->",
        retrieved_at=retrieved_at,
    )

    assert first.artifact.content_hash != second.artifact.content_hash
    assert first.artifact.source_record_id == second.artifact.source_record_id
    assert first.artifact.source_record_id == "frenzy-fedwatch"


def test_fed_funds_futures_path_provider_rejects_empty_parse() -> None:
    response = httpx.Response(
        200,
        text="<html><body>shape changed</body></html>",
        request=httpx.Request("GET", "https://www.frenzycap.com/fedwatch"),
    )

    with (
        patch.object(FedFundsFuturesPathProvider, "_get", return_value=response),
        FedFundsFuturesPathProvider() as provider,
        pytest.raises(NormalizationError, match="meeting rows"),
    ):
        provider.fetch_latest_path(current_target_range="3.50-3.75%")


@pytest.mark.parametrize(
    "probabilities, match",
    [
        (
            '{"cut_25": 0.8, "hold": 0.2}',
            "probability keys",
        ),
        (
            '{"cut_25": 1.1, "cut_gt25": 0, "hold": -0.1, '
            '"hike_25": 0, "hike_gt25": 0}',
            "between 0 and 1",
        ),
        (
            '{"cut_25": 0.8, "cut_gt25": 0, "hold": 0.2, '
            '"hike_25": 0, "hike_gt25": 0, "surprise": 0}',
            "probability keys",
        ),
    ],
)
def test_fedwatch_snapshot_rejects_incomplete_or_invalid_distribution(
    probabilities: str,
    match: str,
) -> None:
    html = (
        '<script>window.__SSR_DATA__ = {"meetings": [{'
        '"meeting_date": "2026-09-16", "post_rate": 3.42, '
        f'"probabilities": {probabilities}'
        '}]};</script>'
    )
    bundle = FedFundsFuturesSourceBundle.from_bytes(
        source_url="https://www.frenzycap.com/fedwatch",
        raw_bytes=html.encode(),
        retrieved_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    with pytest.raises(NormalizationError, match=match):
        parse_fed_funds_futures_snapshot(
            bundle, current_target_range="3.50-3.75%"
        )


def test_fedwatch_snapshot_rejects_nonfinite_implied_rate() -> None:
    html = b"""
    <script>window.__SSR_DATA__ = {"meetings": [{
      "meeting_date": "2026-09-16", "post_rate": "NaN",
      "probabilities": {
        "cut_25": 0.8, "cut_gt25": 0, "hold": 0.2,
        "hike_25": 0, "hike_gt25": 0
      }
    }]};</script>
    """
    bundle = FedFundsFuturesSourceBundle.from_bytes(
        source_url="https://www.frenzycap.com/fedwatch",
        raw_bytes=html,
        retrieved_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    with pytest.raises(NormalizationError, match="implied rate must be finite"):
        parse_fed_funds_futures_snapshot(bundle, current_target_range=None)


def test_fedwatch_snapshot_does_not_silently_drop_one_malformed_meeting() -> None:
    html = b"""
    <script>window.__SSR_DATA__ = {"meetings": [
      {
        "meeting_date": "2026-09-16", "post_rate": 3.42,
        "probabilities": {
          "cut_25": 0.8, "cut_gt25": 0, "hold": 0.2,
          "hike_25": 0, "hike_gt25": 0
        }
      },
      {"meeting_date": "2026-10-28", "post_rate": 3.17}
    ]};</script>
    """
    bundle = FedFundsFuturesSourceBundle.from_bytes(
        source_url="https://www.frenzycap.com/fedwatch",
        raw_bytes=html,
        retrieved_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    with pytest.raises(NormalizationError, match="probabilities must be an object"):
        parse_fed_funds_futures_snapshot(bundle, current_target_range=None)
