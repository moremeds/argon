"""Hard Guarantees #2 and #3: production default never returns a research row.

Exercises every realistic adversarial ordering: a newer research row of every
non-production shape (JNK / LQD / composite) cannot win the production default.

Located under tests/unit/api/ as the conceptual API-layer isolation guard
even though it uses a real DB fixture (no API client, just the repository
contract that backs the /api/regime/validation call site).
"""

from __future__ import annotations

import time
from datetime import date

import pytest

from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION as VCG_COMPOSITE_VERSION
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

PROD_VERSION = str(VCG_COMPOSITE_VERSION)


def _seed(repo, *, run_scope, credit_proxy, composite_method, composite_version=None):
    if composite_version is None:
        composite_version = PROD_VERSION
    rid = repo.insert_run(
        indicator="vcg",
        composite_version=composite_version,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        window_days=21,
        n_days=252,
        params={},
        summary={"extras": {"credit_proxy": credit_proxy}},
        note=None,
        run_scope=run_scope,
        composite_method=composite_method,
        credit_proxy=credit_proxy,
    )
    repo.mark_run_completed(rid)
    return rid


@pytest.mark.parametrize(
    "research_shape",
    [
        {
            "run_scope": "research",
            "credit_proxy": "JNK",
            "composite_method": "single_proxy",
            "composite_version": "1",
        },
        {
            "run_scope": "research",
            "credit_proxy": "LQD",
            "composite_method": "single_proxy",
            "composite_version": "1",
        },
        {
            "run_scope": "research",
            "credit_proxy": "COMPOSITE_RP3",
            "composite_method": "risk_parity_3",
            "composite_version": "2-candidate-rp3",
        },
    ],
)
def test_production_default_excludes_newer_research_row(
    seeded_db_empty_cards, research_shape
):
    """Exercises the EXACT call site at api/routers/regime_validation.py:289
    (`rb.find_latest_run("vcg")` — NO filters). The repo's VCG-specific defaults
    must enforce Hard Guarantee #2 without the caller passing anything.
    """
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    prod = _seed(
        repo,
        run_scope="production",
        credit_proxy="HYG",
        composite_method="single_proxy",
    )
    time.sleep(0.01)  # ensure research row's created_at > prod
    _seed(repo, **research_shape)
    # CRITICAL: bare call, no filter args. If find_latest_run lacks VCG
    # defaults, this test fails — and so would Hard Guarantee #2 in production.
    latest = repo.find_latest_run("vcg")
    assert latest is not None
    assert latest["id"] == prod
    assert latest["credit_proxy"] == "HYG"
    assert latest["composite_method"] == "single_proxy"
    assert latest["run_scope"] == "production"
