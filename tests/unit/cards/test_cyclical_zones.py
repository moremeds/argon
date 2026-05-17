"""Lens 2 — cyclical posture (article zones + heuristic narrative)."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.cards.cyclical_zones import (
    classify_article_zone,
    compute_cyclical_posture,
)


def test_zone_real_rate_driven():
    assert classify_article_zone(Decimal("1.5"), Decimal("2.3")) == "real-rate-driven"


def test_zone_moderate_trap():
    assert classify_article_zone(Decimal("3.0"), Decimal("2.6")) == "moderate-trap"


def test_zone_article_unanchored():
    assert classify_article_zone(Decimal("4.5"), Decimal("3.1")) == "article-unanchored"


def test_zone_transitional_otherwise():
    assert classify_article_zone(Decimal("3.5"), Decimal("3.5")) == "transitional"


def test_cyclical_posture_uses_heuristic_badge_in_narrative():
    posture = compute_cyclical_posture(
        cpi_yoy=Decimal("2.8"),
        t5yifr=Decimal("2.31"),
        dfii10=Decimal("1.97"),
        dfii10_60d_change_bps=Decimal("12"),
        factors={"F1": -0.4, "F5": 1.8},
        gauge_state="suspended",
    )
    assert posture.zone_label == "moderate-trap"
    assert (
        "heuristic" in posture.narrative_text.lower()
        or "article" in posture.narrative_text.lower()
    )


def test_cyclical_posture_suspended_uses_informative_framing():
    posture = compute_cyclical_posture(
        cpi_yoy=Decimal("1.5"),
        t5yifr=Decimal("2.3"),
        dfii10=Decimal("1.0"),
        dfii10_60d_change_bps=Decimal("-20"),
        factors={},
        gauge_state="suspended",
    )
    assert (
        "suspended" in posture.narrative_text.lower()
        or "not actionable" in posture.narrative_text.lower()
        or "informative" in posture.narrative_text.lower()
    )
