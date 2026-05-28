from __future__ import annotations

import pytest

from uw_scan.api.schemas import VcgSignal


def _v1_payload() -> dict:
    return {
        "vcg": 0.5,
        "vcg_adj": 0.4,
        "residual": 0.001,
        "beta1_vvix": -0.02,
        "beta2_vix": -0.01,
        "alpha": 0.0,
        "vix": 18.0,
        "vvix": 90.0,
        "credit_price": 80.5,
        "credit_5d_return_pct": 0.5,
        "ro": 0,
        "edr": 0,
        "tier": None,
        "bounce": 0,
        "vvix_severity": "moderate",
        "sign_ok": True,
        "sign_suppressed": False,
        "pi_panic": 0.0,
        "regime": "DIVERGENCE",
        "interpretation": "NORMAL",
        "attribution": {
            "vvix_pct": 60.0,
            "vix_pct": 40.0,
            "vvix_component": 0.001,
            "vix_component": 0.001,
            "model_implied": 0.002,
        },
    }


def test_vcg_payload_accepts_v1_without_percentiles() -> None:
    model = VcgSignal.model_validate(_v1_payload())
    assert model.vix_percentile_rank is None
    assert model.vvix_percentile_rank is None


def test_vcg_payload_accepts_v2_with_percentiles() -> None:
    payload = _v1_payload()
    payload["vix_percentile_rank"] = 0.97
    payload["vvix_percentile_rank"] = 0.96
    model = VcgSignal.model_validate(payload)
    assert model.vix_percentile_rank == pytest.approx(0.97)
    assert model.vvix_percentile_rank == pytest.approx(0.96)


def test_vcg_payload_accepts_v2_with_nan_percentiles_as_null() -> None:
    payload = _v1_payload()
    payload["vix_percentile_rank"] = None
    payload["vvix_percentile_rank"] = None
    model = VcgSignal.model_validate(payload)
    assert model.vix_percentile_rank is None
    assert model.vvix_percentile_rank is None
