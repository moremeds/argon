"""evaluate_signal must equal _interpretation_for_index(model, idx=-1) on the
common fields. This pins the extraction so it stays semantics-preserving.

The helper's contract: returns the same dict as evaluate_signal except for
credit_5d_return_pct (which is computed from credit_prices, not the model).
Every other field — including the nested `attribution` block — matches."""

from __future__ import annotations

import numpy as np

from uw_scan.cards import vcg_scoring


def _fake_model(n: int = 100) -> dict:
    rng = np.random.default_rng(0)
    vix = 20 + rng.normal(0, 3, n).cumsum() * 0.05 + 5
    vvix = 95 + rng.normal(0, 4, n).cumsum() * 0.05
    credit = 90 + rng.normal(0, 0.4, n).cumsum() * 0.01
    return vcg_scoring.compute_vcg(vix, vvix, credit)


def test_helper_returns_same_keys_as_signal_minus_credit_5d() -> None:
    """Key-set parity. Catches the case where the extraction accidentally
    drops a field (e.g., attribution) that the script/API depends on."""
    model = _fake_model()
    credit = np.linspace(90, 92, len(model["residuals"]) + 1)
    sig_keys = set(vcg_scoring.evaluate_signal(model, credit).keys())
    helper_keys = set(vcg_scoring._interpretation_for_index(model, idx=-1).keys())
    assert sig_keys - helper_keys == {"credit_5d_return_pct"}, (
        f"helper missing keys evaluate_signal provides: "
        f"{sig_keys - helper_keys - {'credit_5d_return_pct'}}"
    )
    assert helper_keys - sig_keys == set(), (
        f"helper produced unexpected keys: {helper_keys - sig_keys}"
    )


def test_interpretation_for_index_matches_evaluate_signal_at_last_bar() -> None:
    """Value parity at idx=-1. Covers EVERY key in the helper's return,
    including nested `attribution`."""
    model = _fake_model()
    credit = np.linspace(90, 92, len(model["residuals"]) + 1)
    sig = vcg_scoring.evaluate_signal(model, credit)
    helper = vcg_scoring._interpretation_for_index(model, idx=-1)
    for k in helper:
        assert sig[k] == helper[k], f"{k}: signal={sig[k]!r} helper={helper[k]!r}"
