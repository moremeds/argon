"""Golden v1 payload-hash regression test (AC-6 / AC-F6).

The pre-existing tests/integration/regime/test_canary_oos_gate.py uses
synthetic seeded rows and does NOT exercise the v1 scoring path. This
test IS the v1-unchanged proof: it runs run_analysis() with the v1
calibration on a fixed input and asserts byte-identical canonical-JSON
output against a captured pre-v2A golden.

If you intentionally change v1 behavior (extremely unlikely — v1 is
shipped), re-run the ad-hoc script in plan §Task-2 Step-1 to recompute.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md
spec §7 AC-6 and §8 AC-F6.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date as _date

import numpy as np

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, load_calibration

# Captured against canary_scoring.py BEFORE the v2-A conditional was applied.
# DO NOT update without re-running the Step-1 capture script.
V1_GOLDEN_HASH = "cb513526a2b12d1da9aa91b031ba4eb36e7a2eecd357542e4c4bb1033e4becf7"


def _fixed_inputs():
    rng = np.random.default_rng(42)
    n = 400
    aligned = {
        "VIX": np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX": np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX": np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }
    base = _date(2020, 6, 1)
    dates = [
        _date.fromordinal(base.toordinal() - (n - 1 - i)).isoformat() for i in range(n)
    ]
    return aligned, dates


def test_v1_payload_hash_unchanged():
    """v1 scoring on fixed inputs MUST produce byte-identical canonical-JSON
    payload to the captured pre-v2A golden. This is AC-6/AC-F6's actual proof —
    the OOS gate test does NOT exercise the v1 scoring path."""
    cal = load_calibration()
    assert cal.composite_version == 1, "default load_calibration must be v1 in PR 1"
    aligned, dates = _fixed_inputs()
    payload = canary_scoring.run_analysis(
        today=_date.fromisoformat(dates[-1]),
        aligned=aligned,
        common_dates=dates,
        sma_50_today=float(aligned["SPX"][-50:].mean()),
        sma_200_today=float(aligned["SPX"][-200:].mean()),
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
        confirmed_canary_active=False,
        buy_the_dip_active=False,
        calibration=cal,
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    actual = hashlib.sha256(canonical.encode()).hexdigest()
    assert actual == V1_GOLDEN_HASH, (
        f"v1 payload hash drifted!\n"
        f"  expected: {V1_GOLDEN_HASH}\n"
        f"  actual:   {actual}\n"
        f"v1 production scoring must be bit-identical to the captured golden. "
        f"If this is intentional, re-run plan §Task-2 Step-1 to recompute."
    )


def test_v1_payload_band_unchanged():
    """Sanity backstop: the band classification on the fixed input is stable."""
    cal = load_calibration()
    aligned, dates = _fixed_inputs()
    payload = canary_scoring.run_analysis(
        today=_date.fromisoformat(dates[-1]),
        aligned=aligned,
        common_dates=dates,
        sma_50_today=float(aligned["SPX"][-50:].mean()),
        sma_200_today=float(aligned["SPX"][-200:].mean()),
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
        confirmed_canary_active=False,
        buy_the_dip_active=False,
        calibration=cal,
    )
    assert payload["canary"]["band"] in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    assert 0.0 <= payload["canary"]["raw_score"] <= 100.0


def test_composite_version_module_constant_is_1_in_pr1():
    """Belt-and-braces invariant: the module constant must stay at 1 for PR 1.
    The flip to 2 is PR 2's job per spec §10."""
    assert COMPOSITE_VERSION == 1, (
        "PR 1 must NOT change COMPOSITE_VERSION. The flip is PR 2's job. See spec §10."
    )
