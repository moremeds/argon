"""cri.run_live / vcg.run_live — quote splice, carry-forward, slim persist."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.scanners.live_quotes import LiveQuote
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

LAST_BAR = date(2026, 6, 11)
SESSION = date(2026, 6, 12)  # a Friday — the live session being computed
N_BARS = 130


def _weekdays_back(end: date, n: int) -> list[date]:
    out: list[date] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def _row(symbol: str, d: date, close: float, adj_close: float | None = None) -> dict:
    return {
        "symbol": symbol,
        "trade_date": d,
        "open": None,
        "high": None,
        "low": None,
        "close": close,
        "adj_close": adj_close,
        "volume": None,
    }


def _seed(conn) -> None:
    vol_repo = VolIndexRepository(conn)
    days = _weekdays_back(LAST_BAR, N_BARS)
    rows = []
    for i, d in enumerate(days):
        rows.append(_row("VIX", d, 18.0 + 0.01 * i))
        rows.append(_row("VVIX", d, 95.0 + 0.05 * i))
        rows.append(_row("COR1M", d, 15.0 + 0.01 * i))
        rows.append(_row("SPX", d, 7000.0 + 2.0 * i))
        rows.append(_row("VIX3M", d, 19.0 + 0.01 * i))
        rows.append(_row("HYG", d, 79.0 + 0.005 * i, adj_close=79.0 + 0.005 * i))
    vol_repo.upsert_rows(rows)
    conn.commit()


def _quote(sym: str, price: float) -> LiveQuote:
    quoted = datetime.combine(SESSION, time(15, 30), tzinfo=timezone.utc)
    return LiveQuote(symbol=sym, price=price, quoted_at=quoted, source="xenon_ws")


def test_cri_run_live_splices_quotes_and_carries_missing(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    _seed(conn)
    quotes = {
        "VIX": _quote("VIX", 25.5),
        "VVIX": _quote("VVIX", 112.0),
        "SPX": _quote("SPX", 7300.0),
        # COR1M and VIX3M intentionally absent → carry-forward
    }
    payload = cri_scanner.run_live(conn, quotes=quotes)
    assert payload is not None
    assert payload["basis"] == "live"
    assert payload["date"] == SESSION.isoformat()
    assert payload["vix"] == 25.5
    assert payload["spy"] == 7300.0
    assert payload["cor1m"] is not None  # carried forward from LAST_BAR
    assert "COR1M" in payload["carried_forward"]
    assert set(payload["live_quotes"]) == {"VIX", "VVIX", "SPX"}


def test_cri_run_live_persist_writes_slim_live_row(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    _seed(conn)
    quotes = {
        "VIX": _quote("VIX", 25.5),
        "VVIX": _quote("VVIX", 112.0),
        "SPX": _quote("SPX", 7300.0),
    }
    payload = cri_scanner.run_live(conn, quotes=quotes, persist=True)
    assert payload is not None
    snap = CriSnapshotRepository(conn).fetch_latest(basis="live")
    assert snap is not None
    assert "history" not in snap and "spy_closes" not in snap  # slim
    assert snap["vix"] == 25.5
    assert CriSnapshotRepository(conn).fetch_latest(basis="eod") is None


def test_cri_run_live_no_quotes_returns_none(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    _seed(conn)
    assert cri_scanner.run_live(conn, quotes={}) is None


def test_vcg_run_live_splices_credit_quote(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    _seed(conn)
    quotes = {
        "VIX": _quote("VIX", 25.5),
        "VVIX": _quote("VVIX", 112.0),
        "HYG": _quote("HYG", 78.9),
    }
    payload = vcg_scanner.run_live(conn, quotes=quotes, persist=True)
    assert payload is not None
    assert payload["basis"] == "live"
    assert payload["signal"]["credit_price"] == 78.9
    snap = VcgSnapshotRepository(conn).fetch_latest(proxy="HYG", basis="live")
    assert snap is not None and "history" not in snap
