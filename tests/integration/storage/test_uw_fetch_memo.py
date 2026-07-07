"""UwFetchMemoRepository — same-day UW fetch dedupe memo (issue #225).

Money/budget logic: these tests pin the cache-correctness contract at the
storage layer (MISS/HIT, per-date isolation, the SAVE counter, pruning). The
fetcher-level dedupe (one HTTP call across two same-day callers, force_refresh
bypass) is covered in tests/integration/sources/test_uw_fetch_dedupe.py.
"""

from __future__ import annotations

from datetime import date

from uw_scan.storage.uw_fetch_memo import UwFetchMemoRepository

# Realistic frozen payload shape (UW `/option-contracts` — {"data": [...]}).
# One real TSLA row snapshotted from docs/uw-samples/option_contracts.json.
_FROZEN_OC_BODY = {
    "data": [
        {
            "last_price": "2.21",
            "option_symbol": "TSLA260511C00440000",
            "volume": 179385,
            "implied_volatility": "0.748755696476749",
            "open_interest": 5497,
            "nbbo_bid": "2.20",
            "nbbo_ask": "2.24",
        }
    ]
}

_AS_OF = date(2026, 7, 7)
_ENDPOINT = "option_contracts"


def _memo(repo) -> UwFetchMemoRepository:
    return UwFetchMemoRepository(repo.conn, schema=repo._schema)


def test_miss_then_hit_same_key(seeded_db_empty_cards):
    memo = _memo(seeded_db_empty_cards)
    # MISS: nothing stored yet.
    assert memo.get("TSLA", _ENDPOINT, _AS_OF) is None
    # First caller stores the payload.
    memo.put("TSLA", _ENDPOINT, _AS_OF, _FROZEN_OC_BODY)
    # HIT: identical (ticker, endpoint, as_of_date) reuses the stored body.
    hit = memo.get("TSLA", _ENDPOINT, _AS_OF)
    assert hit == _FROZEN_OC_BODY


def test_hit_records_save_counter(seeded_db_empty_cards):
    """Every HIT is a budget SAVE — hit_count is the observable attribution."""
    repo = seeded_db_empty_cards
    memo = _memo(repo)
    memo.put("TSLA", _ENDPOINT, _AS_OF, _FROZEN_OC_BODY)
    memo.get("TSLA", _ENDPOINT, _AS_OF)
    memo.get("TSLA", _ENDPOINT, _AS_OF)
    memo.get("TSLA", _ENDPOINT, _AS_OF)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT hit_count, last_hit_at FROM {repo._schema}.uw_fetch_memo "
            "WHERE ticker=%s AND endpoint=%s AND as_of_date=%s",
            ("TSLA", _ENDPOINT, _AS_OF),
        )
        hit_count, last_hit_at = cur.fetchone()
    assert hit_count == 3  # three same-day reuses recorded
    assert last_hit_at is not None


def test_different_date_is_a_miss(seeded_db_empty_cards):
    """TTL = same trading day: yesterday's row is not a hit for today's key."""
    memo = _memo(seeded_db_empty_cards)
    memo.put("TSLA", _ENDPOINT, date(2026, 7, 6), _FROZEN_OC_BODY)
    assert memo.get("TSLA", _ENDPOINT, date(2026, 7, 7)) is None


def test_different_ticker_and_endpoint_are_misses(seeded_db_empty_cards):
    memo = _memo(seeded_db_empty_cards)
    memo.put("TSLA", _ENDPOINT, _AS_OF, _FROZEN_OC_BODY)
    assert memo.get("NVDA", _ENDPOINT, _AS_OF) is None
    assert memo.get("TSLA", "greek_exposure_by_expiry", _AS_OF) is None


def test_put_is_idempotent_and_preserves_hit_count(seeded_db_empty_cards):
    """A race re-put refreshes payload but never resets the SAVE counter."""
    repo = seeded_db_empty_cards
    memo = _memo(repo)
    memo.put("TSLA", _ENDPOINT, _AS_OF, _FROZEN_OC_BODY)
    memo.get("TSLA", _ENDPOINT, _AS_OF)  # hit_count -> 1
    refreshed = {"data": [{"option_symbol": "TSLA260511C00440000", "volume": 200000}]}
    memo.put("TSLA", _ENDPOINT, _AS_OF, refreshed)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT payload, hit_count FROM {repo._schema}.uw_fetch_memo "
            "WHERE ticker=%s AND endpoint=%s AND as_of_date=%s",
            ("TSLA", _ENDPOINT, _AS_OF),
        )
        payload, hit_count = cur.fetchone()
    assert payload == refreshed
    assert hit_count == 1  # not clobbered back to 0 by the re-put


def test_prune_removes_stale_dates_only(seeded_db_empty_cards):
    memo = _memo(seeded_db_empty_cards)
    memo.put("TSLA", _ENDPOINT, date(2026, 7, 5), _FROZEN_OC_BODY)
    memo.put("TSLA", _ENDPOINT, date(2026, 7, 6), _FROZEN_OC_BODY)
    memo.put("TSLA", _ENDPOINT, date(2026, 7, 7), _FROZEN_OC_BODY)
    removed = memo.prune(before=date(2026, 7, 7))
    assert removed == 2
    assert memo.get("TSLA", _ENDPOINT, date(2026, 7, 7)) is not None
    assert memo.get("TSLA", _ENDPOINT, date(2026, 7, 6)) is None
