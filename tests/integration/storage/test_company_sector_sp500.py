"""The sector-fill universe widens to S&P 500 members; sectors_for reads the cache.

GE's NULL is a labelled test double for "asked and the vendor had no sector".
It makes no claim about GE's real classification.
"""

from __future__ import annotations

from uw_scan.storage.company_sector import CompanySectorRepository


def _repo(seeded) -> CompanySectorRepository:
    return CompanySectorRepository(seeded.conn, schema=seeded._schema)


def test_extra_names_are_asked_once_uppercased_and_skip_known_rows(
    seeded_db_empty_cards,
):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert("AAPL", "Technology")
    out = repo.tickers_needing_fetch(5000, extra=["GE", "pkg", "AAPL", "GE"])
    assert "GE" in out and "PKG" in out
    assert "AAPL" not in out
    assert out == sorted(set(out))  # UNION dedupes; ordering kept


def test_sectors_for_separates_never_asked_from_asked_null(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert("AAPL", "Technology")
    repo.upsert("GE", None)
    assert repo.sectors_for(["aapl", "GE", "PKG"]) == {"AAPL": "Technology", "GE": None}
    assert repo.sectors_for([]) == {}
