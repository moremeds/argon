"""Fixture-backed provider doubles for the macro policy worker jobs.

Not a test module: shared by the per-release ingest tests and the 4x4 smoke so
both drive the SAME production entry points off the same pinned official bytes.
The bytes are real Federal Reserve and New York Fed releases captured once and
frozen under tests/fixtures/macro; nothing here fabricates a policy value.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesSourceBundle
from uw_scan.sources.fed_sep import SepSourceBundle
from uw_scan.sources.fomc_statement import FomcStatementBundle
from uw_scan.sources.nyfed_sme import SmeSourceBundle

FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"


def _outcome(candidate, bundle, *, artifacts=None, error=None):
    """Mimic the provider fetch-outcome contract without importing four classes."""
    return SimpleNamespace(
        candidate=candidate,
        bundle=bundle,
        artifacts=artifacts
        or ((bundle.primary_artifact, bundle.accessible_artifact) if bundle else ()),
        error_type=error[0] if error else None,
        error_message=error[1] if error else None,
    )


def _candidate(release_key, release_type, event_date, event_class=None):
    return SimpleNamespace(
        release_key=release_key,
        release_type=release_type,
        event_date=event_date,
        event_class=event_class,
        discovery_url=(
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        ),
    )


class _StatementProvider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_outcomes(self, *, years, retrieved_at):
        assert 2026 in years
        return [
            _outcome(
                _candidate(
                    "fomc-statement:monetary20260617a",
                    "statement",
                    date(2026, 6, 17),
                    "scheduled_meeting",
                ),
                bundle,
            )
            for bundle in self._bundles(retrieved_at)
        ]

    def _bundles(self, retrieved_at):
        return [
            FomcStatementBundle.from_bytes(
                meeting_date=date(2026, 6, 17),
                accessible_url=(
                    "https://www.federalreserve.gov/newsevents/pressreleases/"
                    "monetary20260617a.htm"
                ),
                accessible_bytes=(
                    FIXTURES / "fomc_statement_2026_06.html"
                ).read_bytes(),
                pdf_url=(
                    "https://www.federalreserve.gov/monetarypolicy/files/"
                    "monetary20260617a1.pdf"
                ),
                pdf_bytes=(FIXTURES / "fomc_statement_2026_06.pdf").read_bytes(),
                retrieved_at=retrieved_at,
            )
        ]


class _SepProvider:
    pdf_suffix = b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_outcomes(self, *, years, retrieved_at):
        assert 2026 in years
        return [
            _outcome(
                _candidate("fed-sep:fomcprojtabl20260617", "sep", date(2026, 6, 17)),
                bundle,
            )
            for bundle in self._bundles(retrieved_at)
        ]

    def _bundles(self, retrieved_at):
        return [
            SepSourceBundle.from_bytes(
                meeting_date=date(2026, 6, 17),
                accessible_url=(
                    "https://www.federalreserve.gov/monetarypolicy/"
                    "fomcprojtabl20260617.htm"
                ),
                accessible_bytes=(FIXTURES / "fed_sep_2026_06.html").read_bytes(),
                pdf_url=(
                    "https://www.federalreserve.gov/monetarypolicy/files/"
                    "fomcprojtabl20260617.pdf"
                ),
                pdf_bytes=(FIXTURES / "fed_sep_2026_06.pdf").read_bytes()
                + self.pdf_suffix,
                retrieved_at=retrieved_at,
            )
        ]


class _ChangedSepProvider(_SepProvider):
    pdf_suffix = b"publisher-correction"


class _CorrectedSepProvider(_SepProvider):
    """A reissue that changes a published projection -- a genuinely new fact.

    Distinct from _ChangedSepProvider, which only perturbs the PDF's bytes: the
    facts there are unchanged, so it produces a second witness rather than a
    second observation. This one changes what the release says.
    """

    def _bundles(self, retrieved_at):
        html = (FIXTURES / "fed_sep_2026_06.html").read_bytes()
        corrected = html.replace(b">3.4<", b">3.9<", 1)
        assert corrected != html, "fixture no longer contains the value to correct"
        return [
            SepSourceBundle.from_bytes(
                meeting_date=date(2026, 6, 17),
                accessible_url=(
                    "https://www.federalreserve.gov/monetarypolicy/"
                    "fomcprojtabl20260617.htm"
                ),
                accessible_bytes=corrected,
                pdf_url=(
                    "https://www.federalreserve.gov/monetarypolicy/files/"
                    "fomcprojtabl20260617.pdf"
                ),
                pdf_bytes=(FIXTURES / "fed_sep_2026_06.pdf").read_bytes(),
                retrieved_at=retrieved_at,
            )
        ]


class _MalformedSepProvider(_SepProvider):
    def _bundles(self, retrieved_at):
        bundle = super()._bundles(retrieved_at)[0]
        return [
            SepSourceBundle.from_bytes(
                meeting_date=bundle.meeting_date,
                accessible_url=bundle.accessible_artifact.source_url or "",
                accessible_bytes=(
                    b"<p>For release at 2:00 p.m., EDT, June 17, 2026</p>"
                ),
                pdf_url=bundle.primary_artifact.source_url or "",
                pdf_bytes=bundle.primary_artifact.raw_bytes or b"",
                retrieved_at=retrieved_at,
            )
        ]


class _SmeProvider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_latest_bundle(self, *, retrieved_at):
        return SmeSourceBundle.from_bytes(
            survey_month=date(2026, 6, 1),
            data_url=(
                "https://www.newyorkfed.org/medialibrary/media/markets/survey/"
                "2026/jun-2026-data.xlsx"
            ),
            data_bytes=(FIXTURES / "nyfed_sme_2026_06.xlsx").read_bytes(),
            report_url=(
                "https://www.newyorkfed.org/medialibrary/media/markets/survey/"
                "2026/jun-2026-sme-results.pdf"
            ),
            report_bytes=(FIXTURES / "nyfed_sme_2026_06.pdf").read_bytes(),
            retrieved_at=retrieved_at,
        )


class _MarketProvider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_bundle(self, *, retrieved_at):
        raw = b"""
        <script>window.__SSR_DATA__ = {
          "current_effr": 3.67,
          "current_rate": 3.75,
          "meetings": [{
            "meeting_date": "2026-09-16",
            "post_rate": 3.42,
            "probabilities": {
              "cut_25": 0.70, "cut_gt25": 0.10, "hold": 0.20,
              "hike_25": 0.0, "hike_gt25": 0.0
            }
          }],
          "next_meeting": "2026-09-16"
        };</script>
        """
        return FedFundsFuturesSourceBundle.from_bytes(
            source_url="https://www.frenzycap.com/fedwatch",
            raw_bytes=raw,
            retrieved_at=retrieved_at,
        )
