"""Every macro domain's engine version and parameter version move together.

``engine_version`` is a selector: states are keyed ``(domain, as_of, engine_version,
inputs_hash)`` and readers filter on it to get one engine's semantics.  ``Parameters.version``
labels the calibration.  Splitting them lets a recalibrated engine keep publishing under the
old engine identity, so a reader asking for one semantics silently gets two.

This was not hypothetical: moving USD's momentum threshold bumped the parameter version and
left the engine version behind, and nothing failed.
"""

from __future__ import annotations

import pytest
from uw_scan.macro.gold_state import GOLD_ENGINE_VERSION, DEFAULT_GOLD_PARAMETERS
from uw_scan.macro.inflation import INFLATION_ENGINE_VERSION, DEFAULT_INFLATION_PARAMETERS
from uw_scan.macro.rates import RATES_ENGINE_VERSION, DEFAULT_RATES_PARAMETERS
from uw_scan.macro.usd import USD_ENGINE_VERSION, DEFAULT_USD_PARAMETERS

DOMAINS = [
    ("gold", GOLD_ENGINE_VERSION, DEFAULT_GOLD_PARAMETERS),
    ("inflation", INFLATION_ENGINE_VERSION, DEFAULT_INFLATION_PARAMETERS),
    ("policy_rates", RATES_ENGINE_VERSION, DEFAULT_RATES_PARAMETERS),
    ("usd", USD_ENGINE_VERSION, DEFAULT_USD_PARAMETERS),
]


@pytest.mark.parametrize("domain,engine_version,parameters", DOMAINS)
def test_engine_and_parameter_versions_agree(domain, engine_version, parameters) -> None:
    assert engine_version == parameters.version, (
        f"{domain}: engine_version {engine_version!r} and parameter version "
        f"{parameters.version!r} disagree. A recalibration must move BOTH, or readers "
        f"filtering on engine_version get two different semantics under one label."
    )
