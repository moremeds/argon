"""The embedded trade-skills KB loads as a single non-trivial string constant."""

from __future__ import annotations


def test_kb_contains_core_anchors():
    from uw_scan.reports.trade_blast.trade_framework_kb import (
        TRADE_FRAMEWORK_KNOWLEDGE,
    )

    kb = TRADE_FRAMEWORK_KNOWLEDGE
    assert "Tape" in kb and "DCF" in kb  # operating principle
    assert "Direction" in kb and "Vega" in kb and "Asymmetry" in kb  # 3 axes
    assert "TSEM" in kb or "tsem" in kb  # case study present
    assert "channel checks" in kb  # the 8-factor conviction ledger
    assert len(kb) > 100_000  # full library, not a stub


def test_kb_sections_ordered():
    from uw_scan.reports.trade_blast.trade_framework_kb import (
        TRADE_FRAMEWORK_KNOWLEDGE,
    )

    kb = TRADE_FRAMEWORK_KNOWLEDGE
    # deterministic section order: operating principles -> frameworks -> pitfalls -> cases
    assert kb.index("Operating principles") < kb.index("Pitfalls")
    assert kb.index("Pitfalls") < kb.index("Case studies")
