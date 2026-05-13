"""PCR delta-30d derivation."""

from __future__ import annotations

from decimal import Decimal


def compute_pcr_delta_30d(
    today: Decimal | None, prior: Decimal | None
) -> Decimal | None:
    if today is None or prior is None:
        return None
    return today - prior
