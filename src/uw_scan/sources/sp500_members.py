"""S&P 500 membership for sector RS breadth: a VENDORED list, not an apex call.

Ruling 2026-09-26 (spec §4). On 2026-09-26, apex GET /v1/membership/sp500
returned about 35 rows with a null symbol and dead tickers (BHGE, SBC, PKI,
FISV, Q, FDXF, HONA, MRSH, VMRK), and it was missing META, XOM, AVGO, LIN,
MDT and ETN. A point-in-time read before 2026-09-17 returns about half the
index. livewire's presets/sp500.json is clean, but it is outside the lake
mount the argon container sees, so scripts/research/sync_sp500_members.py
copies it into sources/data/ and it ships as package data
(pyproject [tool.setuptools.package-data], same convention as
uw_scan.cards/data).

This is the CURRENT list, applied to every session by the nightly job and the
backfill alike. Breadth history is therefore survivorship-biased by
construction.
"""

from __future__ import annotations

import json
from collections import Counter
from functools import cache
from importlib.resources import files

#: Fewer names than this means a truncated or broken source, not an index.
MIN_MEMBERS = 450


class Sp500ListInvalid(ValueError):
    """The vendored list is unreadable or failed validation. Write no gics rows from it."""


def validate_tickers(tickers: object) -> tuple[str, ...]:
    """Upper-cased, sorted, distinct tickers, or Sp500ListInvalid.

    Shared by the runtime reader and the sync script, so the file cannot be
    written in a shape the reader would then refuse.
    """
    if not isinstance(tickers, list) or not all(
        isinstance(t, str) and t.strip() for t in tickers
    ):
        raise Sp500ListInvalid("tickers must be a list of non-empty strings")
    norm = [t.strip().upper() for t in tickers]
    dupes = sorted(t for t, n in Counter(norm).items() if n > 1)
    if dupes:
        raise Sp500ListInvalid(f"duplicate tickers: {dupes[:10]}")
    if len(norm) < MIN_MEMBERS:
        raise Sp500ListInvalid(f"{len(norm)} tickers < {MIN_MEMBERS}")
    return tuple(sorted(norm))


@cache
def sp500_members() -> tuple[str, ...]:
    """The vendored current S&P 500 tickers. Raises Sp500ListInvalid."""
    try:
        body = json.loads(
            (files("uw_scan.sources") / "data" / "sp500_members.json").read_text()
        )
    except (OSError, ValueError) as exc:
        raise Sp500ListInvalid(f"cannot read vendored sp500 list: {exc!r}") from exc
    return validate_tickers(body.get("tickers") if isinstance(body, dict) else None)
