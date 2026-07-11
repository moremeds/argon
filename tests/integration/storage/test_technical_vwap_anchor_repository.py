from datetime import date

from uw_scan.storage.technical_vwap_anchor_repository import (
    TechnicalVwapAnchorRepository,
)


def test_upsert_get_delete_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    vrepo = TechnicalVwapAnchorRepository(repo.conn, schema=repo._schema)

    assert vrepo.get("NVDA") is None

    snap = [{"as_of": "2026-07-06", "vwap": 9.0}, {"as_of": "2026-07-07", "vwap": 10.5}]
    vrepo.upsert("nvda", date(2026, 7, 6), snap)
    got = vrepo.get("NVDA")
    assert got["ticker"] == "NVDA"  # uppercased on write
    assert got["anchor_date"] == date(2026, 7, 6)
    assert got["vwap_snapshot"] == snap
    assert got["computed_at"] is not None

    # re-anchor replaces (one anchor per ticker)
    vrepo.upsert("NVDA", date(2026, 7, 7), snap[1:])
    got2 = vrepo.get("NVDA")
    assert got2["anchor_date"] == date(2026, 7, 7)
    assert got2["vwap_snapshot"] == snap[1:]

    vrepo.delete("NVDA")
    assert vrepo.get("NVDA") is None
    vrepo.delete("NVDA")  # idempotent
