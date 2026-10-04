"""Exceptions shared across sources and domains (I-58).

``NormalizationError`` used to live in the UW-specific ``normalize.py`` while the
FRED, Fed SEP/FOMC, CFTC, NY Fed and rates parsers imported it from there.
``normalize`` re-exports it, so ``except normalize.NormalizationError`` still
catches the same class.
"""

from __future__ import annotations


class NormalizationError(Exception):
    """Raised when a payload cannot be normalized."""


# Persisted identity: macro ingest stores ``f"{module}.{name}"`` as the release
# error_type (macro_market_layer_ingest._error_parts), and existing rows say
# ``uw_scan.normalize.NormalizationError``. Keep that string stable across the move.
NormalizationError.__module__ = "uw_scan.normalize"
